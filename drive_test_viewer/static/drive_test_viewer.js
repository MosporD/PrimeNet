let dtMap = null;
let trackLayer = null;
let startMarker = null;
let endMarker = null;
let playbackMarker = null;
let gpxPoints = [];
let playbackIndex = 0;
let playbackTimer = null;
let playbackStepMs = 500;
let siteLayer = null;
let siteMarkers = [];
let allSites = [];
let sitesEnabled = false;
let rfMetricSeries = null;
let rfOverlayLayer = null;

window.addEventListener('DOMContentLoaded', () => {
    initMap();
    const form = document.getElementById('dtUploadForm');
    form.addEventListener('submit', handleUpload);
    updateSitesUiState();
});

function initMap() {
    dtMap = L.map('driveTestMap').setView([31.9539, 35.9106], 11);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; OpenStreetMap contributors',
        maxZoom: 19,
    }).addTo(dtMap);
    siteLayer = L.layerGroup().addTo(dtMap);
}

function resetPlayback() {
    stopPlayback();
    playbackIndex = 0;
    const slider = document.getElementById('playbackSlider');
    const playBtn = document.getElementById('playPauseBtn');
    slider.value = '0';
    slider.disabled = gpxPoints.length === 0;
    slider.max = gpxPoints.length > 0 ? String(gpxPoints.length - 1) : '0';
    playBtn.disabled = gpxPoints.length === 0;
    playBtn.textContent = 'Play';
    updatePlaybackMarkerAndLabel();
}

function updatePlaybackSpeed() {
    const selected = Number(document.getElementById('playbackSpeed').value || 500);
    playbackStepMs = Number.isFinite(selected) ? Math.max(100, selected) : 500;
    if (playbackTimer) {
        stopPlayback();
        startPlayback();
    }
}

function updatePlaybackMarkerAndLabel() {
    const label = document.getElementById('playbackLabel');
    if (!gpxPoints.length) {
        label.textContent = '0 / 0';
        return;
    }
    const idx = Math.min(Math.max(0, playbackIndex), gpxPoints.length - 1);
    const p = gpxPoints[idx];
    const latlng = [p.lat, p.lng];
    if (playbackMarker) dtMap.removeLayer(playbackMarker);
    playbackMarker = L.circleMarker(latlng, {
        radius: 7,
        color: '#f39c12',
        fillColor: '#f39c12',
        fillOpacity: 0.95,
        weight: 2,
    }).addTo(dtMap);
    const t = p.time || '-';
    playbackMarker.bindPopup(`Point ${idx + 1}<br>${escapeHtml(t)}`);
    label.textContent = `${idx + 1} / ${gpxPoints.length}`;
}

function onPlaybackSliderChange() {
    if (!gpxPoints.length) return;
    playbackIndex = Number(document.getElementById('playbackSlider').value || 0);
    updatePlaybackMarkerAndLabel();
}

function startPlayback() {
    if (!gpxPoints.length || playbackTimer) return;
    document.getElementById('playPauseBtn').textContent = 'Pause';
    playbackTimer = setInterval(() => {
        if (playbackIndex >= gpxPoints.length - 1) {
            stopPlayback();
            return;
        }
        playbackIndex += 1;
        document.getElementById('playbackSlider').value = String(playbackIndex);
        updatePlaybackMarkerAndLabel();
    }, playbackStepMs);
}

function stopPlayback() {
    if (playbackTimer) {
        clearInterval(playbackTimer);
        playbackTimer = null;
    }
    const btn = document.getElementById('playPauseBtn');
    if (btn) btn.textContent = 'Play';
}

function togglePlayback() {
    if (playbackTimer) stopPlayback();
    else startPlayback();
}

function setStatus(message, type = 'info') {
    const el = document.getElementById('uploadStatus');
    el.className = `status-message ${type}`;
    el.textContent = message;
}

function fmtBytes(bytes) {
    const n = Number(bytes || 0);
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
    return `${(n / (1024 * 1024)).toFixed(2)} MB`;
}

async function handleUpload(event) {
    event.preventDefault();
    const fd = new FormData();
    const gpx = document.getElementById('gpxFile').files[0];
    const nmfs = document.getElementById('nmfsFile').files[0];
    if (gpx) fd.append('gpx_file', gpx);
    if (nmfs) fd.append('nmfs_file', nmfs);
    if (!gpx && !nmfs) {
        setStatus('Please choose at least one file.', 'error');
        return;
    }
    setStatus('Uploading and parsing files...', 'info');
    try {
        const res = await fetch('/api/drive-test-viewer/upload', {
            method: 'POST',
            body: fd,
        });
        const data = await res.json();
        if (!data.success) throw new Error(data.error || 'Upload failed');
        if (data.gpx) renderGpx(data.gpx);
        if (data.nmfs) renderNmfs(data.nmfs);
        setStatus('Files parsed successfully.', 'success');
    } catch (error) {
        setStatus(error.message || 'Upload failed', 'error');
    }
}

function renderGpx(gpx) {
    const panel = document.getElementById('gpxSummary');
    panel.innerHTML = `
        <h4>GPX Summary</h4>
        <div><strong>File:</strong> ${escapeHtml(gpx.file_name || '-')}</div>
        <div><strong>Points:</strong> ${Number(gpx.point_count || 0).toLocaleString()}</div>
        <div><strong>Start:</strong> ${escapeHtml(gpx.start_time || '-')}</div>
        <div><strong>End:</strong> ${escapeHtml(gpx.end_time || '-')}</div>
    `;
    const points = Array.isArray(gpx.points) ? gpx.points : [];
    gpxPoints = points;
    if (!points.length || !dtMap) {
        resetPlayback();
        return;
    }
    const latlngs = points.map((p) => [p.lat, p.lng]);
    if (trackLayer) dtMap.removeLayer(trackLayer);
    if (startMarker) dtMap.removeLayer(startMarker);
    if (endMarker) dtMap.removeLayer(endMarker);
    trackLayer = L.polyline(latlngs, { color: '#e74c3c', weight: 3 }).addTo(dtMap);
    startMarker = L.circleMarker(latlngs[0], {
        radius: 6, color: '#2ecc71', fillColor: '#2ecc71', fillOpacity: 0.9,
    }).addTo(dtMap).bindPopup('Start');
    endMarker = L.circleMarker(latlngs[latlngs.length - 1], {
        radius: 6, color: '#3498db', fillColor: '#3498db', fillOpacity: 0.9,
    }).addTo(dtMap).bindPopup('End');
    dtMap.fitBounds(trackLayer.getBounds(), { padding: [24, 24] });
    renderRfOverlay();
    resetPlayback();
}

function renderNmfs(nmfs) {
    const panel = document.getElementById('nmfsSummary');
    const rows = Array.isArray(nmfs.records_preview) ? nmfs.records_preview : [];
    const tags = nmfs.record_tags && typeof nmfs.record_tags === 'object' ? Object.entries(nmfs.record_tags) : [];
    const entropyRows = Array.isArray(nmfs.high_entropy_windows) ? nmfs.high_entropy_windows : [];
    const tsRows = Array.isArray(nmfs.timestamp_candidates) ? nmfs.timestamp_candidates : [];
    const kpiCandidates = nmfs.kpi_candidates && typeof nmfs.kpi_candidates === 'object' ? nmfs.kpi_candidates : {};
    const eventRef = nmfs.nemo_event_reference && typeof nmfs.nemo_event_reference === 'object' ? nmfs.nemo_event_reference : {};
    const mapper = nmfs.nemo_object_mapper_summary && typeof nmfs.nemo_object_mapper_summary === 'object'
        ? nmfs.nemo_object_mapper_summary
        : null;
    rfMetricSeries = nmfs.metric_series && typeof nmfs.metric_series === 'object' ? nmfs.metric_series : null;
    const kpiText = Object.entries(kpiCandidates).map(([name, rows]) => {
        const list = Array.isArray(rows) ? rows : [];
        if (!list.length) return `${name}: none`;
        return `${name}\n` + list.map((r) =>
            `  @${r.offset} count=${r.count} avg=${r.avg} min=${r.min} max=${r.max} smooth=${r.smooth_ratio}`
        ).join('\n');
    }).join('\n\n');
    const eventRefText = Object.entries(eventRef).map(([eventId, meta]) => {
        const params = Array.isArray(meta.params) ? meta.params : [];
        return `${eventId} - ${meta.name || '-'}\n  Params: ${params.slice(0, 12).join(', ') || 'n/a'}${params.length > 12 ? ' ...' : ''}`;
    }).join('\n\n');
    const mapperText = mapper
        ? [
            `Total logs: ${mapper.total_logs ?? '-'}`,
            `Formats: ${Array.isArray(mapper.formats) ? mapper.formats.join(', ') : '-'}`,
            `Technologies: ${mapper.technology_counts ? Object.entries(mapper.technology_counts).map(([k, v]) => `${k}:${v}`).join(', ') : '-'}`,
            `Protocols: ${mapper.protocol_counts ? Object.entries(mapper.protocol_counts).map(([k, v]) => `${k}:${v}`).join(', ') : '-'}`,
        ].join('\n')
        : 'No object mapper summary available';
    panel.innerHTML = `
        <h4>NMFS Summary</h4>
        <div><strong>File:</strong> ${escapeHtml(nmfs.file_name || '-')}</div>
        <div><strong>Size:</strong> ${fmtBytes(nmfs.size_bytes)}</div>
        <div><strong>Format:</strong> ${escapeHtml(nmfs.format_hint || '-')}</div>
        <div><strong>Header:</strong> <code>${escapeHtml(nmfs.header_ascii || '-')}</code></div>
        <div><strong>Record lines:</strong> ${Number(nmfs.records_found || 0).toLocaleString()}</div>
        <div><strong>Payload ASCII ratio:</strong> ${(Number(nmfs.payload_ascii_ratio || 0) * 100).toFixed(2)}%</div>
        <div><strong>Payload type:</strong> ${nmfs.likely_encoded_payload ? 'Likely encoded/compressed' : 'Mostly plain text'}</div>
        <h5>Record Tags</h5>
        <pre class="nmfs-preview">${escapeHtml(tags.map(([k, v]) => `${k}: ${v}`).join('\n') || 'No tags found')}</pre>
        <h5>High Entropy Zones</h5>
        <pre class="nmfs-preview">${escapeHtml(entropyRows.map((r) => `${r.offset_start}-${r.offset_end}: ${r.entropy}`).join('\n') || 'None detected')}</pre>
        <h5>Timestamp Candidates (LE uint32)</h5>
        <pre class="nmfs-preview">${escapeHtml(tsRows.slice(0, 60).map((r) => `offset ${r.offset}: ${r.epoch_sec}`).join('\n') || 'None found')}</pre>
        <h5>Radio KPI Candidate Streams (Heuristic)</h5>
        <pre class="nmfs-preview">${escapeHtml(kpiText || 'No candidate streams detected')}</pre>
        <h5>Map RF Overlay</h5>
        <pre class="nmfs-preview">${escapeHtml(describeRfOverlay(rfMetricSeries))}</pre>
        <h5>Nemo Event Reference Match</h5>
        <pre class="nmfs-preview">${escapeHtml(eventRefText || 'No matching Nemo event docs for detected tags')}</pre>
        <h5>Nemo Object Mapper Summary</h5>
        <pre class="nmfs-preview">${escapeHtml(mapperText)}</pre>
        <h5>Metadata Preview</h5>
        <pre class="nmfs-preview">${escapeHtml(rows.join('\n') || 'No records found')}</pre>
    `;
    renderRfOverlay();
}

function describeRfOverlay(metricSeries) {
    if (!metricSeries || typeof metricSeries !== 'object') {
        return 'No candidate RF series available from NMFS payload.';
    }
    const keys = Object.keys(metricSeries);
    if (!keys.length) return 'No candidate RF series available from NMFS payload.';
    return keys.map((k) => {
        const row = metricSeries[k] || {};
        return `${k}: count=${row.count ?? 0}, min=${row.min ?? '-'}, max=${row.max ?? '-'}, avg=${row.avg ?? '-'}`;
    }).join('\n');
}

function pickOverlayMetric() {
    if (!rfMetricSeries || typeof rfMetricSeries !== 'object') return null;
    for (const key of ['rsrp_dbm', 'rscp_dbm', 'rsrq_db', 'ecno_db']) {
        const row = rfMetricSeries[key];
        if (row && Array.isArray(row.series) && row.series.length >= 20) return { key, ...row };
    }
    return null;
}

function metricColor(metricKey, value) {
    if (!Number.isFinite(value)) return '#7f8c8d';
    if (metricKey === 'rsrp_dbm' || metricKey === 'rscp_dbm') {
        if (value >= -85) return '#2ecc71';
        if (value >= -100) return '#f1c40f';
        return '#e74c3c';
    }
    if (metricKey === 'rsrq_db' || metricKey === 'ecno_db') {
        if (value >= -8) return '#2ecc71';
        if (value >= -12) return '#f1c40f';
        return '#e74c3c';
    }
    return '#3498db';
}

function renderRfOverlay() {
    if (!dtMap) return;
    if (rfOverlayLayer) {
        dtMap.removeLayer(rfOverlayLayer);
        rfOverlayLayer = null;
    }
    if (!gpxPoints.length) return;
    const metric = pickOverlayMetric();
    if (!metric) return;
    const series = metric.series || [];
    if (series.length < 2 || gpxPoints.length < 2) return;

    const group = L.layerGroup();
    const segmentCount = Math.min(gpxPoints.length - 1, 1200);
    for (let i = 0; i < segmentCount; i++) {
        const p1 = gpxPoints[i];
        const p2 = gpxPoints[i + 1];
        const sIdx = Math.min(series.length - 1, Math.round((i / Math.max(1, segmentCount - 1)) * (series.length - 1)));
        const val = Number(series[sIdx]);
        const color = metricColor(metric.key, val);
        L.polyline([[p1.lat, p1.lng], [p2.lat, p2.lng]], {
            color,
            weight: 4,
            opacity: 0.9,
        }).bindTooltip(`${metric.key}: ${Number.isFinite(val) ? val : '-'}`).addTo(group);
    }
    rfOverlayLayer = group.addTo(dtMap);
}

async function loadSites() {
    if (!sitesEnabled) return;
    try {
        const vendor = document.getElementById('siteVendorFilter').value;
        const tech = document.getElementById('siteTechFilter').value;
        const params = new URLSearchParams();
        if (tech) params.set('tech', tech);
        const res = await fetch(`/api/map/sites?${params.toString()}`);
        const data = await res.json();
        if (!data.success) throw new Error(data.error || 'Failed to load sites');
        allSites = Array.isArray(data.sites) ? data.sites : [];
        if (vendor) {
            allSites = allSites.filter((s) => String(s.vendor || '') === vendor);
        }
        renderSiteList();
        renderSiteMarkers(allSites);
    } catch (error) {
        const list = document.getElementById('siteList');
        list.innerHTML = `<div class="placeholder">${escapeHtml(error.message)}</div>`;
    }
}

function toggleSitesLayer() {
    sitesEnabled = !sitesEnabled;
    if (!sitesEnabled) {
        allSites = [];
        renderSiteList();
        renderSiteMarkers([]);
    } else {
        loadSites();
    }
    updateSitesUiState();
}

function updateSitesUiState() {
    const btn = document.getElementById('toggleSitesBtn');
    const hint = document.getElementById('siteToggleHint');
    const controls = ['siteSearch', 'siteVendorFilter', 'siteTechFilter'];
    controls.forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.disabled = !sitesEnabled;
    });
    if (btn) btn.textContent = sitesEnabled ? 'Hide Sites' : 'Load Sites';
    if (hint) hint.textContent = sitesEnabled ? 'Site layer is active.' : 'Optional: load site layer if needed.';
}

function renderSiteList() {
    const search = (document.getElementById('siteSearch').value || '').trim().toLowerCase();
    const list = document.getElementById('siteList');
    const rows = allSites.filter((s) => {
        if (!search) return true;
        return String(s.site_name || '').toLowerCase().includes(search) || String(s.site_id || '').includes(search);
    });
    if (!rows.length) {
        list.innerHTML = '<div class="placeholder">No sites found.</div>';
        renderSiteMarkers(rows);
        return;
    }
    list.innerHTML = rows.map((s) => `
        <button type="button" class="site-item" onclick="focusSite('${escapeHtml(String(s.site_id || ''))}')">
            <span class="site-item-name">${escapeHtml(s.site_name || s.site_id || '')}</span>
            <span class="site-item-meta">${escapeHtml(s.vendor || '-')}${s.area ? ' · ' + escapeHtml(s.area) : ''}</span>
        </button>
    `).join('');
    renderSiteMarkers(rows);
}

function renderSiteMarkers(sites) {
    if (!siteLayer) return;
    siteLayer.clearLayers();
    siteMarkers = [];
    sites.forEach((s) => {
        const lat = Number(s.latitude);
        const lng = Number(s.longitude);
        if (!Number.isFinite(lat) || !Number.isFinite(lng)) return;
        const marker = L.circleMarker([lat, lng], {
            radius: 5,
            color: s.vendor === 'Nokia' ? '#00a3e0' : '#e55300',
            fillColor: s.vendor === 'Nokia' ? '#00a3e0' : '#e55300',
            fillOpacity: 0.85,
            weight: 1.5,
        }).addTo(siteLayer);
        marker.on('click', () => focusSite(String(s.site_id || '')));
        marker.bindTooltip(escapeHtml(s.site_name || String(s.site_id || '')));
        siteMarkers.push(marker);
    });
}

async function focusSite(siteId) {
    const site = allSites.find((s) => String(s.site_id || '') === String(siteId));
    if (site) {
        const lat = Number(site.latitude);
        const lng = Number(site.longitude);
        if (Number.isFinite(lat) && Number.isFinite(lng)) dtMap.setView([lat, lng], Math.max(dtMap.getZoom(), 14));
    }
    const details = document.getElementById('siteDetails');
    if (!site) {
        details.innerHTML = '<p class="placeholder">Site not found.</p>';
        return;
    }
    details.innerHTML = `
        <h4>${escapeHtml(site.site_name || siteId)}</h4>
        <div><strong>Site ID:</strong> ${escapeHtml(String(site.site_id || siteId))}</div>
        <div><strong>Vendor:</strong> ${escapeHtml(site.vendor || '-')}</div>
        <div><strong>Area:</strong> ${escapeHtml(site.area || '-')}</div>
        <div><strong>Cluster:</strong> ${escapeHtml(String(site.cluster ?? '-'))}</div>
    `;
}

function escapeHtml(text) {
    return String(text ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}
