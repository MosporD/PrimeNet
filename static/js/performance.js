/**
 * Performance Analytics v2
 * Left filter panel + stacked KPI charts on the right
 */

// All Chart.js instances keyed by KPI key
const charts = {};
let allCells  = [];
let allSites  = [];
let activeCellId = null;

// ============================================================
// KPI definitions — update labels/thresholds when vendor
// column mappings are confirmed. good/warn thresholds:
// inverse=false → higher is better
// inverse=true  → lower is better
// ============================================================
const KPI_DEFS = [
    { key: 'availability_percent',  label: 'Cell Availability',          unit: '%',    good: 99,   warn: 95,   inverse: false, color: '#27ae60' },
    { key: 'rrc_success_rate',      label: 'RRC Setup Success Rate',      unit: '%',    good: 98,   warn: 95,   inverse: false, color: '#3498db' },
    { key: 'erab_success_rate',     label: 'ERAB Setup Success Rate',     unit: '%',    good: 98,   warn: 95,   inverse: false, color: '#2980b9' },
    { key: 'call_drop_rate',        label: 'Call Drop Rate',              unit: '%',    good: 0.5,  warn: 2,    inverse: true,  color: '#e74c3c' },
    { key: 'handover_success_rate', label: 'Handover Success Rate',       unit: '%',    good: 98,   warn: 95,   inverse: false, color: '#1abc9c' },
    { key: 'throughput_dl_mbps',    label: 'DL Throughput',               unit: 'Mbps', good: 50,   warn: 20,   inverse: false, color: '#9b59b6' },
    { key: 'throughput_ul_mbps',    label: 'UL Throughput',               unit: 'Mbps', good: 20,   warn: 5,    inverse: false, color: '#8e44ad' },
    { key: 'rsrp',                  label: 'RSRP',                        unit: 'dBm',  good: -80,  warn: -100, inverse: false, color: '#f39c12' },
    { key: 'rsrq',                  label: 'RSRQ',                        unit: 'dB',   good: -10,  warn: -15,  inverse: false, color: '#e67e22' },
    { key: 'sinr',                  label: 'SINR',                        unit: 'dB',   good: 15,   warn: 5,    inverse: false, color: '#d35400' },
    { key: 'avg_users',             label: 'Average Users',               unit: '',     good: null, warn: null, inverse: false, color: '#34495e' },
    { key: 'data_volume_gb',        label: 'Data Volume',                 unit: 'GB',   good: null, warn: null, inverse: false, color: '#7f8c8d' },
];

function kpiClass(value, def) {
    if (value === null || value === undefined || def.good === null) return '';
    if (!def.inverse) return value >= def.good ? 'good' : value >= def.warn ? 'warn' : 'bad';
    return value <= def.good ? 'good' : value <= def.warn ? 'warn' : 'bad';
}

function fmt(value, unit, decimals = 2) {
    if (value === null || value === undefined) return 'N/A';
    return Number(value).toFixed(decimals) + (unit ? ' ' + unit : '');
}

// ============================================================
// Filter dropdowns
// ============================================================
async function loadFilters() {
    const res  = await fetch('/api/performance/filters');
    const data = await res.json();
    if (!data.success) return;

    allSites = data.sites;

    const regionSel = document.getElementById('filter-region');
    data.regions.forEach(r => {
        const o = document.createElement('option');
        o.value = r; o.textContent = r;
        regionSel.appendChild(o);
    });

    _populateSites(allSites);
}

function _populateSites(sites) {
    const siteSel = document.getElementById('filter-site');
    const prev = siteSel.value;
    siteSel.innerHTML = '<option value="">All Sites</option>';
    sites.forEach(s => {
        const o = document.createElement('option');
        o.value = s.site_id;
        o.textContent = s.site_name;
        o.dataset.region = s.region || '';
        siteSel.appendChild(o);
    });
    if (prev) siteSel.value = prev;
}

function onVendorChange() {
    // When Huawei is selected, hide 5G option
    const vendor = document.getElementById('filter-vendor').value;
    const techSel = document.getElementById('filter-tech');
    const opt5g = techSel.querySelector('option[value="5G"]');
    if (opt5g) opt5g.style.display = vendor === 'Huawei' ? 'none' : '';
    if (vendor === 'Huawei' && techSel.value === '5G') techSel.value = '';
}

function onRegionChange() {
    const region = document.getElementById('filter-region').value;
    const filtered = region ? allSites.filter(s => s.region === region) : allSites;
    _populateSites(filtered);
    document.getElementById('filter-site').value = '';
    document.getElementById('filter-cell').innerHTML = '<option value="">All Cells</option>';
}

async function onSiteChange() {
    const siteId = document.getElementById('filter-site').value;
    const cellSel = document.getElementById('filter-cell');
    cellSel.innerHTML = '<option value="">All Cells</option>';
    if (!siteId) return;

    const tech = document.getElementById('filter-tech').value;
    const params = new URLSearchParams({ site_id: siteId });
    if (tech) params.set('technology', tech);

    const res  = await fetch('/api/performance/cells?' + params);
    const data = await res.json();
    if (!data.success) return;

    data.cells.forEach(c => {
        const o = document.createElement('option');
        o.value = c.cell_id;
        o.textContent = `${c.cell_name} (${c.technology || 'N/A'})`;
        cellSel.appendChild(o);
    });
}

// ============================================================
// Apply filters — loads cell list and shows cell chips
// ============================================================
async function applyFilters() {
    const tech   = document.getElementById('filter-tech').value;
    const region = document.getElementById('filter-region').value;
    const site   = document.getElementById('filter-site').value;
    const cell   = document.getElementById('filter-cell').value;

    const params = new URLSearchParams();
    if (tech)   params.set('technology', tech);
    if (region) params.set('region', region);
    if (site)   params.set('site_id', site);

    const res  = await fetch('/api/performance/cells?' + params);
    const data = await res.json();
    if (!data.success) return;

    allCells = data.cells;
    updateSummary(allCells);

    // If a specific cell is selected in dropdown, load it directly
    if (cell) {
        loadCellCharts(cell);
        return;
    }

    // Otherwise show cell chips to pick from
    showCellPicker(allCells);
}

function showCellPicker(cells) {
    document.getElementById('charts-wrap').style.display   = 'none';
    document.getElementById('loading-charts').style.display = 'none';
    document.getElementById('no-selection').style.display  = 'flex';

    document.getElementById('charts-title').textContent = 'Select a cell';
    document.getElementById('charts-subtitle').textContent = `${cells.length} cell${cells.length !== 1 ? 's' : ''} found`;

    const wrap = document.getElementById('cell-list-wrap');
    const list = document.getElementById('cell-list');
    list.innerHTML = '';

    if (!cells.length) {
        wrap.style.display = 'none';
        return;
    }

    wrap.style.display = 'block';
    cells.forEach(c => {
        const chip = document.createElement('div');
        chip.className = `cell-chip tech-${c.technology || ''}${c.cell_id === activeCellId ? ' active' : ''}`;
        chip.textContent = c.cell_name;
        chip.title = `${c.site_name} · ${c.technology || ''} ${c.frequency_band || ''}`;
        chip.onclick = () => loadCellCharts(c.cell_id);
        list.appendChild(chip);
    });
}

// ============================================================
// Load charts for a selected cell
// ============================================================
async function loadCellCharts(cellId) {
    activeCellId = cellId;

    // Update chip highlights
    document.querySelectorAll('.cell-chip').forEach(c => {
        c.classList.toggle('active', c.onclick.toString().includes(cellId));
    });

    document.getElementById('no-selection').style.display   = 'none';
    document.getElementById('charts-wrap').style.display    = 'none';
    document.getElementById('loading-charts').style.display = 'flex';

    const hours = document.getElementById('filter-hours').value;

    try {
        const res  = await fetch(`/api/performance/cell/${cellId}/trend?hours=${hours}`);
        const data = await res.json();
        if (!data.success) throw new Error(data.error);

        const cell  = data.cell;
        const trend = data.trend;

        document.getElementById('charts-title').textContent =
            `${cell.cell_name}`;
        document.getElementById('charts-subtitle').textContent =
            `${cell.site_name} · ${cell.technology || ''} ${cell.frequency_band || ''} · ${trend.length} data points`;

        // Update map link
        document.getElementById('map-link').href =
            `/network-map`;

        renderAllCharts(trend);

    } catch (e) {
        document.getElementById('loading-charts').style.display = 'none';
        document.getElementById('no-selection').style.display   = 'flex';
        document.getElementById('charts-title').textContent = 'Error loading data';
        document.getElementById('charts-subtitle').textContent  = e.message;
    }
}

// ============================================================
// Render one chart card per KPI, stacked vertically
// ============================================================
function renderAllCharts(trend) {
    // Destroy old charts
    Object.values(charts).forEach(c => c.destroy());
    Object.keys(charts).forEach(k => delete charts[k]);

    const wrap = document.getElementById('charts-wrap');
    wrap.innerHTML = '';

    const labels = trend.map(r => {
        const d = new Date(r.timestamp);
        return d.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ' ' +
               d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    });

    KPI_DEFS.forEach(def => {
        const values = trend.map(r => r[def.key]);
        const lastVal = [...values].reverse().find(v => v !== null && v !== undefined);

        // Card
        const card = document.createElement('div');
        card.className = 'kpi-chart-card';

        const cls = lastVal !== undefined ? kpiClass(lastVal, def) : '';
        const displayVal = lastVal !== undefined ? fmt(lastVal, def.unit) : 'N/A';

        card.innerHTML = `
            <div class="kpi-chart-title">
                <span class="kpi-chart-name">${def.label}</span>
                <span class="kpi-chart-value ${cls}">${displayVal}</span>
            </div>
            <div class="kpi-chart-canvas-wrap">
                <canvas id="chart-${def.key}"></canvas>
            </div>
        `;
        wrap.appendChild(card);

        // Point colors based on threshold
        const pointColors = values.map(v => {
            if (v === null || v === undefined) return '#bdc3c7';
            const c = kpiClass(v, def);
            return c === 'good' ? '#27ae60' : c === 'warn' ? '#f39c12' : c === 'bad' ? '#e74c3c' : def.color;
        });

        const ctx = document.getElementById(`chart-${def.key}`).getContext('2d');
        charts[def.key] = new Chart(ctx, {
            type: 'line',
            data: {
                labels,
                datasets: [{
                    label: def.label,
                    data: values,
                    borderColor: def.color,
                    backgroundColor: def.color + '18',
                    pointBackgroundColor: pointColors,
                    pointRadius: trend.length > 48 ? 2 : 3,
                    pointHoverRadius: 5,
                    borderWidth: 2,
                    tension: 0.3,
                    fill: true,
                    spanGaps: true,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: ctx => {
                                const v = ctx.parsed.y;
                                return v !== null ? `${def.label}: ${Number(v).toFixed(2)}${def.unit ? ' ' + def.unit : ''}` : 'N/A';
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        ticks: { maxTicksLimit: 8, font: { size: 10 }, maxRotation: 0 },
                        grid: { color: '#f5f6fa' }
                    },
                    y: {
                        ticks: { font: { size: 10 } },
                        grid: { color: '#f5f6fa' }
                    }
                }
            }
        });
    });

    document.getElementById('loading-charts').style.display = 'none';
    wrap.style.display = 'flex';
}

// ============================================================
// Side summary stats
// ============================================================
function updateSummary(cells) {
    const avg = key => {
        const vals = cells.map(c => c[key]).filter(v => v !== null && v !== undefined);
        return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
    };
    document.getElementById('sum-cells').textContent = cells.length;
    const avail = avg('availability_percent');
    document.getElementById('sum-availability').textContent = avail !== null ? avail.toFixed(1) + '%' : 'N/A';
    const drop = avg('call_drop_rate');
    document.getElementById('sum-drop').textContent = drop !== null ? drop.toFixed(2) + '%' : 'N/A';
    const dl = avg('throughput_dl_mbps');
    document.getElementById('sum-dl').textContent = dl !== null ? dl.toFixed(1) + ' Mbps' : 'N/A';
}
