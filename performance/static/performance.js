/**
 * Performance Analytics v4
 * - Cluster / Area derived from site_id (matching network map logic)
 * - Cell search in left panel (always visible after Apply)
 * - 2 charts per row from live KPI DB headers
 * - CSV export of tabular trend data
 */

const charts = {};
let allCells    = [];
let allSites    = [];
let allClusters = [];
let allAreas    = [];   // [{cluster, area}]
let activeCellId = null;
let lastTrendData = null;  // {cell, trend} kept for export

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

// ============================================================
// KPI columns
// ============================================================

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

    allSites    = data.sites;
    allClusters = data.clusters || [];
    allAreas    = data.areas    || [];

    // Clusters (numeric)
    _populateClusters(allClusters);
    _populateAreas(allAreas);
    _populateSites(allSites);
}

function _populateClusters(clusters) {
    const sel = document.getElementById('filter-cluster');
    const prev = sel.value;
    sel.innerHTML = '<option value="">All Clusters</option>';
    clusters.forEach(c => {
        const o = document.createElement('option');
        o.value = String(c); o.textContent = 'Cluster ' + c;
        sel.appendChild(o);
    });
    if (prev) sel.value = prev;
}

function _populateAreas(areas) {
    const sel = document.getElementById('filter-area');
    const prev = sel.value;
    sel.innerHTML = '<option value="">All Areas</option>';
    const seen = new Set();
    areas.forEach(a => {
        if (seen.has(a.area)) return;
        seen.add(a.area);
        const o = document.createElement('option');
        o.value = a.area; o.textContent = a.area;
        sel.appendChild(o);
    });
    if (prev) sel.value = prev;
}

function _populateSites(sites) {
    const siteSel = document.getElementById('filter-site');
    const prev = siteSel.value;
    siteSel.innerHTML = '<option value="">All Sites</option>';
    sites.forEach(s => {
        const o = document.createElement('option');
        o.value = s.site_id;
        o.textContent = s.site_name;
        o.dataset.cluster = s.cluster != null ? String(s.cluster) : '';
        o.dataset.area    = s.area    || '';
        siteSel.appendChild(o);
    });
    if (prev) siteSel.value = prev;
}

function onVendorChange() {
    const vendor  = document.getElementById('filter-vendor').value;
    const techSel = document.getElementById('filter-tech');
    const opt5g   = techSel.querySelector('option[value="5G"]');
    if (opt5g) opt5g.style.display = vendor === 'Huawei' ? 'none' : '';
    if (vendor === 'Huawei' && techSel.value === '5G') techSel.value = '';
    loadKpiColumns();
}

function onClusterChange() {
    const cluster = document.getElementById('filter-cluster').value;

    // Filter area options to match selected cluster
    const filteredAreas = cluster
        ? allAreas.filter(a => String(a.cluster) === cluster)
        : allAreas;
    _populateAreas(filteredAreas);
    document.getElementById('filter-area').value = '';
    _applyGeoFilters(cluster, '');
}

function onAreaChange() {
    const cluster = document.getElementById('filter-cluster').value;
    const area    = document.getElementById('filter-area').value;
    _applyGeoFilters(cluster, area);
}

function _applyGeoFilters(cluster, area) {
    let filtered = allSites;
    if (cluster) filtered = filtered.filter(s => String(s.cluster) === cluster);
    if (area)    filtered = filtered.filter(s => s.area === area);
    _populateSites(filtered);
    document.getElementById('filter-site').value = '';
    document.getElementById('filter-cell').innerHTML = '<option value="">All Cells</option>';
}

async function onSiteChange() {
    const siteId = document.getElementById('filter-site').value;
    const cellSel = document.getElementById('filter-cell');
    cellSel.innerHTML = '<option value="">All Cells</option>';
    if (!siteId) return;

    const tech   = document.getElementById('filter-tech').value;
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
// Apply filters — load cell list into left-panel search
// ============================================================

async function applyFilters() {
    const vendor  = document.getElementById('filter-vendor').value;
    const tech    = document.getElementById('filter-tech').value;
    const cluster = document.getElementById('filter-cluster').value;
    const area    = document.getElementById('filter-area').value;
    const site    = document.getElementById('filter-site').value;
    const cell    = document.getElementById('filter-cell').value;

    const params = new URLSearchParams();
    if (vendor)  params.set('vendor',     vendor);
    if (tech)    params.set('technology', tech);
    if (cluster) params.set('cluster',    cluster);
    if (area)    params.set('area',       area);
    if (site)    params.set('site_id',    site);

    const res  = await fetch('/api/performance/cells?' + params);
    const data = await res.json();
    if (!data.success) return;

    allCells = data.cells;
    updateSummary(allCells);

    if (cell) {
        loadCellCharts(cell);
        return;
    }

    // Populate the cell chip list in the left panel
    showCellPicker(allCells);
}

// ============================================================
// Cell picker — shown in left panel after Apply
// ============================================================

function showCellPicker(cells) {
    document.getElementById('btn-refresh').style.display = 'inline-flex';

    document.getElementById('charts-title').textContent =
        cells.length ? 'Select a cell' : 'No cells found';
    document.getElementById('charts-subtitle').textContent =
        `${cells.length} cell${cells.length !== 1 ? 's' : ''} found`;

    const wrap = document.getElementById('cell-list-wrap');
    const list = document.getElementById('cell-list');
    list.innerHTML = '';

    if (!cells.length) {
        wrap.style.display = 'none';
        return;
    }

    // Clear search bar
    const searchInput = document.getElementById('cell-search');
    if (searchInput) searchInput.value = '';
    _updateCellCountBadge(cells.length, cells.length);

    wrap.style.display = 'block';

    cells.forEach(c => {
        const chip = document.createElement('div');
        chip.className = `cell-chip tech-${c.technology || ''}${c.cell_id === activeCellId ? ' active' : ''}`;
        chip.textContent = c.cell_name;
        const clusterArea = [c.cluster ? 'Cluster ' + c.cluster : '', c.area || ''].filter(Boolean).join(' / ');
        chip.title = [
            c.site_name,
            c.technology || '',
            c.frequency_band || '',
            clusterArea
        ].filter(Boolean).join(' · ');
        chip.dataset.search = (c.cell_name + ' ' + c.site_name + ' ' + (c.cluster || '') + ' ' + (c.area || '')).toLowerCase();
        chip.onclick = () => loadCellCharts(c.cell_id);
        list.appendChild(chip);
    });
}

function filterCellChips(query) {
    const q = query.toLowerCase().trim();
    const chips = document.querySelectorAll('#cell-list .cell-chip');
    let visible = 0;
    chips.forEach(chip => {
        const match = !q || chip.dataset.search.includes(q);
        chip.style.display = match ? '' : 'none';
        if (match) visible++;
    });
    _updateCellCountBadge(visible, chips.length);
}

function _updateCellCountBadge(visible, total) {
    const badge = document.getElementById('cell-count-badge');
    if (!badge) return;
    badge.textContent = visible === total
        ? `${total} cells`
        : `${visible} / ${total} cells`;
}

// ============================================================
// Load charts for a selected cell
// ============================================================

async function loadCellCharts(cellId) {
    activeCellId = cellId;

    document.querySelectorAll('.cell-chip').forEach(c => {
        const match = c.onclick && c.onclick.toString().includes(String(cellId));
        c.classList.toggle('active', match);
    });

    document.getElementById('no-selection').style.display   = 'none';
    document.getElementById('charts-wrap').style.display    = 'none';
    document.getElementById('loading-charts').style.display = 'flex';
    document.getElementById('btn-export').style.display     = 'none';
    document.getElementById('btn-refresh').style.display    = 'inline-flex';

    const hours = document.getElementById('filter-hours').value;

    try {
        const res  = await fetch(`/api/performance/cell/${cellId}/trend?hours=${hours}`);
        const data = await res.json();
        if (!data.success) throw new Error(data.error);

        const cell  = data.cell;
        const trend = data.trend;
        lastTrendData = data;

        // Build subtitle with cluster / area
        const parts = [cell.site_name, cell.technology || '', cell.frequency_band || ''];
        if (cell.cluster) parts.push('Cluster: ' + cell.cluster);
        if (cell.area)    parts.push('Area: '    + cell.area);
        parts.push(trend.length + ' data points');

        document.getElementById('charts-title').textContent    = cell.cell_name;
        document.getElementById('charts-subtitle').textContent = parts.filter(Boolean).join('  ·  ');

        renderAllCharts(trend);

        // Show export button only when we have trend data
        if (trend.length) {
            document.getElementById('btn-export').style.display = 'inline-flex';
        }

    } catch (e) {
        document.getElementById('loading-charts').style.display = 'none';
        document.getElementById('no-selection').style.display   = 'flex';
        document.getElementById('charts-title').textContent     = 'Error loading data';
        document.getElementById('charts-subtitle').textContent  = e.message;
    }
}

// ============================================================
// Render charts — 2 per row
// ============================================================

function renderAllCharts(trend) {
    Object.values(charts).forEach(c => c.destroy());
    Object.keys(charts).forEach(k => delete charts[k]);

    const wrap = document.getElementById('charts-wrap');
    wrap.innerHTML = '';

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
        wrap.style.display = 'grid';
        return;
    }

    const labels = trend.map(r => {
        const d = new Date(r.timestamp);
        return d.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ' ' +
               d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    });

    defs.forEach(def => {
        const values   = trend.map(r => r[def.key]);
        const lastVal  = [...values].reverse().find(v => v !== null && v !== undefined);
        const cls      = lastVal !== undefined ? kpiClass(lastVal, def) : '';
        const dispVal  = lastVal !== undefined ? fmt(lastVal, def.unit) : 'N/A';

        const card = document.createElement('div');
        card.className = 'kpi-chart-card';
        card.innerHTML = `
            <div class="kpi-chart-title">
                <span class="kpi-chart-name">${def.label}</span>
                <span class="kpi-chart-value ${cls}">${dispVal}</span>
            </div>
            <div class="kpi-chart-canvas-wrap">
                <canvas id="chart-${def.key}"></canvas>
            </div>
        `;
        wrap.appendChild(card);

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
                                return v !== null
                                    ? `${def.label}: ${Number(v).toFixed(2)}${def.unit ? ' ' + def.unit : ''}`
                                    : 'N/A';
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
    wrap.style.display = 'grid';
}

// ============================================================
// Refresh
// ============================================================

async function refreshData() {
    const btn = document.getElementById('btn-refresh');
    if (btn) {
        btn.disabled = true;
        btn.querySelector('.refresh-icon').classList.add('spinning');
    }
    try {
        if (activeCellId) {
            await loadCellCharts(activeCellId);
        } else {
            await applyFilters();
        }
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.querySelector('.refresh-icon').classList.remove('spinning');
        }
    }
}

// ============================================================
// CSV Export
// ============================================================

function exportCSV() {
    if (!lastTrendData || !lastTrendData.trend || !lastTrendData.trend.length) return;

    const { cell, trend } = lastTrendData;

    // Columns: all keys from first row
    const skip = new Set(['id']);
    const cols = Object.keys(trend[0]).filter(k => !skip.has(k));

    const escape = v => {
        if (v === null || v === undefined) return '';
        const s = String(v);
        return s.includes(',') || s.includes('"') || s.includes('\n')
            ? `"${s.replace(/"/g, '""')}"` : s;
    };

    const lines = [];

    // Header comment rows
    lines.push(`# Cell: ${cell.cell_name}`);
    lines.push(`# Site: ${cell.site_name}  |  Vendor: ${cell.vendor}  |  Technology: ${cell.technology || ''}`);
    if (cell.cluster || cell.area)
        lines.push(`# Cluster: ${cell.cluster || ''}  |  Area: ${cell.area || ''}`);
    lines.push(`# Exported: ${new Date().toISOString()}`);
    lines.push('');

    // Column headers
    lines.push(cols.map(escape).join(','));

    // Data rows
    trend.forEach(row => {
        lines.push(cols.map(c => escape(row[c])).join(','));
    });

    const blob = new Blob([lines.join('\r\n')], { type: 'text/csv;charset=utf-8;' });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href     = url;
    a.download = `${cell.cell_name}_kpi_trend.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
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
