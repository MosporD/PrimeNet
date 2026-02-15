/**
 * Performance Analytics v2
 * Left filter panel + stacked KPI charts on the right
 */

// All Chart.js instances keyed by KPI key
const charts = {};
let allCells     = [];
let allSites     = [];
let activeCellId = null;

// KPI definitions — populated dynamically from /api/performance/kpi_columns
// Colors are assigned deterministically from the column name.
let KPI_DEFS = [];

const _CHART_COLORS = [
    '#3498db','#27ae60','#e74c3c','#9b59b6','#f39c12',
    '#1abc9c','#e67e22','#2980b9','#8e44ad','#d35400',
    '#34495e','#7f8c8d','#16a085','#c0392b','#2ecc71',
];

function _colorFor(col) {
    let h = 0;
    for (let i = 0; i < col.length; i++) h = (h + col.charCodeAt(i)) % _CHART_COLORS.length;
    return _CHART_COLORS[h];
}

async function loadKpiColumns() {
    try {
        const res  = await fetch('/api/performance/kpi_columns');
        const data = await res.json();
        if (!data.success) return;
        const all = [...new Set([...data.nokia, ...data.huawei])];
        KPI_DEFS = all.map(col => ({
            key:     col,
            label:   col,
            unit:    '',
            good:    null,
            warn:    null,
            inverse: false,
            color:   _colorFor(col),
        }));
    } catch (e) {
        console.warn('Could not load KPI columns:', e);
    }
}

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
    await loadKpiColumns();

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
    // Reload KPI column list for the selected vendor
    loadKpiColumns();
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

    // If KPI_DEFS haven't loaded yet, build them from the trend row keys directly
    let defs = KPI_DEFS;
    if (!defs.length && trend.length) {
        const skip = new Set(['id', 'cell_name', 'timestamp']);
        defs = Object.keys(trend[0])
            .filter(k => !skip.has(k))
            .map(col => ({ key: col, label: col, unit: '', good: null, warn: null, inverse: false, color: _colorFor(col) }));
    }

    if (!defs.length) {
        wrap.innerHTML = '<p style="padding:1rem;color:#888">No KPI data available yet.</p>';
        document.getElementById('loading-charts').style.display = 'none';
        wrap.style.display = 'flex';
        return;
    }

    const labels = trend.map(r => {
        const d = new Date(r.timestamp);
        return d.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ' ' +
               d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    });

    defs.forEach(def => {
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

    // Try to find availability/drop/throughput columns by partial name match
    const findCol = (...keywords) => {
        const keys = cells.length ? Object.keys(cells[0]) : [];
        return keys.find(k => keywords.some(kw => k.toLowerCase().includes(kw.toLowerCase())));
    };

    const availCol = findCol('avail');
    const dropCol  = findCol('drop');
    const dlCol    = findCol('thp dl', 'throughput dl', 'thp DL', 'DL thp', 'dl_mbps', 'DL (Mbps)', 'PDSCH');

    const availEl = document.getElementById('sum-availability');
    const dropEl  = document.getElementById('sum-drop');
    const dlEl    = document.getElementById('sum-dl');

    if (availEl) { const v = availCol ? avg(availCol) : null; availEl.textContent = v !== null ? v.toFixed(1) + '%' : 'N/A'; }
    if (dropEl)  { const v = dropCol  ? avg(dropCol)  : null; dropEl.textContent  = v !== null ? v.toFixed(2) + '%' : 'N/A'; }
    if (dlEl)    { const v = dlCol    ? avg(dlCol)    : null; dlEl.textContent    = v !== null ? v.toFixed(1) + ' Mbps' : 'N/A'; }
}
