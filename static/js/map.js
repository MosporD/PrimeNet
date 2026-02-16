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

// ─── State ───────────────────────────────────────────────────────────────────

let map          = null;
let sitesData    = [];
let siteMarkers  = [];
let sectorLayers = [];
let activeTech   = 'all';

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

    let html = `<button class="tech-btn active" data-tech="all"
                        onclick="setTechFilter('all')">
                  All <span class="tech-count">${total}</span>
                </button>`;

    TECH_ORDER.forEach(tech => {
        if (!counts[tech]) return;
        const color = TECH_COLORS[tech] || '#3498db';
        html += `<button class="tech-btn" data-tech="${tech}"
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
    document.getElementById('site-info-panel').style.display = 'none';
    loadNetworkSites();
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

        sitesData = data.sites;
        displaySites(sitesData);
        document.getElementById('sites-count').textContent = sitesData.length;

        if (sitesData.length > 0) {
            map.fitBounds(
                sitesData.map(s => [s.latitude, s.longitude]),
                { padding: [50, 50] }
            );
        }

        buildRegionFilter(sitesData);
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
        <div class="site-meta-row"><strong>Region:</strong> ${site.region || '—'}</div>
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

// ─── Search & region filter ───────────────────────────────────────────────────

function buildRegionFilter(sites) {
    const select  = document.getElementById('region-filter');
    const current = select.value;
    const regions = [...new Set(sites.map(s => s.region).filter(Boolean))].sort();

    select.innerHTML = '<option value="all">All Regions</option>';
    regions.forEach(r => {
        const opt = document.createElement('option');
        opt.value = r;
        opt.textContent = `Region ${r}`;
        if (r === current) opt.selected = true;
        select.appendChild(opt);
    });
}

function searchSites() {
    const term = document.getElementById('site-search').value.toLowerCase();
    if (!term) { displaySites(sitesData); return; }

    const filtered = sitesData.filter(s =>
        s.site_name.toLowerCase().includes(term) ||
        String(s.site_id).toLowerCase().includes(term)
    );
    displaySites(filtered);

    if (filtered.length > 0)
        map.fitBounds(
            filtered.map(s => [s.latitude, s.longitude]),
            { padding: [50, 50] }
        );
}

function filterByRegion() {
    const region   = document.getElementById('region-filter').value;
    const filtered = region === 'all'
        ? sitesData
        : sitesData.filter(s => s.region === region);
    displaySites(filtered);

    if (filtered.length > 0)
        map.fitBounds(
            filtered.map(s => [s.latitude, s.longitude]),
            { padding: [50, 50] }
        );
}

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
