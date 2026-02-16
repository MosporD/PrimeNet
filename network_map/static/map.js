/**
 * Network Map – Leaflet visualization
 * Sites → sector wedges drawn per cell (azimuth-aligned)
 * Tech filter: All / 2G / 3G / 4G / 4G-FDD / 4G-TDD / 5G
 */

// ─── Constants ───────────────────────────────────────────────────────────────

const TECH_COLORS = {
    '2G':     '#7f8c8d',
    '3G':     '#27ae60',
    '4G':     '#3498db',
    '4G-FDD': '#1a5276',
    '4G-TDD': '#148f77',
    '5G':     '#9b59b6',
};

const TECH_ORDER = ['2G', '3G', '4G', '4G-FDD', '4G-TDD', '5G'];

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
let activeTech       = '3G';
let highlightMarkers = [];
let highlightLayers  = [];
let codeSearchTimer  = null;

// ─── Initialization ──────────────────────────────────────────────────────────

function initializeMap() {
    if (map) { map.invalidateSize(); return; }

    map = L.map('network-map').setView(DEFAULT_CENTER, DEFAULT_ZOOM);

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© OpenStreetMap contributors',
        maxZoom: 18
    }).addTo(map);

    loadNetworkStats().then(() => loadNetworkSites());
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
            tech === '2G'                             ? 'BCCH...'            :
                                                        'SC / PCI / BCCH...';
    }
    loadNetworkSites();
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
    const filtered = applyClientFilters(sitesData);
    displaySites(filtered);
    document.getElementById('sites-count').textContent = filtered.length;
    if (filtered.length > 0)
        map.fitBounds(
            filtered.map(s => [s.latitude, s.longitude]),
            { padding: [50, 50] }
        );
}

// ─── Site loading & display ───────────────────────────────────────────────────

async function loadNetworkSites() {
    try {
        const url  = activeTech !== 'all'
            ? `/api/map/sites?tech=${encodeURIComponent(activeTech)}`
            : '/api/map/sites';
        const res  = await fetch(url);
        const data = await res.json();
        if (!data.success) return;

        sitesData = enrichSites(data.sites);

        const filtered = applyClientFilters(sitesData);
        displaySites(filtered);
        document.getElementById('sites-count').textContent = filtered.length;

        if (filtered.length > 0) {
            map.fitBounds(
                filtered.map(s => [s.latitude, s.longitude]),
                { padding: [50, 50] }
            );
        }

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

    sites.forEach(site => {
        const color = activeTech !== 'all'
            ? (TECH_COLORS[activeTech] || '#3498db')
            : (site.vendor === 'Nokia' ? '#00a3e0' : '#e55300');

        const icon = L.divIcon({
            className: 'site-marker',
            html: `<div class="site-marker-inner" style="border-color:${color}" title="${site.site_name}">
                     <div class="site-icon">📡</div>
                   </div>`,
            iconSize: [36, 36],
            iconAnchor: [18, 18]
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

        // Draw a wedge per cell that has azimuth data
        cells
            .filter(c => c.azimuth != null)
            .forEach(cell => drawSectorWedge(site, cell));

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
function drawSectorWedge(site, cell) {
    const az    = cell.azimuth || 0;
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

    const color   = TECH_COLORS[cell.technology] || '#34495e';
    const polygon = L.polygon(pts, {
        color,
        fillColor: color,
        fillOpacity: 0.35,
        weight: 1.5
    }).addTo(map);

    polygon.bindPopup(`
        <div style="min-width:190px;font-family:sans-serif;">
            <div style="font-weight:700;font-size:1em;margin-bottom:6px;">
                ${cell.cell_name}
            </div>
            <div style="color:${color};font-weight:600;margin-bottom:6px;">
                ${cell.technology || ''}
                ${cell.frequency_band ? ' · ' + cell.frequency_band : ''}
            </div>
            <table style="font-size:0.88em;border-collapse:collapse;width:100%;">
                <tr><td style="color:#777;">Azimuth</td>
                    <td style="font-weight:600;">${az}°</td></tr>
                ${cell.mechanical_tilt != null
                    ? `<tr><td style="color:#777;">M.Tilt</td>
                           <td>${cell.mechanical_tilt}°</td></tr>` : ''}
                ${cell.electrical_tilt != null
                    ? `<tr><td style="color:#777;">E.Tilt</td>
                           <td>${cell.electrical_tilt}°</td></tr>` : ''}
                ${cell.pci != null
                    ? `<tr><td style="color:#777;">PCI</td>
                           <td>${cell.pci}</td></tr>` : ''}
            </table>
            <button onclick="showCellKPIs(${cell.cell_id})"
                    style="margin-top:10px;padding:5px 14px;background:${color};
                           color:white;border:none;border-radius:5px;cursor:pointer;
                           width:100%;font-weight:600;">
                View KPIs
            </button>
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
            techHtml += `
            <div class="cell-row" onclick="showCellKPIs(${c.cell_id})">
                <span class="cell-name">${c.cell_name}</span>
                <span class="cell-meta">Az: ${c.azimuth ?? '—'}°</span>
                ${c.frequency_band
                    ? `<span class="cell-meta">${c.frequency_band}</span>`
                    : ''}
            </div>`;
        });
        techHtml += '</div>';
    });

    panel.innerHTML = `
        <h3 class="site-panel-title">📡 ${site.site_name}</h3>
        <div class="site-meta-row"><strong>Site ID:</strong> ${site.site_id}</div>
        <div class="site-meta-row"><strong>Cluster:</strong> ${site.cluster ?? '—'}</div>
        <div class="site-meta-row"><strong>Area:</strong> ${site.area || '—'}</div>
        <div class="site-meta-row"><strong>Vendor:</strong> ${site.vendor || '—'}</div>
        <div class="site-meta-row"><strong>Cells shown:</strong> ${cells.length}</div>
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
        const res  = await fetch(`/api/map/cell/${cellId}/kpis`);
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

    const kpiRow = (label, val, unit = '') =>
        `<div class="kpi-item">
            <div class="kpi-label">${label}</div>
            <div class="kpi-value">${val != null ? val + unit : '—'}</div>
         </div>`;

    const kpiHtml = kpis
        ? `<div class="kpi-grid">
               ${kpiRow('Users',      kpis.avg_users)}
               ${kpiRow('Data',       kpis.data_volume_gb?.toFixed(2), ' GB')}
               ${kpiRow('RSRP',       kpis.rsrp?.toFixed(1),           ' dBm')}
               ${kpiRow('RSRQ',       kpis.rsrq?.toFixed(1),           ' dB')}
               ${kpiRow('SINR',       kpis.sinr?.toFixed(1),           ' dB')}
               ${kpiRow('DL Tput',    kpis.throughput_dl_mbps?.toFixed(1), ' Mbps')}
               ${kpiRow('RRC Succ',   kpis.rrc_success_rate?.toFixed(2),   '%')}
               ${kpiRow('Drop Rate',  kpis.call_drop_rate?.toFixed(2),      '%')}
               ${kpiRow('Avail',      kpis.availability_percent?.toFixed(2), '%')}
           </div>
           <div style="font-size:0.82em;color:#7f8c8d;margin-top:10px;">
               Last: ${kpis.timestamp ? new Date(kpis.timestamp).toLocaleString() : '—'}
           </div>`
        : `<p style="color:#95a5a6;">No KPI data available</p>`;

    document.getElementById('kpi-content').innerHTML = `
        <span class="close-modal" onclick="closeKPIModal()">&times;</span>
        <h2 style="margin-top:0;color:#2C3E50;border-bottom:3px solid ${color};
                   padding-bottom:8px;">
            ${cell.cell_name}
        </h2>
        <div style="margin-bottom:14px;color:#555;font-size:0.9em;line-height:1.7;">
            <strong>Site:</strong> ${cell.site_name || '—'} &nbsp;|&nbsp;
            <strong style="color:${color};">${cell.technology || '—'}</strong>
            &nbsp;|&nbsp; Az: ${cell.azimuth ?? '—'}°
            &nbsp;|&nbsp; PCI: ${cell.pci ?? '—'}
        </div>
        ${kpiHtml}
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
        if (cell.azimuth != null) drawHighlightWedge(cell);
    });

    // Drop highlight markers on matching sites
    Object.values(siteMap).forEach(site => {
        const icon = L.divIcon({
            className: 'site-marker',
            html: `<div class="site-marker-inner highlight-marker" title="${site.site_name}">
                     <div class="site-icon">📡</div>
                   </div>`,
            iconSize: [36, 36],
            iconAnchor: [18, 18]
        });
        const marker = L.marker([site.latitude, site.longitude], { icon }).addTo(map);
        marker.on('click', () => showSiteDetails(site.site_id));
        highlightMarkers.push(marker);
    });

    // Fit map to matches
    map.fitBounds(
        matches.map(m => [m.latitude, m.longitude]),
        { padding: [60, 60] }
    );

    // Populate side panel
    const techLabel = _codeLabel();
    let siteHtml = '';
    Object.values(siteMap).forEach(site => {
        siteHtml += `
            <div class="code-result-site" onclick="showSiteDetails('${site.site_id}')">
                <div class="code-result-site-name">📡 ${site.site_name}</div>`;
        site.cells.forEach(c => {
            const color = TECH_COLORS[c.technology] || '#34495e';
            siteHtml += `
                <div class="code-result-cell">
                    <span class="cell-tech-badge" style="background:${color}">${c.technology}</span>
                    <span class="cell-name">${c.cell_name}</span>
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
        ${siteHtml}
    `;
    panel.style.display = 'block';
}

function drawHighlightWedge(cell) {
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
            <button onclick="showCellKPIs(${cell.cell_id})"
                    style="margin-top:10px;padding:5px 14px;background:${techColor};
                           color:white;border:none;border-radius:5px;cursor:pointer;
                           width:100%;font-weight:600;">
                View KPIs
            </button>
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
function filterByVendor() { runFilters(); }
function filterByArea()   { runFilters(); }
function filterByCluster(){ runFilters(); }

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

// Close modal on backdrop click
window.onclick = e => {
    if (e.target === document.getElementById('kpi-modal')) closeKPIModal();
};
