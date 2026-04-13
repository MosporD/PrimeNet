/**
 * Network Map – Leaflet visualization
 * Sites → sector wedges drawn per cell (azimuth-aligned)
 * Tech filter: All / 2G / 3G / 4G / 4G-FDD / 4G-TDD / 5G
 */

// ─── Constants ───────────────────────────────────────────────────────────────

const TECH_COLORS = {
    '2G':     '#7f8c8d',
    '3G':     '#27ae60',
    '4G-FDD': '#1a5276',
    '4G-TDD': '#148f77',
    '5G':     '#9b59b6',
};

// Note: We intentionally do NOT expose generic "4G" in the UI.
// Any legacy 4G rows are normalized to 4G-FDD by the backend map APIs.
const TECH_ORDER = ['2G', '3G', '4G-FDD', '4G-TDD', '5G'];

const DEFAULT_CENTER = [31.9539, 35.9106];   // Amman, Jordan
const DEFAULT_ZOOM   = 10;
const SECTOR_RADIUS_M = 600;                 // wedge radius in metres
const SECTOR_BEAMWIDTH = 65;                 // 3 dB beamwidth in degrees

// Cluster number → Area name  (cluster = Math.floor(site_id / 100))
const CLUSTER_AREA = {
     3: 'East Amman',  13: 'East Amman',  17: 'East Amman',  21: 'East Amman',
    23: 'East Amman',  27: 'East Amman',  48: 'East Amman',  49: 'East Amman',
    50: 'East Amman',  51: 'East Amman',  52: 'East Amman',  54: 'East Amman',
    10: 'East Jordan', 11: 'East Jordan', 19: 'East Jordan', 28: 'East Jordan',
    31: 'East Jordan', 42: 'East Jordan', 43: 'East Jordan', 47: 'East Jordan',
     1: 'South Amman',  6: 'South Amman',  9: 'South Amman', 18: 'South Amman',
    30: 'South Amman', 36: 'South Amman', 38: 'South Amman', 39: 'South Amman',
    53: 'South Amman', 57: 'South Amman', 59: 'South Amman',
     7: 'South Jordan',  8: 'South Jordan', 12: 'South Jordan', 15: 'South Jordan',
    33: 'South Jordan', 41: 'South Jordan', 58: 'South Jordan',
     2: 'West Amman',   5: 'West Amman',  16: 'West Amman',  20: 'West Amman',
    22: 'West Amman',  25: 'West Amman',  26: 'West Amman',  32: 'West Amman',
    35: 'West Amman',  40: 'West Amman',  55: 'West Amman',  56: 'West Amman',
     4: 'North Jordan', 14: 'North Jordan', 24: 'North Jordan', 29: 'North Jordan',
    34: 'North Jordan', 37: 'North Jordan', 44: 'North Jordan', 45: 'North Jordan',
    46: 'North Jordan', 65: 'North Jordan',
};

// ─── State ───────────────────────────────────────────────────────────────────

let map              = null;
let sitesData        = [];
let siteMarkers      = [];
let sectorLayers     = [];
let activeTech       = 'all';
let highlightMarkers = [];
let highlightLayers  = [];
let codeSearchTimer  = null;
let activeTechSpecific = 'all';

// Map wedge group id -> group payload (cells + site context)
let wedgeGroups = {};

// Coordinate search marker
let coordMarker = null;

// ─── Measure tool state ───────────────────────────────────────────────────────
let measureActive    = false;
let measurePoints    = [];
let measurePtMarkers = [];
let measurePolyline  = null;
let measureDistLabel = null;

const LEFT_PANEL_COLLAPSE_KEY = 'networkMapLeftPanelCollapsed';

function applySavedLeftPanelState() {
    try {
        if (localStorage.getItem(LEFT_PANEL_COLLAPSE_KEY) === '1') {
            const shell = document.getElementById('left-panel-shell');
            const tab = document.getElementById('left-panel-tab');
            if (shell) shell.classList.add('collapsed');
            if (tab) {
                tab.setAttribute('aria-expanded', 'false');
                tab.title = 'Show filters panel';
            }
        }
    } catch (_) { /* storage blocked */ }
}

function toggleMapLeftPanel() {
    const shell = document.getElementById('left-panel-shell');
    const tab = document.getElementById('left-panel-tab');
    if (!shell || !tab) return;
    const collapsed = shell.classList.toggle('collapsed');
    tab.setAttribute('aria-expanded', String(!collapsed));
    tab.title = collapsed ? 'Show filters panel' : 'Hide filters panel';
    try {
        localStorage.setItem(LEFT_PANEL_COLLAPSE_KEY, collapsed ? '1' : '0');
    } catch (_) { /* ignore */ }
    window.setTimeout(() => {
        if (map) map.invalidateSize();
    }, 320);
}

// ─── Initialization ──────────────────────────────────────────────────────────

function initializeMap() {
    // Full-screen KPI modal can survive bfcache restore and block all clicks
    closeKPIModal();

    applySavedLeftPanelState();

    if (map) { map.invalidateSize(); return; }

    map = L.map('network-map').setView(DEFAULT_CENTER, DEFAULT_ZOOM);

    // Base map styles
    const street = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; OpenStreetMap contributors',
        maxZoom: 19
    });
    const hot = L.tileLayer('https://{s}.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png', {
        attribution: '&copy; OpenStreetMap contributors, Tiles style by Humanitarian OpenStreetMap Team',
        maxZoom: 19
    });
    const topo = L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png', {
        attribution: 'Map data: &copy; OpenStreetMap contributors, SRTM | Map style: &copy; OpenTopoMap',
        maxZoom: 17
    });
    const satellite = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
        attribution: 'Tiles &copy; Esri',
        maxZoom: 19
    });
    const terrain = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Terrain_Base/MapServer/tile/{z}/{y}/{x}', {
        attribution: 'Tiles &copy; Esri',
        maxZoom: 13
    });

    // Default layer
    street.addTo(map);

    // Layer control (top-right)
    L.control.layers(
        {
            'Street': street,
            'Street (HOT)': hot,
            'Topographic': topo,
            'Satellite': satellite,
            'Terrain': terrain
        },
        {},
        { collapsed: false }
    ).addTo(map);

    window.setTimeout(() => { if (map) map.invalidateSize(); }, 200);

    // Load stats + tech buttons, but do NOT load sites until the user applies a filter.
    loadNetworkStats().then(() => {
        _showEmptyState();
        _wireInitialFilterListeners();
    });
}

// ─── Stats & tech filter buttons ─────────────────────────────────────────────

async function loadNetworkStats() {
    try {
        const res  = await fetch('/api/map/stats');
        const data = await res.json();
        if (!data.success) return;

        const s = data.stats;
        document.getElementById('sites-count').textContent = s.total_sites;

        buildTechButtons(s.tech_counts || {});
    } catch (e) {
        console.error('Stats error:', e);
    }
}

function buildTechButtons(counts) {
    const container = document.getElementById('tech-filter');
    if (!container) return;

    const total = Object.values(counts).reduce((a, b) => a + b, 0);

    let html = `<button class="tech-btn${activeTech === 'all' ? ' active' : ''}" data-tech="all"
                        onclick="setTechFilter('all')">
                  All <span class="tech-count">${total}</span>
                </button>`;

    TECH_ORDER.forEach(tech => {
        if (!counts[tech]) return;
        const color    = TECH_COLORS[tech] || '#3498db';
        const isActive = activeTech === tech ? ' active' : '';
        html += `<button class="tech-btn${isActive}" data-tech="${tech}"
                         style="--tc:${color}"
                         onclick="setTechFilter('${tech}')">
                   ${tech} <span class="tech-count">${counts[tech]}</span>
                 </button>`;
    });

    container.innerHTML = html;
}

function setTechFilter(tech) {
    activeTech = tech;
    activeTechSpecific = 'all';
    document.querySelectorAll('.tech-btn').forEach(btn =>
        btn.classList.toggle('active', btn.dataset.tech === tech)
    );
    clearSectorLayers();
    clearHighlights();
    document.getElementById('site-info-panel').style.display = 'none';

    const codeInput = document.getElementById('cell-code-search');
    if (codeInput) {
        codeInput.placeholder =
            tech === '3G'                             ? 'Scrambling Code...' :
            ['4G', '4G-FDD', '4G-TDD'].includes(tech)? 'PCI...'             :
            tech === '5G'                             ? 'PCI...'             :
            tech === '2G'                             ? 'BCCH...'            :
                                                        'SC / PCI / BCCH...';
    }
    updateTechSpecificFilter();
    _onFilterChanged();
}

// ─── Cell operational state (`activity_status` from map APIs; `status` is alias) ─

/** True when KPI / detail actions are allowed (on-air per vendor rules). */
function cellOperational(c) {
    const raw = c && (c.activity_status != null ? c.activity_status : c.status);
    const s = raw != null ? String(raw).trim().toLowerCase() : '';
    return s === 'active';
}

function escapeHtmlAttr(str) {
    return String(str ?? '')
        .replace(/&/g, '&amp;')
        .replace(/"/g, '&quot;')
        .replace(/</g, '&lt;');
}

function escapeHtml(str) {
    return String(str ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

/** Tooltip when at least one sector wedge has every cell inactive (matches map wedge bins). */
function sitePinTitle(site) {
    const n = Number(site.full_sector_offline_count) || 0;
    if (n <= 0) return site.site_name || '';
    const w = n === 1 ? 'wedge' : 'wedges';
    return `${site.site_name || ''} — ${n} sector ${w} fully deactivated`;
}

/** Leaflet divIcon size/anchor: lat/lng aligns with center of the circular pin. */
function sitePinIconMetrics() {
    const labelH = 14;
    const circle = 36;
    const h = labelH + circle;
    const w = 44;
    return {
        iconSize: [w, h],
        iconAnchor: [w / 2, labelH + circle / 2],
    };
}

function sitePinInnerHtml(site, { highlight = false } = {}) {
    const color = activeTech !== 'all'
        ? (TECH_COLORS[activeTech] || '#3498db')
        : (site.vendor === 'Nokia' ? '#00a3e0' : '#e55300');
    const fullOff = Number(site.full_sector_offline_count) || 0;
    const hasOff = fullOff > 0;
    const hi = highlight ? ' highlight-marker' : '';
    const title = escapeHtmlAttr(sitePinTitle(site));
    const sid = escapeHtml(site.site_id != null ? site.site_id : '');
    return `<div class="site-marker-stack">
              <span class="site-marker-id" aria-hidden="true">${sid}</span>
              <div class="site-marker-inner${hi}${hasOff ? ' site-marker-has-offline' : ''}" style="border-color:${color}" title="${title}">
                <div class="site-icon">📡</div>
                ${hasOff ? '<span class="site-offline-pin-badge" aria-hidden="true"></span>' : ''}
              </div>
            </div>`;
}

// ─── Site enrichment ──────────────────────────────────────────────────────────

function enrichSites(sites) {
    return sites.map(s => {
        const cluster = Math.floor(s.site_id / 100);
        const area    = CLUSTER_AREA[cluster] || 'Unknown';
        return Object.assign({}, s, { cluster, area });
    });
}

// ─── Client-side filtering ────────────────────────────────────────────────────

function applyClientFilters(sites) {
    const term    = document.getElementById('site-search').value.toLowerCase();
    const vendor  = document.getElementById('vendor-filter').value;
    const area    = document.getElementById('area-filter').value;
    const cluster = document.getElementById('cluster-filter').value;

    return sites.filter(s => {
        if (term && !s.site_name.toLowerCase().includes(term) &&
                    !String(s.site_id).includes(term)) return false;
        if (vendor  !== 'all' && s.vendor          !== vendor)  return false;
        if (area    !== 'all' && s.area            !== area)    return false;
        if (cluster !== 'all' && String(s.cluster) !== cluster) return false;
        return true;
    });
}

function runFilters() {
    if (!sitesData.length) {
        _showEmptyState();
        return;
    }
    const filtered = applyClientFilters(sitesData);
    displaySites(filtered);
    document.getElementById('sites-count').textContent = filtered.length;
}

// ─── Site loading & display ───────────────────────────────────────────────────

async function loadNetworkSites() {
    try {
        if (!_hasActiveFilters()) {
            // Keep the map empty until a filter/search is applied.
            sitesData = [];
            displaySites([]);
            _showEmptyState();
            return;
        }

        const params = new URLSearchParams();
        if (activeTech !== 'all') params.set('tech', activeTech);
        if (activeTechSpecific !== 'all') params.set('tech_value', activeTechSpecific);
        const qs = params.toString();
        const url = qs ? `/api/map/sites?${qs}` : '/api/map/sites';
        const res  = await fetch(url);
        const data = await res.json();
        if (!data.success) {
            console.error('Sites API error:', data.error || data);
            return;
        }

        sitesData = enrichSites(data.sites);

        runFilters();

        buildClusterFilter(sitesData);
        buildAreaFilter(sitesData);
    } catch (e) {
        console.error('Sites error:', e);
        showNotification('Failed to load network sites', 'error');
    }
}

function displaySites(sites) {
    siteMarkers.forEach(m => map.removeLayer(m));
    siteMarkers = [];

    if (!sites || !sites.length) return;

    sites.forEach(site => {
        const { iconSize, iconAnchor } = sitePinIconMetrics();
        const icon = L.divIcon({
            className: 'site-marker',
            html: sitePinInnerHtml(site, { highlight: false }),
            iconSize,
            iconAnchor,
        });

        const marker = L.marker([site.latitude, site.longitude], { icon }).addTo(map);
        marker.on('click', () => showSiteDetails(site.site_id));
        siteMarkers.push(marker);
    });
}

// ─── Site detail: draw sector wedges ─────────────────────────────────────────

async function showSiteDetails(siteId) {
    try {
        clearSectorLayers();
        const res  = await fetch(`/api/map/site/${siteId}`);
        const data = await res.json();
        if (!data.success) return;

        const site = data.site;

        // Enrich with cluster/area so the info panel can display them
        const cluster = Math.floor(site.site_id / 100);
        site.cluster  = cluster;
        site.area     = CLUSTER_AREA[cluster] || 'Unknown';

        // Filter to active tech; keep all when 'all'
        const cells = (activeTech === 'all')
            ? site.cells
            : site.cells.filter(c => c.technology === activeTech);

        // Wedges only for on-air cells; offline cells stay in the list panel only.
        const wedgeCells = cells.filter(cellOperational);
        const groups = _groupCellsIntoWedges(site, wedgeCells);
        groups.forEach(g => drawSectorWedge(site, g));

        displaySiteInfo(site, cells);
    } catch (e) {
        console.error('Site detail error:', e);
        showNotification('Failed to load site details', 'error');
    }
}

/**
 * Draw a sector wedge polygon.
 *
 * Geographic azimuth convention:
 *   0° = North, 90° = East, 180° = South, 270° = West
 *
 *   lat  offset = R * cos(azimuth)   (North component)
 *   lng  offset = R * sin(azimuth)   (East component, scaled for latitude)
 */
function drawSectorWedge(site, group) {
    const az    = group.azimuth || 0;
    const half  = SECTOR_BEAMWIDTH / 2;
    const rLat  = SECTOR_RADIUS_M / 111320;
    const rLng  = SECTOR_RADIUS_M / (111320 * Math.cos(site.latitude * Math.PI / 180));

    const pts = [[site.latitude, site.longitude]];
    for (let a = az - half; a <= az + half; a += 3) {
        const rad = a * Math.PI / 180;
        pts.push([
            site.latitude  + rLat * Math.cos(rad),
            site.longitude + rLng * Math.sin(rad)
        ]);
    }
    pts.push([site.latitude, site.longitude]);

    const tech = group.technology || '';
    const color   = TECH_COLORS[tech] || '#34495e';
    const anyOnAir = group.cells.some(cellOperational);
    const polygon = L.polygon(pts, {
        color,
        fillColor: color,
        fillOpacity: anyOnAir ? 0.35 : 0.2,
        weight: 1.5
    }).addTo(map);

    // Store group payload for click handlers (avoid giant inline JSON in HTML).
    const groupId = group.groupId;
    wedgeGroups[groupId] = group;

    const cellCount = group.cells.length;
    const header = cellCount === 1
        ? group.cells[0].cell_name
        : `${cellCount} cells (select one)`;

    const cellsHtml = cellCount === 1
        ? ''
        : `<div style="margin-top:10px; display:flex; flex-direction:column; gap:6px;">
              ${group.cells.map(c => {
                  const meta = `${c.frequency_band ? ' · ' + c.frequency_band : ''}${c.pci != null ? ' · PCI/SC/BCCH: ' + c.pci : ''}`;
                  if (cellOperational(c)) {
                      return `<button onclick='showCellKPIs(${JSON.stringify(c.cell_name)})'
                        style="padding:6px 10px;background:${color};
                               color:white;border:none;border-radius:6px;cursor:pointer;
                               width:100%;font-weight:600;text-align:left;">
                    ${c.cell_name}
                    <span style="font-weight:500;opacity:.9;font-size:.85em;">${meta}</span>
                </button>`;
                  }
                  return `<div style="padding:6px 10px;border-radius:6px;background:#eee;color:#555;
                               font-size:0.9em;border:1px solid #ddd;">
                    <strong>${c.cell_name}</strong>${meta}
                    <div style="margin-top:4px;font-size:0.82em;color:#888;">Offline — no KPI panel</div>
                  </div>`;
              }).join('')}
           </div>`;

    // Use the first cell for summary metadata (band/tilt can vary per cell, but is usually identical).
    const ref = group.cells[0] || {};

    polygon.bindPopup(`
        <div style="min-width:220px;font-family:sans-serif;">
            <div style="font-weight:700;font-size:1em;margin-bottom:6px;">
                ${header}
            </div>
            <div style="color:${color};font-weight:600;margin-bottom:6px;">
                ${tech}
                ${ref.frequency_band ? ' · ' + ref.frequency_band : ''}
            </div>
            <table style="font-size:0.88em;border-collapse:collapse;width:100%;">
                <tr><td style="color:#777;">Azimuth</td>
                    <td style="font-weight:600;">${az}°</td></tr>
                ${ref.mechanical_tilt != null
                    ? `<tr><td style="color:#777;">M.Tilt</td>
                           <td>${ref.mechanical_tilt}°</td></tr>` : ''}
                ${ref.electrical_tilt != null
                    ? `<tr><td style="color:#777;">E.Tilt</td>
                           <td>${ref.electrical_tilt}°</td></tr>` : ''}
                ${ref.pci != null
                    ? `<tr><td style="color:#777;">PCI/SC/BCCH</td>
                           <td>${ref.pci}</td></tr>` : ''}
            </table>
            ${cellCount === 1 ? (
                cellOperational(ref)
                    ? `<button onclick='showCellKPIs(${JSON.stringify(ref.cell_name)})'
                      style="margin-top:10px;padding:6px 14px;background:${color};
                             color:white;border:none;border-radius:6px;cursor:pointer;
                             width:100%;font-weight:700;">
                  View cell details
              </button>`
                    : `<p style="margin-top:10px;color:#888;font-size:0.88em;line-height:1.35;">
                  Offline cell — KPI details are hidden.
                </p>`
            ) : cellsHtml}
        </div>
    `);

    polygon.on('click', e => { L.DomEvent.stopPropagation(e); polygon.openPopup(); });
    sectorLayers.push(polygon);
}

function clearSectorLayers() {
    sectorLayers.forEach(l => map.removeLayer(l));
    sectorLayers = [];
}

// ─── Site info panel ─────────────────────────────────────────────────────────

function displaySiteInfo(site, cells) {
    const panel = document.getElementById('site-info-panel');

    // Group cells by technology
    const byTech = {};
    cells.forEach(c => {
        (byTech[c.technology] = byTech[c.technology] || []).push(c);
    });

    let techHtml = '';
    TECH_ORDER.concat(
        Object.keys(byTech).filter(t => !TECH_ORDER.includes(t))
    ).forEach(tech => {
        if (!byTech[tech]) return;
        const color = TECH_COLORS[tech] || '#34495e';
        techHtml += `<div class="tech-group">
            <div class="tech-group-label" style="color:${color};">${tech}</div>`;
        byTech[tech].forEach(c => {
            const onAir = cellOperational(c);
            techHtml += `
            <div class="cell-row${onAir ? '' : ' cell-row-offline'}"
                 ${onAir ? `onclick='showCellKPIs(${JSON.stringify(c.cell_name)})'` : ''}>
                <span class="cell-name">${c.cell_name}</span>
                ${onAir ? '' : '<span class="cell-offline-badge">Offline</span>'}
                <span class="cell-meta">Az: ${c.azimuth ?? '—'}°</span>
                ${c.frequency_band
                    ? `<span class="cell-meta">${c.frequency_band}</span>`
                    : ''}
            </div>`;
        });
        techHtml += '</div>';
    });

    const offlineN = cells.filter(c => !cellOperational(c)).length;
    const offlineNote = offlineN > 0
        ? `<div class="site-meta-row site-offline-summary"><strong>Offline:</strong> ${offlineN} cell${offlineN === 1 ? '' : 's'} (no sector wedges)</div>`
        : '';

    panel.innerHTML = `
        <h3 class="site-panel-title">📡 ${site.site_name}</h3>
        <div class="site-meta-row"><strong>Site ID:</strong> ${site.site_id}</div>
        <div class="site-meta-row"><strong>Cluster:</strong> ${site.cluster ?? '—'}</div>
        <div class="site-meta-row"><strong>Area:</strong> ${site.area || '—'}</div>
        <div class="site-meta-row"><strong>Vendor:</strong> ${site.vendor || '—'}</div>
        <div class="site-meta-row"><strong>Cells shown:</strong> ${cells.length}</div>
        ${offlineNote}
        ${techHtml}
        <a href="/performance?site_id=${site.site_id}"
           class="kpi-link">
            📈 In-depth KPI
        </a>
    `;
    panel.style.display = 'block';
}

// ─── Cell KPI modal ───────────────────────────────────────────────────────────

async function showCellKPIs(cellId) {
    try {
        const url = (typeof cellId === 'number')
            ? `/api/map/cell/${cellId}/kpis`
            : `/api/map/cell/kpis?cell_name=${encodeURIComponent(String(cellId))}`;

        const res  = await fetch(url);
        const data = await res.json();
        if (!data.success) return;
        renderKPIModal(data.cell);
    } catch (e) {
        console.error('KPI error:', e);
    }
}

function renderKPIModal(cell) {
    const color = TECH_COLORS[cell.technology] || '#34495e';
    const kpis  = cell.kpis;
    const metadata = cell.metadata;

    const kpiRow = (label, val, unit = '') =>
        `<div class="kpi-item">
            <div class="kpi-label">${label}</div>
            <div class="kpi-value">${val != null ? val + unit : '—'}</div>
         </div>`;

    const known = kpis ? {
        avg_users: 'Users',
        data_volume_gb: 'Data (GB)',
        rsrp: 'RSRP (dBm)',
        rsrq: 'RSRQ (dB)',
        sinr: 'SINR (dB)',
        throughput_dl_mbps: 'DL Throughput (Mbps)',
        throughput_ul_mbps: 'UL Throughput (Mbps)',
        rrc_success_rate: 'RRC Success (%)',
        erab_success_rate: 'ERAB Success (%)',
        call_drop_rate: 'Drop Rate (%)',
        handover_success_rate: 'HO Success (%)',
        availability_percent: 'Availability (%)',
    } : {};

    const _fmt = (v) => {
        if (v == null) return null;
        if (typeof v === 'number') return Number.isFinite(v) ? v : null;
        // Try numeric strings
        const asNum = Number(v);
        return Number.isFinite(asNum) && String(v).trim() !== '' ? asNum : v;
    };

    const summaryGrid = kpis ? (() => {
        const entries = Object.entries(known)
            .map(([key, label]) => [label, _fmt(kpis[key])])
            .filter(([, v]) => v != null);
        if (!entries.length) return '';
        return `<div class="kpi-grid">
            ${entries.map(([label, v]) => kpiRow(label, (typeof v === 'number' ? v.toFixed(2) : v))).join('')}
        </div>`;
    })() : '';

    const detailsTable = kpis ? (() => {
        const skip = new Set(['id', 'cell_name', 'timestamp']);
        const rows = Object.keys(kpis)
            .filter(k => !skip.has(k))
            .sort()
            .map(k => ({ k, v: kpis[k] }))
            .filter(r => r.v != null && String(r.v).trim() !== '');

        if (!rows.length) return '';
        const max = 40;
        const shown = rows.slice(0, max);
        const more = rows.length - shown.length;
        return `
            <div style="margin-top:14px;">
                <div style="font-weight:800;color:#2c3e50;margin-bottom:8px;">All KPI fields</div>
                <div style="max-height:260px; overflow:auto; border:1px solid #eee; border-radius:8px;">
                    <table style="width:100%; border-collapse:collapse; font-size:0.88em;">
                        ${shown.map(r => `
                          <tr>
                            <td style="padding:8px 10px; border-bottom:1px solid #f1f1f1; color:#666; width:55%;">${r.k}</td>
                            <td style="padding:8px 10px; border-bottom:1px solid #f1f1f1; font-weight:700; color:#2c3e50;">${r.v}</td>
                          </tr>
                        `).join('')}
                    </table>
                </div>
                ${more > 0 ? `<div style="margin-top:6px;color:#7f8c8d;font-size:0.82em;">Showing ${shown.length}/${rows.length} fields</div>` : ''}
            </div>
        `;
    })() : '';

    const metadataTable = metadata ? (() => {
        const rows = Object.keys(metadata)
            .sort()
            .map(k => ({ k, v: metadata[k] }))
            .filter(r => r.v != null && String(r.v).trim() !== '');
        if (!rows.length) return '';
        const max = 80;
        const shown = rows.slice(0, max);
        const more = rows.length - shown.length;
        return `
            <div style="margin-top:14px;">
                <div style="font-weight:800;color:#2c3e50;margin-bottom:8px;">All cell metadata fields</div>
                <div style="max-height:260px; overflow:auto; border:1px solid #eee; border-radius:8px;">
                    <table style="width:100%; border-collapse:collapse; font-size:0.88em;">
                        ${shown.map(r => `
                          <tr>
                            <td style="padding:8px 10px; border-bottom:1px solid #f1f1f1; color:#666; width:55%;">${r.k}</td>
                            <td style="padding:8px 10px; border-bottom:1px solid #f1f1f1; font-weight:700; color:#2c3e50;">${r.v}</td>
                          </tr>
                        `).join('')}
                    </table>
                </div>
                ${more > 0 ? `<div style="margin-top:6px;color:#7f8c8d;font-size:0.82em;">Showing ${shown.length}/${rows.length} fields</div>` : ''}
            </div>
        `;
    })() : '';

    const kpiHtml = kpis
        ? `${summaryGrid}
           <div style="font-size:0.82em;color:#7f8c8d;margin-top:10px;">
               Last: ${kpis.timestamp ? new Date(kpis.timestamp).toLocaleString() : '—'}
           </div>
           ${detailsTable}`
        : `<p style="color:#95a5a6;">No KPI data available</p>`;

    const perfUrl = (() => {
        const params = new URLSearchParams();
        if (cell.site_id != null) params.set('site_id', String(cell.site_id));
        if (cell.cell_name) params.set('cell_name', String(cell.cell_name));
        if (cell.technology) params.set('technology', String(cell.technology));
        const qs = params.toString();
        return qs ? `/performance?${qs}` : '/performance';
    })();

    document.getElementById('kpi-content').innerHTML = `
        <span class="close-modal" onclick="closeKPIModal()">&times;</span>
        <h2 style="margin-top:0;color:#0a0a0a;border-bottom:3px solid ${color};
                   padding-bottom:8px;">
            ${cell.cell_name}
        </h2>
        <div style="margin-bottom:14px;color:#444;font-size:0.9em;line-height:1.7;">
            <strong style="color:#0a0a0a;">Site:</strong> <span style="color:#0a0a0a;font-weight:600;">${cell.site_name || '—'}</span> &nbsp;|&nbsp;
            <strong style="color:${color};">${cell.technology || '—'}</strong>
            &nbsp;|&nbsp; Vendor: ${cell.vendor || '—'}
            &nbsp;|&nbsp; Az: ${cell.azimuth ?? '—'}°
            &nbsp;|&nbsp; PCI/SC/BCCH: ${cell.pci ?? '—'}
            <br/>
            <strong>Activity:</strong> ${cell.activity_status || cell.status || '—'}
            &nbsp;|&nbsp; <strong>Band:</strong> ${cell.frequency_band || '—'}
            &nbsp;|&nbsp; <strong>Tilts:</strong> M ${cell.mechanical_tilt ?? '—'}° / E ${cell.electrical_tilt ?? '—'}°
        </div>
        <a href="${perfUrl}"
           style="display:inline-block;margin:2px 0 12px;padding:8px 12px;background:${color};
                  color:#fff;text-decoration:none;border-radius:8px;font-weight:700;font-size:0.88em;">
            📈 Open in Performance Page
        </a>
        ${kpiHtml}
        ${metadataTable}
    `;
    document.getElementById('kpi-modal').style.display = 'flex';
}

function closeKPIModal() {
    document.getElementById('kpi-modal').style.display = 'none';
}

// ─── Cell-code search (SC / PCI / BCCH) ──────────────────────────────────────

function cellCodeSearch() {
    clearTimeout(codeSearchTimer);
    const val = document.getElementById('cell-code-search').value.trim();
    if (!val) { clearHighlights(); return; }
    codeSearchTimer = setTimeout(doCodeSearch, 400);
}

async function doCodeSearch() {
    const code = document.getElementById('cell-code-search').value.trim();
    if (!code || isNaN(code)) return;

    clearHighlights();

    const techParam = activeTech !== 'all'
        ? `&tech=${encodeURIComponent(activeTech)}` : '';

    try {
        const res  = await fetch(`/api/map/search/cell-code?code=${code}${techParam}`);
        const data = await res.json();
        if (!data.success) return;

        const panel = document.getElementById('site-info-panel');
        if (!data.matches.length) {
            const techLabel = _codeLabel();
            panel.innerHTML = `<div class="code-no-results">No cells found with ${techLabel} = ${code}</div>`;
            panel.style.display = 'block';
            return;
        }

        drawCodeSearchResults(data.matches, parseInt(code));
    } catch (e) {
        console.error('Code search error:', e);
    }
}

function drawCodeSearchResults(matches, code) {
    // Hide all regular site markers — only show matching ones
    siteMarkers.forEach(m => map.removeLayer(m));

    // Group by site
    const siteMap = {};
    matches.forEach(cell => {
        if (!siteMap[cell.site_id]) {
            siteMap[cell.site_id] = {
                site_id:   cell.site_id,
                site_name: cell.site_name,
                latitude:  cell.latitude,
                longitude: cell.longitude,
                cells: []
            };
        }
        siteMap[cell.site_id].cells.push(cell);
    });

    // Draw highlight wedges for every matching cell that has azimuth data
    matches.forEach(cell => {
        if (cellOperational(cell) && cell.azimuth != null) drawHighlightWedge(cell);
    });

    // Drop highlight markers on matching sites only
    Object.values(siteMap).forEach(site => {
        site.offline_cell_count = site.cells.filter(c => !cellOperational(c)).length;
        const fromList = sitesData.find(s => String(s.site_id) === String(site.site_id));
        site.full_sector_offline_count = fromList != null && fromList.full_sector_offline_count != null
            ? Number(fromList.full_sector_offline_count) || 0
            : 0;
        const { iconSize, iconAnchor } = sitePinIconMetrics();
        const icon = L.divIcon({
            className: 'site-marker',
            html: sitePinInnerHtml(site, { highlight: true }),
            iconSize,
            iconAnchor,
        });
        const marker = L.marker([site.latitude, site.longitude], { icon }).addTo(map);
        marker.on('click', () => showSiteDetails(site.site_id));
        highlightMarkers.push(marker);
    });

    // Populate side panel
    const techLabel = _codeLabel();
    const techParam = activeTech !== 'all' ? activeTech : '';
    let siteHtml = '';
    Object.values(siteMap).forEach(site => {
        siteHtml += `
            <div class="code-result-site" onclick="showSiteDetails('${site.site_id}')">
                <div class="code-result-site-name">📡 ${site.site_name}</div>`;
        site.cells.forEach(c => {
            const color = TECH_COLORS[c.technology] || '#34495e';
            const off = !cellOperational(c);
            siteHtml += `
                <div class="code-result-cell${off ? ' code-result-cell-offline' : ''}">
                    <span class="cell-tech-badge" style="background:${color}">${c.technology}</span>
                    <span class="cell-name">${c.cell_name}</span>
                    ${off ? '<span class="code-offline-hint">offline</span>' : ''}
                    <span class="cell-meta">Az: ${c.azimuth ?? '—'}°</span>
                </div>`;
        });
        siteHtml += '</div>';
    });

    const panel = document.getElementById('site-info-panel');
    panel.innerHTML = `
        <h3 class="site-panel-title">🔍 ${techLabel} = ${code}</h3>
        <div class="site-meta-row" style="margin-bottom:8px;">
            ${matches.length} cell${matches.length !== 1 ? 's' : ''}
            across ${Object.keys(siteMap).length} site${Object.keys(siteMap).length !== 1 ? 's' : ''}
        </div>
        <button class="export-btn" onclick="exportCodeSearch(${code}, '${techParam}')">
            ⬇ Export to Excel
        </button>
        ${siteHtml}
    `;
    panel.style.display = 'block';
}

/** Download matching cells as an Excel file. */
function exportCodeSearch(code, tech) {
    const techParam = tech ? `&tech=${encodeURIComponent(tech)}` : '';
    window.location.href = `/api/map/export/cell-code?code=${code}${techParam}`;
}

function drawHighlightWedge(cell) {
    if (!cellOperational(cell)) return;
    const az    = cell.azimuth || 0;
    const half  = SECTOR_BEAMWIDTH / 2;
    const rLat  = SECTOR_RADIUS_M / 111320;
    const rLng  = SECTOR_RADIUS_M / (111320 * Math.cos(cell.latitude * Math.PI / 180));

    const pts = [[cell.latitude, cell.longitude]];
    for (let a = az - half; a <= az + half; a += 3) {
        const rad = a * Math.PI / 180;
        pts.push([
            cell.latitude  + rLat * Math.cos(rad),
            cell.longitude + rLng * Math.sin(rad)
        ]);
    }
    pts.push([cell.latitude, cell.longitude]);

    const techColor = TECH_COLORS[cell.technology] || '#34495e';
    const polygon   = L.polygon(pts, {
        color:       '#f1c40f',   // bright yellow border = highlighted
        fillColor:   techColor,
        fillOpacity: 0.65,
        weight:      3,
    }).addTo(map);

    polygon.bindPopup(`
        <div style="min-width:190px;font-family:sans-serif;">
            <div style="font-weight:700;font-size:1em;margin-bottom:6px;">
                ${cell.cell_name}
            </div>
            <div style="color:${techColor};font-weight:600;margin-bottom:6px;">
                ${cell.technology || ''}
                ${cell.frequency_band ? ' · ' + cell.frequency_band : ''}
            </div>
            <table style="font-size:0.88em;border-collapse:collapse;width:100%;">
                <tr><td style="color:#777;">${_codeLabel()}</td>
                    <td style="font-weight:600;color:#e67e22;">${cell.pci}</td></tr>
                <tr><td style="color:#777;">Azimuth</td>
                    <td style="font-weight:600;">${az}°</td></tr>
                ${cell.mechanical_tilt != null
                    ? `<tr><td style="color:#777;">M.Tilt</td><td>${cell.mechanical_tilt}°</td></tr>` : ''}
                ${cell.electrical_tilt != null
                    ? `<tr><td style="color:#777;">E.Tilt</td><td>${cell.electrical_tilt}°</td></tr>` : ''}
            </table>
            ${cellOperational(cell)
        ? `<button onclick='showCellKPIs(${JSON.stringify(cell.cell_name)})'
                    style="margin-top:10px;padding:5px 14px;background:${techColor};
                           color:white;border:none;border-radius:5px;cursor:pointer;
                           width:100%;font-weight:600;">
                View KPIs
            </button>`
        : `<p style="margin-top:10px;color:#888;font-size:0.85em;">Offline — KPIs hidden.</p>`}
        </div>
    `);
    polygon.on('click', e => { L.DomEvent.stopPropagation(e); polygon.openPopup(); });
    highlightLayers.push(polygon);
}

function clearHighlights() {
    highlightLayers.forEach(l => map && map.removeLayer(l));
    highlightLayers = [];
    highlightMarkers.forEach(m => map && map.removeLayer(m));
    highlightMarkers = [];
    // Restore all regular site markers
    siteMarkers.forEach(m => { try { m.addTo(map); } catch (_) {} });
}

function clearCodeSearch() {
    document.getElementById('cell-code-search').value = '';
    clearHighlights();
    document.getElementById('site-info-panel').style.display = 'none';
}

/** Returns the human label for the active-tech code type. */
function _codeLabel() {
    if (activeTech === '3G') return 'SC';
    if (['4G', '4G-FDD', '4G-TDD'].includes(activeTech)) return 'PCI';
    if (activeTech === '5G') return 'PCI';
    if (activeTech === '2G') return 'BCCH';
    return 'Code';
}

// ─── Filter builders ──────────────────────────────────────────────────────────

function buildClusterFilter(sites) {
    const select  = document.getElementById('cluster-filter');
    const current = select.value;
    const clusters = [...new Set(sites.map(s => s.cluster).filter(c => c != null))]
        .sort((a, b) => a - b);

    select.innerHTML = '<option value="all">All Clusters</option>';
    clusters.forEach(c => {
        const opt = document.createElement('option');
        opt.value = String(c);
        opt.textContent = `Cluster ${c}`;
        if (String(c) === current) opt.selected = true;
        select.appendChild(opt);
    });
}

function buildAreaFilter(sites) {
    const select  = document.getElementById('area-filter');
    const current = select.value;
    const areas = [...new Set(sites.map(s => s.area).filter(Boolean))].sort();

    select.innerHTML = '<option value="all">All Areas</option>';
    areas.forEach(a => {
        const opt = document.createElement('option');
        opt.value = a;
        opt.textContent = a;
        if (a === current) opt.selected = true;
        select.appendChild(opt);
    });
}

// ─── Filter callbacks (all funnel into runFilters) ────────────────────────────

function searchSites()    { runFilters(); }
function filterByVendor() { _onFilterChanged(); }
function filterByArea()   { _onFilterChanged(); }
function filterByCluster(){ _onFilterChanged(); }

// ─── Metadata refresh ────────────────────────────────────────────────────────

async function refreshMetadata() {
    const btn = document.getElementById('refresh-btn');
    btn.disabled = true;
    btn.textContent = '↻ Syncing…';

    try {
        const res  = await fetch('/api/map/refresh', { method: 'POST' });
        const data = await res.json();

        if (data.success) {
            btn.textContent = '✓ Started — reloading in 15 s…';
            // Give the background sync time to download + process files,
            // then automatically reload the map data.
            setTimeout(async () => {
                await loadNetworkStats();
                await loadNetworkSites();
                btn.textContent = '↻ Refresh Data';
                btn.disabled = false;
            }, 15000);
        } else {
            btn.textContent = '✗ Failed: ' + (data.error || 'unknown');
            setTimeout(() => {
                btn.textContent = '↻ Refresh Data';
                btn.disabled = false;
            }, 4000);
        }
    } catch (e) {
        btn.textContent = '✗ Error';
        setTimeout(() => {
            btn.textContent = '↻ Refresh Data';
            btn.disabled = false;
        }, 3000);
    }
}

// ─── Measuring tool ───────────────────────────────────────────────────────────

function toggleMeasure() {
    measureActive = !measureActive;
    const btn = document.getElementById('measure-btn');
    if (measureActive) {
        btn.classList.add('active');
        btn.textContent = '✕ Stop Measuring';
        map.getContainer().style.cursor = 'crosshair';
        map.on('click', onMeasureClick);
    } else {
        btn.classList.remove('active');
        btn.textContent = '📏 Measure Distance';
        map.getContainer().style.cursor = '';
        map.off('click', onMeasureClick);
        clearMeasure();
    }
}

function onMeasureClick(e) {
    measurePoints.push(e.latlng);

    const pt = L.circleMarker(e.latlng, {
        radius: 5, color: '#e74c3c', fillColor: '#fff',
        fillOpacity: 1, weight: 2.5
    }).addTo(map);
    measurePtMarkers.push(pt);

    if (measurePoints.length < 2) return;

    // Redraw polyline through all points
    if (measurePolyline) map.removeLayer(measurePolyline);
    measurePolyline = L.polyline(measurePoints, {
        color: '#e74c3c', weight: 2, dashArray: '7,5', opacity: 0.85
    }).addTo(map);

    // Accumulate total distance
    let totalM = 0;
    for (let i = 1; i < measurePoints.length; i++) {
        totalM += measurePoints[i - 1].distanceTo(measurePoints[i]);
    }
    const distText = totalM >= 1000
        ? `${(totalM / 1000).toFixed(2)} km`
        : `${Math.round(totalM)} m`;

    // Segment distance for last segment
    const segM     = measurePoints[measurePoints.length - 2]
                        .distanceTo(measurePoints[measurePoints.length - 1]);
    const segText  = segM >= 1000
        ? `+${(segM / 1000).toFixed(2)} km`
        : `+${Math.round(segM)} m`;

    // Move/update total label to last point
    if (measureDistLabel) map.removeLayer(measureDistLabel);
    measureDistLabel = L.marker(e.latlng, {
        icon: L.divIcon({
            className: 'measure-label-icon',
            html: `<div class="measure-tooltip">
                       <span class="measure-total">${distText}</span>
                       <span class="measure-seg">${segText}</span>
                   </div>`,
            iconAnchor: [-8, 10]
        }),
        interactive: false,
        zIndexOffset: 1000
    }).addTo(map);
}

function clearMeasure() {
    measurePtMarkers.forEach(m => map && map.removeLayer(m));
    measurePtMarkers = [];
    if (measurePolyline)  { map.removeLayer(measurePolyline);  measurePolyline  = null; }
    if (measureDistLabel) { map.removeLayer(measureDistLabel); measureDistLabel = null; }
    measurePoints = [];
}

// Close modal on backdrop click
window.addEventListener('click', e => {
    if (e.target === document.getElementById('kpi-modal')) closeKPIModal();
});

window.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeKPIModal();
});

window.addEventListener('pageshow', e => {
    if (e.persisted) closeKPIModal();
});

// ─── Export (Excel / KML) ────────────────────────────────────────────────────
function exportCurrentView(format) {
    const tech   = activeTech !== 'all' ? activeTech : '';
    const vendor = document.getElementById('vendor-filter').value;
    const search = document.getElementById('site-search').value.trim();

    const params = new URLSearchParams();
    if (tech)             params.set('tech',   tech);
    if (activeTechSpecific !== 'all') params.set('tech_value', activeTechSpecific);
    if (vendor !== 'all') params.set('vendor', vendor);
    if (search)           params.set('search', search);

    const endpoint = format === 'kml'
        ? `/api/map/export/kml?${params}`
        : `/api/map/export/sites?${params}`;

    window.location.href = endpoint;
}

// ─── Wedge grouping ───────────────────────────────────────────────────────────

function _azBucket(az) {
    // bucket azimuth into 5° bins so co-sector cells combine into one wedge
    const a = Number(az);
    if (!Number.isFinite(a)) return null;
    return Math.round(a / 5) * 5;
}

function _groupCellsIntoWedges(site, cells) {
    // Reset wedgeGroups whenever we redraw site wedges
    wedgeGroups = {};

    const byKey = {};
    cells
        .filter(c => c && c.azimuth != null && Number.isFinite(Number(c.azimuth)))
        .forEach(c => {
            const tech = c.technology || 'Unknown';
            const bucket = _azBucket(c.azimuth);
            const key = `${site.site_id}|${tech}|${bucket}`;
            if (!byKey[key]) byKey[key] = { technology: tech, azimuth: bucket, cells: [] };
            byKey[key].cells.push(c);
        });

    const groups = Object.values(byKey);
    // Stable order: technology then azimuth then cell_name
    groups.sort((a, b) => {
        if (a.technology !== b.technology) return String(a.technology).localeCompare(String(b.technology));
        if (a.azimuth !== b.azimuth) return Number(a.azimuth) - Number(b.azimuth);
        return String(a.cells?.[0]?.cell_name || '').localeCompare(String(b.cells?.[0]?.cell_name || ''));
    });

    // Attach group ids
    groups.forEach((g, idx) => {
        g.groupId = `${site.site_id}-${g.technology}-${g.azimuth}-${idx}`;
        // Sort cells in the popup list for readability
        g.cells.sort((x, y) => String(x.cell_name).localeCompare(String(y.cell_name)));
    });

    return groups;
}

// ─── Empty state + filter wiring ──────────────────────────────────────────────

function _hasActiveFilters() {
    const term    = (document.getElementById('site-search')?.value || '').trim();
    const vendor  = document.getElementById('vendor-filter')?.value || 'all';
    const area    = document.getElementById('area-filter')?.value || 'all';
    const cluster = document.getElementById('cluster-filter')?.value || 'all';
    const code    = (document.getElementById('cell-code-search')?.value || '').trim();
    const techSpecific = document.getElementById('tech-specific-filter')?.value || 'all';
    const lat     = (document.getElementById('coord-lat')?.value || '').trim();
    const lng     = (document.getElementById('coord-lng')?.value || '').trim();

    return Boolean(
        activeTech !== 'all' ||
        vendor !== 'all' ||
        area !== 'all' ||
        cluster !== 'all' ||
        techSpecific !== 'all' ||
        term ||
        code ||
        (lat && lng)
    );
}

async function updateTechSpecificFilter() {
    const select = document.getElementById('tech-specific-filter');
    if (!select) return;

    // Only show for requested technologies.
    if (!['2G', '3G', '4G-FDD', '4G-TDD'].includes(activeTech)) {
        select.style.display = 'none';
        select.innerHTML = '<option value="all">All</option>';
        activeTechSpecific = 'all';
        return;
    }

    try {
        const res = await fetch(`/api/map/tech-filter-options?tech=${encodeURIComponent(activeTech)}`);
        const data = await res.json();
        if (!data.success) throw new Error(data.error || 'Failed to load filter values');

        const label = data.label || 'Value';
        const values = Array.isArray(data.values) ? data.values : [];
        select.innerHTML = `<option value="all">All ${label}</option>` +
            values.map(v => `<option value="${String(v)}">${String(v)}</option>`).join('');
        select.style.display = 'block';
        select.value = 'all';
        activeTechSpecific = 'all';
    } catch (e) {
        console.error('Tech-specific filter error:', e);
        select.style.display = 'none';
        select.innerHTML = '<option value="all">All</option>';
        activeTechSpecific = 'all';
    }
}

function filterByTechSpecific() {
    const select = document.getElementById('tech-specific-filter');
    activeTechSpecific = (select?.value || 'all').trim() || 'all';
    _onFilterChanged();
}

function _showEmptyState() {
    document.getElementById('sites-count').textContent = '0';
    const panel = document.getElementById('site-info-panel');
    if (!panel) return;
    panel.innerHTML = `
        <div style="color:#2c3e50;font-weight:800;margin-bottom:6px;">Map is ready</div>
        <div style="color:#555;font-size:0.88em;line-height:1.6;">
            Select <strong>Technology</strong>, <strong>Vendor</strong>, <strong>Area</strong> or <strong>Cluster</strong>
            (or use <strong>SC/PCI/BCCH</strong> search) to load sites.
        </div>
    `;
    panel.style.display = 'block';
}

function _wireInitialFilterListeners() {
    // When user starts filtering, load sites from the server.
    const ids = ['vendor-filter', 'area-filter', 'cluster-filter'];
    ids.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('change', _onFilterChanged);
    });
    const search = document.getElementById('site-search');
    if (search) search.addEventListener('input', () => _onFilterChanged(true));
}

let _filterDebounce = null;
function _onFilterChanged(isTyping = false) {
    // Clear selections when filters change
    clearSectorLayers();
    clearHighlights();
    document.getElementById('site-info-panel').style.display = 'none';

    if (isTyping) {
        clearTimeout(_filterDebounce);
        _filterDebounce = setTimeout(loadNetworkSites, 250);
        return;
    }
    loadNetworkSites();
}

// ─── Coordinate search (lat/lng) ──────────────────────────────────────────────

function goToCoordinates() {
    const lat = parseFloat(document.getElementById('coord-lat')?.value);
    const lng = parseFloat(document.getElementById('coord-lng')?.value);
    if (!Number.isFinite(lat) || !Number.isFinite(lng)) {
        showNotification('Enter valid latitude & longitude', 'error');
        return;
    }
    if (!map) return;

    // Pan/zoom and drop a marker
    map.setView([lat, lng], Math.max(map.getZoom(), 14));
    if (coordMarker) map.removeLayer(coordMarker);
    coordMarker = L.marker([lat, lng]).addTo(map);
    coordMarker.bindPopup(`<div style="font-weight:700;">📍 Coordinate</div><div>${lat.toFixed(6)}, ${lng.toFixed(6)}</div>`).openPopup();

    // If sites are not loaded yet, load them (filters now active via lat/lng)
    if (!sitesData.length) {
        loadNetworkSites();
    }
}

function showNearestSitesFromCoordinates() {
    const lat = parseFloat(document.getElementById('coord-lat')?.value);
    const lng = parseFloat(document.getElementById('coord-lng')?.value);
    if (!Number.isFinite(lat) || !Number.isFinite(lng)) {
        showNotification('Enter valid latitude & longitude first', 'error');
        return;
    }
    if (!sitesData.length) {
        showNotification('Load sites first by applying a filter', 'info');
        return;
    }

    // Highlight nearest sites (top 10 within 10km) only on explicit user request.
    const target = L.latLng(lat, lng);
    const withinKm = 10;
    const nearest = sitesData
        .map(s => ({ s, d: target.distanceTo([s.latitude, s.longitude]) / 1000 }))
        .filter(x => Number.isFinite(x.d))
        .sort((a, b) => a.d - b.d)
        .slice(0, 10)
        .filter(x => x.d <= withinKm);

    if (!nearest.length) {
        showNotification(`No sites within ${withinKm} km`, 'info');
        return;
    }

    // Render only the nearest sites as markers (temporary view)
    displaySites(nearest.map(x => x.s));
    const panel = document.getElementById('site-info-panel');
    panel.innerHTML = `
        <h3 class="site-panel-title">📍 Nearest sites</h3>
        <div class="site-meta-row">Showing ${nearest.length} within ${withinKm} km</div>
        ${nearest.map(x => `
          <div class="cell-row" onclick="showSiteDetails('${x.s.site_id}')">
            <span class="cell-name">${x.s.site_name}</span>
            <span class="cell-meta">${x.d.toFixed(2)} km</span>
          </div>
        `).join('')}
    `;
    panel.style.display = 'block';
}
