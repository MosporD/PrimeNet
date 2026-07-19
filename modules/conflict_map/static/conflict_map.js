let conflictMap = null;
let conflictLayerGroup = null;
const conflictElevationCache = new Map();
let conflictPciFilter = '';

function conflictElevationKey(lat, lng) {
    return `${Number(lat).toFixed(5)},${Number(lng).toFixed(5)}`;
}

function conflictFormatElevation(value) {
    const n = Number(value);
    return Number.isFinite(n) ? `${Math.round(n)} m` : '-';
}

async function conflictFetchElevation(lat, lng) {
    const la = Number(lat);
    const lo = Number(lng);
    if (!Number.isFinite(la) || !Number.isFinite(lo)) return null;
    const key = conflictElevationKey(la, lo);
    if (conflictElevationCache.has(key)) return conflictElevationCache.get(key);
    try {
        const res = await fetch(`/api/elevation?lat=${encodeURIComponent(la)}&lng=${encodeURIComponent(lo)}`, {
            credentials: 'same-origin',
            cache: 'no-store',
        });
        const data = await res.json().catch(() => ({}));
        const val = res.ok && data.success ? data.elevation_m : null;
        conflictElevationCache.set(key, val);
        return val;
    } catch (_) {
        conflictElevationCache.set(key, null);
        return null;
    }
}

function conflictFillElevation(id, lat, lng) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = 'loading...';
    conflictFetchElevation(lat, lng).then((value) => {
        const target = document.getElementById(id);
        if (target) target.textContent = conflictFormatElevation(value);
    });
}

function conflictFillElevationPair(aId, bId, deltaId, aLat, aLng, bLat, bLng) {
    Promise.all([conflictFetchElevation(aLat, aLng), conflictFetchElevation(bLat, bLng)]).then(([a, b]) => {
        const aEl = document.getElementById(aId);
        const bEl = document.getElementById(bId);
        const dEl = document.getElementById(deltaId);
        if (aEl) aEl.textContent = conflictFormatElevation(a);
        if (bEl) bEl.textContent = conflictFormatElevation(b);
        if (dEl) {
            const an = Number(a);
            const bn = Number(b);
            dEl.textContent = Number.isFinite(an) && Number.isFinite(bn) ? `${Math.round(an - bn)} m` : '-';
        }
    });
}

window.addEventListener('DOMContentLoaded', () => {
    initConflictMap();
    bindFilters();
    syncPanelAnchors();
    window.addEventListener('resize', () => {
        syncPanelAnchors();
        if (conflictMap) conflictMap.invalidateSize();
    });
    applyDeepLinkFromUrl();
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
    const fixMapSize = () => {
        if (conflictMap) conflictMap.invalidateSize();
    };
    setTimeout(fixMapSize, 50);
    setTimeout(fixMapSize, 250);
    setTimeout(fixMapSize, 600);
}

function bindFilters() {
    const techEl = document.getElementById('conf-tech');
    const strictEl = document.getElementById('conf-strictness');
    const areaEl = document.getElementById('conf-area');
    const queryBtn = document.getElementById('conf-refresh');
    const refreshBtn = document.getElementById('conf-refresh-cache');
    const exportBtn = document.getElementById('conf-export-kml');
    const panelToggleBtn = document.getElementById('conf-panel-toggle');
    if (techEl) techEl.addEventListener('change', () => loadOptionsForTechnology());
    if (strictEl) strictEl.addEventListener('change', () => refreshBandOptionsForArea());
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

function attrEscape(s) {
    return String(s || '').replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
}

function refillStrictnessSelect(profiles, defaultId) {
    const sel = document.getElementById('conf-strictness');
    if (!sel || !profiles || !profiles.length) return;
    const current = sel.value;
    sel.innerHTML =
        '<option value="" disabled>Select strictness</option>' +
        profiles
            .map(
                (p) =>
                    `<option value="${attrEscape(p.id)}" title="${attrEscape(p.hint)} (${attrEscape(
                        p.dist_max_km
                    )} km max, ±${attrEscape(p.az_near_deg)}°)">${attrEscape(p.label)}</option>`
            )
            .join('');
    const pick = current && [...sel.options].some((o) => o.value === current) ? current : defaultId || '';
    if (pick && [...sel.options].some((o) => o.value === pick)) sel.value = pick;
}

async function refreshBandOptionsForArea() {
    const statsEl = document.getElementById('conf-map-stats');
    const technology = document.getElementById('conf-tech')?.value || '';
    const strictness = document.getElementById('conf-strictness')?.value || 'standard';
    const risk = document.getElementById('conf-risk')?.value || 'all';
    const areas = selectedAreas();
    if (!technology) return;
    try {
        const qs = new URLSearchParams();
        qs.set('technology', technology);
        if (strictness) qs.set('strictness', strictness);
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
    const panel = document.getElementById('conf-filter-panel');
    const stats = document.getElementById('conf-map-stats');
    if (!panel || !stats) return;

    // Use layout offsets (same CSS-pixel space as `top`) — not getBoundingClientRect,
    // which mismatches under html { zoom } and was breaking Leaflet tile alignment.
    panel.style.top = '12px';
    const statsTop = panel.offsetTop + panel.offsetHeight + 8;
    stats.style.top = `${statsTop}px`;
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
    sel.innerHTML =
        '<option value="" selected disabled>Select band</option>' +
        '<option value="all">All Bands</option>' +
        (values || []).map((v) => `<option value="${String(v)}">${String(v)}</option>`).join('');
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
    const strictness = document.getElementById('conf-strictness')?.value || '';
    const risk = document.getElementById('conf-risk')?.value || '';
    const band = document.getElementById('conf-band')?.value || '';
    const includeElevation = !!document.getElementById('conf-elev')?.checked;
    const areas = selectedAreas();
    if (requireComplete && (!technology || !strictness || !risk || !band || !areas.length)) return null;
    const qs = new URLSearchParams();
    if (technology) qs.set('technology', technology);
    if (strictness) qs.set('strictness', strictness);
    if (risk) qs.set('risk', risk);
    if (band) qs.set('band', band);
    if (includeElevation) qs.set('include_elevation', '1');
    if (areas.length) {
        areas.forEach((a) => qs.append('area', a));
    } else {
        qs.set('area', 'all');
    }
    if (conflictPciFilter) qs.set('pci', conflictPciFilter);
    return qs;
}

async function loadOptionsForTechnology() {
    const statsEl = document.getElementById('conf-map-stats');
    const technology = document.getElementById('conf-tech')?.value || '';
    if (!technology) return;
    try {
        if (statsEl) statsEl.textContent = 'Loading filter options...';
        const qs = new URLSearchParams({ technology, risk: 'all', area: 'all', band: 'all' });
        const defSt = 'standard';
        qs.set('strictness', defSt);
        const res = await fetch(`/api/conflict-map/data?${qs.toString()}`);
        const data = await res.json();
        if (!data.success) {
            if (statsEl) statsEl.textContent = data.error || 'Failed to load options.';
            return;
        }
        refillStrictnessSelect(data.filters?.strictness_profiles, data.filters?.strictness_default || defSt);
        const stEl = document.getElementById('conf-strictness');
        if (stEl && data.filters?.strictness_default && [...stEl.options].some((o) => o.value === data.filters.strictness_default)) {
            stEl.value = data.filters.strictness_default;
        } else if (stEl && !stEl.value && [...stEl.options].some((o) => o.value === defSt)) {
            stEl.value = defSt;
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
        if (statsEl) statsEl.textContent = 'Select strictness, risk, area, and band, then click Query.';
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
        if (statsEl) statsEl.textContent = 'Please select technology, strictness, risk, area, and band, then click Query.';
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
            const st = data.strictness || '';
            const pool = Number(data.candidate_total ?? data.total ?? 0).toLocaleString();
            const pciNote = data.pci ? ` PCI/PSC ${data.pci} filter.` : '';
            statsEl.textContent = `Showing ${Number(data.filtered_total || 0).toLocaleString()} of ${Number(
                data.total || 0
            ).toLocaleString()} links (${data.technology}, ${st}).${pciNote} Pool: ${pool} pair candidates within max distance.`;
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
    (rows || []).forEach((r, idx) => {
        const aLat = Number(r.a_lat);
        const aLng = Number(r.a_lng);
        const bLat = Number(r.b_lat);
        const bLng = Number(r.b_lng);
        if (!Number.isFinite(aLat) || !Number.isFinite(aLng) || !Number.isFinite(bLat) || !Number.isFinite(bLng)) return;

        const color = riskColor(r.risk);
        const aElevId = `conf-elev-${idx}-a`;
        const bElevId = `conf-elev-${idx}-b`;
        const dElevId = `conf-elev-${idx}-delta`;
        const line = L.polyline([[aLat, aLng], [bLat, bLng]], { color, weight: 3, opacity: 0.85 });
        line.bindPopup(`
            <strong>${r.risk} Risk</strong> (${r.strictness || '—'} strictness)<br>
            Technology: ${r.technology || '-'}<br>
            PCI/PSC: ${r.pci} | CoBand: ${r.coband}<br>
            Distance: ${r.distance_km} km<br>
            Az vs bore A→B / B→A: ${r.a_to_b_diff ?? '-'}° / ${r.b_to_a_diff ?? '-'}°<br>
            Elev A/B/Δ: <span id="${aElevId}">loading...</span> / <span id="${bElevId}">loading...</span> / <span id="${dElevId}">loading...</span><br>
            A: ${r.a_name} (${r.a_site})<br>
            B: ${r.b_name} (${r.b_site})
        `);
        line.on('popupopen', () => conflictFillElevationPair(aElevId, bElevId, dElevId, aLat, aLng, bLat, bLng));
        conflictLayerGroup.addLayer(line);
        conflictLayerGroup.addLayer(L.circleMarker([aLat, aLng], { radius: 5, color, fillColor: color, fillOpacity: 0.9, weight: 1 }));
        conflictLayerGroup.addLayer(L.circleMarker([bLat, bLng], { radius: 5, color, fillColor: color, fillOpacity: 0.9, weight: 1 }));
        const wa = buildWedge(aLat, aLng, Number(r.a_az));
        const wb = buildWedge(bLat, bLng, Number(r.b_az));
        if (wa) {
            const wedgeAElevId = `conf-elev-${idx}-wa`;
            const wedgeA = L.polygon(wa, { color, weight: 1, fillColor: color, fillOpacity: 0.16 });
            wedgeA.bindPopup(`
                <strong>Cell A Wedge</strong><br>
                Cell: ${r.a_name || '-'}<br>
                Site: ${r.a_site || '-'}<br>
                Technology: ${r.technology || '-'}<br>
                Area: ${r.a_area || '-'}<br>
                Band: ${r.a_band || '-'}<br>
                Elevation: <span id="${wedgeAElevId}">loading...</span><br>
                Azimuth: ${r.a_az ?? '-'}<br>
                PCI/PSC: ${r.pci || '-'}<br>
                Risk: ${r.risk || '-'}
            `);
            wedgeA.on('popupopen', () => conflictFillElevation(wedgeAElevId, aLat, aLng));
            conflictLayerGroup.addLayer(wedgeA);
        }
        if (wb) {
            const wedgeBElevId = `conf-elev-${idx}-wb`;
            const wedgeB = L.polygon(wb, { color, weight: 1, fillColor: color, fillOpacity: 0.16 });
            wedgeB.bindPopup(`
                <strong>Cell B Wedge</strong><br>
                Cell: ${r.b_name || '-'}<br>
                Site: ${r.b_site || '-'}<br>
                Technology: ${r.technology || '-'}<br>
                Area: ${r.b_area || '-'}<br>
                Band: ${r.b_band || '-'}<br>
                Elevation: <span id="${wedgeBElevId}">loading...</span><br>
                Azimuth: ${r.b_az ?? '-'}<br>
                PCI/PSC: ${r.pci || '-'}<br>
                Risk: ${r.risk || '-'}
            `);
            wedgeB.on('popupopen', () => conflictFillElevation(wedgeBElevId, bLat, bLng));
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

async function applyDeepLinkFromUrl() {
    const params = new URLSearchParams(window.location.search);
    const pci = (params.get('pci') || '').trim();
    const tech = (params.get('technology') || '').trim();
    const auto = params.get('auto');
    if (!pci || !tech) return;

    conflictPciFilter = pci;
    const techEl = document.getElementById('conf-tech');
    if (techEl) techEl.value = tech;

    await loadOptionsForTechnology();

    const strictEl = document.getElementById('conf-strictness');
    const strictness = params.get('strictness');
    if (strictEl && strictness && [...strictEl.options].some((o) => o.value === strictness)) {
        strictEl.value = strictness;
    }

    const riskEl = document.getElementById('conf-risk');
    const risk = params.get('risk');
    if (riskEl && risk && [...riskEl.options].some((o) => o.value === risk)) {
        riskEl.value = risk;
    }

    const areaEl = document.getElementById('conf-area');
    const area = params.get('area') || 'all';
    if (areaEl && [...areaEl.options].some((o) => o.value === area)) {
        areaEl.value = area;
    }

    const bandEl = document.getElementById('conf-band');
    const band = params.get('band') || 'all';
    if (bandEl && [...bandEl.options].some((o) => o.value === band)) {
        bandEl.value = band;
    }

    if (auto === '1') {
        await loadConflictMapData();
    }
}
