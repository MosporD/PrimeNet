let conflictMap = null;
let conflictLayerGroup = null;

window.addEventListener('DOMContentLoaded', () => {
    initConflictMap();
    bindFilters();
    syncPanelAnchors();
    window.addEventListener('resize', syncPanelAnchors);
});

function initConflictMap() {
    const mapEl = document.getElementById('conflict-map');
    if (!mapEl || typeof L === 'undefined') return;
    conflictMap = L.map('conflict-map', { preferCanvas: true }).setView([31.95, 35.93], 8);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; OpenStreetMap contributors',
        maxZoom: 18,
    }).addTo(conflictMap);
    conflictLayerGroup = L.layerGroup().addTo(conflictMap);
    setTimeout(() => conflictMap.invalidateSize(), 50);
}

function bindFilters() {
    const techEl = document.getElementById('conf-tech');
    const areaEl = document.getElementById('conf-area');
    const queryBtn = document.getElementById('conf-refresh');
    const refreshBtn = document.getElementById('conf-refresh-cache');
    const exportBtn = document.getElementById('conf-export-kml');
    const panelToggleBtn = document.getElementById('conf-panel-toggle');
    if (techEl) techEl.addEventListener('change', () => loadOptionsForTechnology());
    if (areaEl) areaEl.addEventListener('change', () => refreshBandOptionsForArea());
    if (queryBtn) queryBtn.addEventListener('click', () => loadConflictMapData());
    if (refreshBtn) refreshBtn.addEventListener('click', () => refreshConflictCache());
    if (exportBtn) exportBtn.addEventListener('click', () => exportKml());
    if (panelToggleBtn) {
        panelToggleBtn.addEventListener('click', () => {
            const panel = document.getElementById('conf-filter-panel');
            if (!panel) return;
            panel.classList.toggle('collapsed');
            panelToggleBtn.textContent = panel.classList.contains('collapsed') ? 'Expand' : 'Collapse';
            syncPanelAnchors();
        });
    }
}

async function refreshBandOptionsForArea() {
    const statsEl = document.getElementById('conf-map-stats');
    const technology = document.getElementById('conf-tech')?.value || '';
    const risk = document.getElementById('conf-risk')?.value || 'all';
    const areas = selectedAreas();
    if (!technology) return;
    try {
        const qs = new URLSearchParams();
        qs.set('technology', technology);
        qs.set('risk', risk || 'all');
        if (areas.length) {
            areas.forEach((a) => qs.append('area', a));
        } else {
            qs.set('area', 'all');
        }
        qs.set('band', 'all');
        const res = await fetch(`/api/conflict-map/data?${qs.toString()}`);
        const data = await res.json();
        if (!data.success) return;
        refillBandSelect(data.filters?.bands || []);
        if (statsEl) statsEl.textContent = 'Band options updated. Select band and click Query.';
    } catch (_) {
        // keep current UI state on transient failures
    }
}

function syncPanelAnchors() {
    const header = document.querySelector('header');
    const panel = document.getElementById('conf-filter-panel');
    const stats = document.getElementById('conf-map-stats');
    const mapEl = document.getElementById('conflict-map');
    if (!header || !panel || !stats || !mapEl) return;

    const hb = header.getBoundingClientRect();
    const panelTop = Math.max(8, hb.bottom + 8);
    panel.style.top = `${panelTop}px`;

    const panelRect = panel.getBoundingClientRect();
    const statsTop = panelRect.bottom + 8;
    stats.style.top = `${statsTop}px`;

    // Map starts right below header; filter/stats float on top of map.
    const mapTop = Math.max(hb.bottom + 8, 80);
    mapEl.style.top = `${mapTop}px`;
    if (conflictMap) setTimeout(() => conflictMap.invalidateSize(), 30);
}

function riskColor(risk) {
    const r = String(risk || '').toLowerCase();
    if (r === 'high') return '#c0392b';
    if (r === 'medium') return '#f39c12';
    return '#2980b9';
}

function refillBandSelect(values) {
    const sel = document.getElementById('conf-band');
    if (!sel) return;
    const current = sel.value;
    sel.innerHTML = '<option value="" selected disabled>Select band</option>' + (values || [])
        .map((v) => `<option value="${String(v)}">${String(v)}</option>`)
        .join('');
    if ([...sel.options].some((o) => o.value === current)) sel.value = current;
}

function refillAreaSelect(values) {
    const sel = document.getElementById('conf-area');
    if (!sel) return;
    const current = sel.value;
    sel.innerHTML = '<option value="" selected disabled>Select area</option><option value="all">All Areas</option>' + (values || [])
        .map((v) => `<option value="${String(v)}">${String(v)}</option>`)
        .join('');
    if ([...sel.options].some((o) => o.value === current)) sel.value = current;
}

function selectedAreas() {
    const sel = document.getElementById('conf-area');
    if (!sel) return [];
    return sel.value ? [sel.value] : [];
}

function toRad(d) {
    return (d * Math.PI) / 180;
}

function toDeg(r) {
    return (r * 180) / Math.PI;
}

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
        const b = start + i * step;
        pts.push(destinationPoint(lat, lng, b, distanceKm));
    }
    pts.push([lat, lng]);
    return pts;
}

function buildQueryParams(requireComplete = false) {
    const technology = document.getElementById('conf-tech')?.value || '';
    const risk = document.getElementById('conf-risk')?.value || '';
    const band = document.getElementById('conf-band')?.value || '';
    const includeElevation = !!document.getElementById('conf-elev')?.checked;
    const areas = selectedAreas();
    if (requireComplete && (!technology || !risk || !band || !areas.length)) return null;
    const qs = new URLSearchParams();
    if (technology) qs.set('technology', technology);
    if (risk) qs.set('risk', risk);
    if (band) qs.set('band', band);
    if (includeElevation) qs.set('include_elevation', '1');
    if (areas.length) {
        areas.forEach((a) => qs.append('area', a));
    } else {
        qs.set('area', 'all');
    }
    return qs;
}

async function loadOptionsForTechnology() {
    const statsEl = document.getElementById('conf-map-stats');
    const technology = document.getElementById('conf-tech')?.value || '';
    if (!technology) return;
    try {
        if (statsEl) statsEl.textContent = 'Loading filter options...';
        const qs = new URLSearchParams({ technology, risk: 'all', area: 'all', band: 'all' });
        const res = await fetch(`/api/conflict-map/data?${qs.toString()}`);
        const data = await res.json();
        if (!data.success) {
            if (statsEl) statsEl.textContent = data.error || 'Failed to load options.';
            return;
        }
        refillAreaSelect(data.filters?.areas || []);
        const bands = data.filters?.bands || [];
        refillBandSelect(bands);
        const bandEl = document.getElementById('conf-band');
        if (bandEl) {
            if (technology === '5G') {
                // 5G scope has a single band in this deployment; auto-select it for convenience.
                if (bands.length === 1) {
                    bandEl.value = String(bands[0]);
                }
            }
            bandEl.disabled = (technology === '5G' && bands.length <= 1);
        }
        const riskEl = document.getElementById('conf-risk');
        if (riskEl && !riskEl.value) riskEl.selectedIndex = 0;
        if (statsEl) statsEl.textContent = 'Select risk, area, and band, then click Query.';
        if (conflictLayerGroup) conflictLayerGroup.clearLayers();
        syncPanelAnchors();
    } catch (_) {
        if (statsEl) statsEl.textContent = 'Could not load filter options.';
        syncPanelAnchors();
    }
}

async function loadConflictMapData() {
    const statsEl = document.getElementById('conf-map-stats');
    const qs = buildQueryParams(true);
    if (!qs) {
        if (statsEl) statsEl.textContent = 'Please select technology, risk, area, and band, then click Query.';
        return;
    }

    try {
        if (statsEl) statsEl.textContent = 'Loading map data...';
        const res = await fetch(`/api/conflict-map/data?${qs.toString()}`);
        const data = await res.json();
        if (!data.success) {
            if (statsEl) statsEl.textContent = data.error || 'Failed to load map data.';
            return;
        }
        refillAreaSelect(data.filters?.areas || []);
        refillBandSelect(data.filters?.bands || []);
        renderRows(data.rows || []);
        if (statsEl) {
            statsEl.textContent = `Showing ${Number(data.filtered_total || 0).toLocaleString()} of ${Number(data.total || 0).toLocaleString()} links (${data.technology}).`;
        }
        syncPanelAnchors();
    } catch (_) {
        if (statsEl) statsEl.textContent = 'Could not load conflict map data.';
        syncPanelAnchors();
    }
}

function renderRows(rows) {
    if (!conflictMap || !conflictLayerGroup) return;
    conflictLayerGroup.clearLayers();
    const bounds = [];
    (rows || []).forEach((r) => {
        const aLat = Number(r.a_lat);
        const aLng = Number(r.a_lng);
        const bLat = Number(r.b_lat);
        const bLng = Number(r.b_lng);
        if (!Number.isFinite(aLat) || !Number.isFinite(aLng) || !Number.isFinite(bLat) || !Number.isFinite(bLng)) return;

        const color = riskColor(r.risk);
        const line = L.polyline([[aLat, aLng], [bLat, bLng]], { color, weight: 3, opacity: 0.85 });
        line.bindPopup(`
            <strong>${r.risk} Risk</strong><br>
            Technology: ${r.technology || '-'}<br>
            PCI/PSC: ${r.pci} | CoBand: ${r.coband}<br>
            Distance: ${r.distance_km} km<br>
            Elev A/B/Δ: ${r.a_elevation_m ?? '-'} / ${r.b_elevation_m ?? '-'} / ${r.elevation_delta_m ?? '-'} m<br>
            A: ${r.a_name} (${r.a_site})<br>
            B: ${r.b_name} (${r.b_site})
        `);
        conflictLayerGroup.addLayer(line);
        conflictLayerGroup.addLayer(L.circleMarker([aLat, aLng], { radius: 5, color, fillColor: color, fillOpacity: 0.9, weight: 1 }));
        conflictLayerGroup.addLayer(L.circleMarker([bLat, bLng], { radius: 5, color, fillColor: color, fillOpacity: 0.9, weight: 1 }));
        const wa = buildWedge(aLat, aLng, Number(r.a_az));
        const wb = buildWedge(bLat, bLng, Number(r.b_az));
        if (wa) {
            const wedgeA = L.polygon(wa, { color, weight: 1, fillColor: color, fillOpacity: 0.16 });
            wedgeA.bindPopup(`
                <strong>Cell A Wedge</strong><br>
                Cell: ${r.a_name || '-'}<br>
                Site: ${r.a_site || '-'}<br>
                Technology: ${r.technology || '-'}<br>
                Area: ${r.a_area || '-'}<br>
                Band: ${r.a_band || '-'}<br>
                Elevation: ${r.a_elevation_m ?? '-'} m<br>
                Azimuth: ${r.a_az ?? '-'}<br>
                PCI/PSC: ${r.pci || '-'}<br>
                Risk: ${r.risk || '-'}
            `);
            conflictLayerGroup.addLayer(wedgeA);
        }
        if (wb) {
            const wedgeB = L.polygon(wb, { color, weight: 1, fillColor: color, fillOpacity: 0.16 });
            wedgeB.bindPopup(`
                <strong>Cell B Wedge</strong><br>
                Cell: ${r.b_name || '-'}<br>
                Site: ${r.b_site || '-'}<br>
                Technology: ${r.technology || '-'}<br>
                Area: ${r.b_area || '-'}<br>
                Band: ${r.b_band || '-'}<br>
                Elevation: ${r.b_elevation_m ?? '-'} m<br>
                Azimuth: ${r.b_az ?? '-'}<br>
                PCI/PSC: ${r.pci || '-'}<br>
                Risk: ${r.risk || '-'}
            `);
            conflictLayerGroup.addLayer(wedgeB);
        }
        bounds.push([aLat, aLng], [bLat, bLng]);
    });
    if (bounds.length) conflictMap.fitBounds(bounds, { padding: [24, 24], maxZoom: 13 });
}

async function refreshConflictCache() {
    const statsEl = document.getElementById('conf-map-stats');
    const tech = document.getElementById('conf-tech')?.value || 'all';
    try {
        if (statsEl) statsEl.textContent = 'Refreshing conflict data cache...';
        const res = await fetch('/api/conflict-map/refresh', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ technology: tech || 'all' }),
        });
        const data = await res.json();
        if (!data.success) {
            if (statsEl) statsEl.textContent = data.error || 'Cache refresh failed.';
            return;
        }
        if (statsEl) statsEl.textContent = 'Conflict cache refreshed. You can query now.';
        if (tech) {
            await loadOptionsForTechnology();
        }
        syncPanelAnchors();
    } catch (_) {
        if (statsEl) statsEl.textContent = 'Could not refresh cache.';
        syncPanelAnchors();
    }
}

function exportKml() {
    const statsEl = document.getElementById('conf-map-stats');
    const qs = buildQueryParams(true);
    if (!qs) {
        if (statsEl) statsEl.textContent = 'Select all filters before exporting KML.';
        return;
    }
    window.location.href = `/api/conflict-map/export-kml?${qs.toString()}`;
}
