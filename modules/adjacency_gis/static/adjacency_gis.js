let adjMap = null;
let adjLayerGroup = null;

window.addEventListener('DOMContentLoaded', () => {
    initAdjMap();
    bindAdjFilters();
    syncAdjPanelAnchors();
    loadAdjStatus().then(() => loadAdjMapData(false));
    window.addEventListener('resize', () => {
        syncAdjPanelAnchors();
        if (adjMap) adjMap.invalidateSize();
    });
});

function initAdjMap() {
    const mapEl = document.getElementById('adjacency-map');
    if (!mapEl || typeof L === 'undefined') return;
    adjMap = L.map('adjacency-map', { preferCanvas: true }).setView([31.95, 35.93], 8);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; OpenStreetMap contributors',
        maxZoom: 18,
    }).addTo(adjMap);
    adjLayerGroup = L.layerGroup().addTo(adjMap);
    const fix = () => { if (adjMap) adjMap.invalidateSize(); };
    setTimeout(fix, 50);
    setTimeout(fix, 250);
    setTimeout(fix, 600);
}

function bindAdjFilters() {
    const queryBtn = document.getElementById('adj-query');
    const refreshBtn = document.getElementById('adj-refresh');
    const panelToggleBtn = document.getElementById('adj-panel-toggle');
    if (queryBtn) queryBtn.addEventListener('click', () => loadAdjMapData(true));
    if (refreshBtn) refreshBtn.addEventListener('click', () => refreshAdjSnapshot());
    if (panelToggleBtn) {
        panelToggleBtn.addEventListener('click', () => {
            const panel = document.getElementById('adj-filter-panel');
            if (!panel) return;
            panel.classList.toggle('collapsed');
            panelToggleBtn.textContent = panel.classList.contains('collapsed') ? 'Expand' : 'Collapse';
            syncAdjPanelAnchors();
        });
    }
}

function syncAdjPanelAnchors() {
    const panel = document.getElementById('adj-filter-panel');
    const stats = document.getElementById('adj-map-stats');
    if (!panel || !stats) return;
    panel.style.top = '12px';
    const statsTop = panel.offsetTop + panel.offsetHeight + 8;
    stats.style.top = `${statsTop}px`;
    if (adjMap) setTimeout(() => adjMap.invalidateSize(), 30);
}

function attrEscape(s) {
    return String(s || '').replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
}

function refillSelect(sel, values, allLabel, allValue = 'all') {
    if (!sel) return;
    const current = sel.value;
    sel.innerHTML =
        `<option value="${allValue}">${attrEscape(allLabel)}</option>` +
        (values || []).map((v) => `<option value="${attrEscape(v)}">${attrEscape(v)}</option>`).join('');
    if ([...sel.options].some((o) => o.value === current)) sel.value = current;
}

function severityColor(severity) {
    const s = String(severity || '').toLowerCase();
    if (s === 'co_channel') return '#8e44ad';
    if (s === 'overshoot' || s === 'ncl_overflow') return '#c0392b';
    if (s === 'unidirectional') return '#f39c12';
    return '#2980b9';
}

function toRad(d) { return (d * Math.PI) / 180; }
function toDeg(r) { return (r * 180) / Math.PI; }

function destinationPoint(lat, lng, bearingDeg, distanceKm) {
    const R = 6371.0;
    const br = toRad(bearingDeg);
    const p1 = toRad(lat);
    const l1 = toRad(lng);
    const d = distanceKm / R;
    const p2 = Math.asin(Math.sin(p1) * Math.cos(d) + Math.cos(p1) * Math.sin(d) * Math.cos(br));
    const l2 = l1 + Math.atan2(Math.sin(br) * Math.sin(d) * Math.cos(p1), Math.cos(d) - Math.sin(p1) * Math.sin(p2));
    return [toDeg(p2), toDeg(l2)];
}

function buildWedge(lat, lng, azimuth, widthDeg = 40, distanceKm = 0.8, segments = 8) {
    const az = Number(azimuth);
    if (!Number.isFinite(lat) || !Number.isFinite(lng) || !Number.isFinite(az)) return null;
    const pts = [[lat, lng]];
    const start = az - widthDeg / 2;
    const step = widthDeg / Math.max(1, segments);
    for (let i = 0; i <= segments; i++) {
        pts.push(destinationPoint(lat, lng, start + i * step, distanceKm));
    }
    pts.push([lat, lng]);
    return pts;
}

async function loadAdjStatus() {
    const statsEl = document.getElementById('adj-map-stats');
    try {
        const res = await fetch('/api/adjacency-gis/status', { credentials: 'same-origin' });
        const data = await res.json();
        if (!data.success) return;
        const overEl = document.getElementById('adj-overshoot');
        if (overEl && data.defaults?.overshoot_km != null) {
            overEl.value = data.defaults.overshoot_km;
        }
        const snap = data.snapshot || {};
        if (statsEl && snap.built_at) {
            statsEl.textContent =
                `Snapshot ${snap.built_at} · sectors ${snap.sector_count || 0} · edges ${snap.edge_count || 0}`;
        }
    } catch (_) {
        // keep default UI
    }
}

function buildAdjQueryParams() {
    const qs = new URLSearchParams();
    qs.set('vendor', document.getElementById('adj-vendor')?.value || 'all');
    qs.set('bsc', document.getElementById('adj-bsc')?.value || 'all');
    qs.set('area', document.getElementById('adj-area')?.value || 'all');
    qs.set('issue', document.getElementById('adj-issue')?.value || 'all');
    const over = document.getElementById('adj-overshoot')?.value;
    if (over) qs.set('overshoot_km', over);
    return qs;
}

async function loadAdjMapData(requireQuery) {
    const statsEl = document.getElementById('adj-map-stats');
    const qs = buildAdjQueryParams();
    if (statsEl) statsEl.textContent = 'Loading adjacency map…';
    try {
        const res = await fetch(`/api/adjacency-gis/data?${qs.toString()}`, {
            credentials: 'same-origin',
            cache: 'no-store',
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data.success) {
            if (statsEl) {
                statsEl.textContent = data.error || 'Failed to load adjacency data.';
            }
            if (adjLayerGroup) adjLayerGroup.clearLayers();
            syncAdjPanelAnchors();
            return;
        }
        refillSelect(document.getElementById('adj-bsc'), data.filters?.bscs || [], 'All BSCs');
        refillSelect(document.getElementById('adj-area'), data.filters?.areas || [], 'All Areas');
        drawAdjLayers(data.sectors || [], data.edges || []);
        const c = data.counts || {};
        if (statsEl) {
            statsEl.textContent =
                `Sectors ${c.sectors || 0} · Links ${c.edges || 0}` +
                ` · Uni ${c.unidirectional || 0}` +
                ` · Overshoot ${c.overshoot || 0}` +
                ` · NCL>32 ${c.ncl_overflow || 0}` +
                ` · Co-CH ${c.co_channel || 0}` +
                (data.built_at ? ` · Built ${data.built_at}` : '');
        }
        syncAdjPanelAnchors();
    } catch (err) {
        if (statsEl) statsEl.textContent = 'Could not load adjacency data.';
        syncAdjPanelAnchors();
    }
}

function drawAdjLayers(sectors, edges) {
    if (!adjLayerGroup) return;
    adjLayerGroup.clearLayers();
    const bounds = [];

    (sectors || []).forEach((s) => {
        const lat = Number(s.lat);
        const lng = Number(s.lng);
        if (!Number.isFinite(lat) || !Number.isFinite(lng)) return;
        bounds.push([lat, lng]);
        const wedge = buildWedge(lat, lng, Number(s.azimuth));
        if (wedge) {
            L.polygon(wedge, {
                color: '#1e3a5f',
                weight: 1,
                fillColor: '#3498db',
                fillOpacity: 0.28,
            })
                .bindPopup(
                    `<strong>${attrEscape(s.cell_name)}</strong><br>` +
                    `BCCH ${attrEscape(s.bcch)} · Az ${attrEscape(s.azimuth)}°<br>` +
                    `BSC ${attrEscape(s.bsc_id)} · ${attrEscape(s.area)}`
                )
                .addTo(adjLayerGroup);
        } else {
            L.circleMarker([lat, lng], { radius: 4, color: '#1e3a5f', fillOpacity: 0.7 })
                .bindPopup(attrEscape(s.cell_name))
                .addTo(adjLayerGroup);
        }
    });

    (edges || []).forEach((e) => {
        const aLat = Number(e.source_lat);
        const aLng = Number(e.source_lng);
        const bLat = Number(e.target_lat);
        const bLng = Number(e.target_lng);
        if (![aLat, aLng, bLat, bLng].every(Number.isFinite)) return;
        bounds.push([aLat, aLng], [bLat, bLng]);
        const color = severityColor(e.severity);
        L.polyline([[aLat, aLng], [bLat, bLng]], {
            color,
            weight: e.unidirectional ? 2 : 2.5,
            opacity: 0.85,
            dashArray: e.unidirectional ? '6 4' : null,
        })
            .bindPopup(
                `<strong>${attrEscape(e.source_name)} → ${attrEscape(e.target_name)}</strong><br>` +
                `${e.bidirectional ? 'Bidirectional' : 'Unidirectional'} · ${attrEscape(e.distance_km)} km<br>` +
                `BCCH ${attrEscape(e.source_bcch)} / ${attrEscape(e.target_bcch)}` +
                (e.issues?.length ? `<br>Issues: ${attrEscape((e.issues || []).join(', '))}` : '') +
                (e.ncl_count != null ? `<br>NCL count: ${attrEscape(e.ncl_count)}` : '')
            )
            .addTo(adjLayerGroup);
    });

    if (bounds.length && adjMap) {
        try {
            adjMap.fitBounds(bounds, { padding: [40, 40], maxZoom: 14 });
        } catch (_) {
            // ignore empty bounds
        }
    }
}

async function refreshAdjSnapshot() {
    const statsEl = document.getElementById('adj-map-stats');
    const vendor = document.getElementById('adj-vendor')?.value || 'all';
    if (!confirm(`Rebuild ${vendor} ADCE/G2GNCELL snapshot from CM? This may take several minutes.`)) {
        return;
    }
    if (statsEl) statsEl.textContent = 'Starting snapshot rebuild…';
    try {
        const res = await fetch('/api/adjacency-gis/refresh', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ vendor }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data.success) {
            if (statsEl) statsEl.textContent = data.error || 'Refresh denied or failed.';
            return;
        }
        if (statsEl) {
            statsEl.textContent = `Ingest started (${data.vendor || vendor}). Re-query in a few minutes.`;
        }
    } catch (_) {
        if (statsEl) statsEl.textContent = 'Could not start refresh.';
    }
}
