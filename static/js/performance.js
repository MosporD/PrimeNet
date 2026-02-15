/**
 * Performance Analytics
 * Cell KPI table + Chart.js trend panel
 */

let allCells = [];
let trendChart = null;
let selectedCellId = null;

// KPI display config: label, good/warn/bad thresholds, inverse flag
const KPI_CONFIG = {
    availability_percent:   { label: 'Avail %',    good: 99,   warn: 95,  inverse: false },
    rrc_success_rate:       { label: 'RRC %',      good: 98,   warn: 95,  inverse: false },
    erab_success_rate:      { label: 'ERAB %',     good: 98,   warn: 95,  inverse: false },
    call_drop_rate:         { label: 'Drop %',     good: 0.5,  warn: 2,   inverse: true  },
    handover_success_rate:  { label: 'HO %',       good: 98,   warn: 95,  inverse: false },
    throughput_dl_mbps:     { label: 'DL Mbps',    good: 50,   warn: 20,  inverse: false },
    throughput_ul_mbps:     { label: 'UL Mbps',    good: 20,   warn: 5,   inverse: false },
    rsrp:                   { label: 'RSRP',       good: -80,  warn: -100, inverse: false },
    rsrq:                   { label: 'RSRQ',       good: -10,  warn: -15,  inverse: false },
    sinr:                   { label: 'SINR',       good: 15,   warn: 5,   inverse: false },
    avg_users:              { label: 'Users',      good: null, warn: null, inverse: false },
    data_volume_gb:         { label: 'Data GB',    good: null, warn: null, inverse: false },
};

function kpiClass(value, kpiKey) {
    const cfg = KPI_CONFIG[kpiKey];
    if (!cfg || value === null || value === undefined) return 'kpi-na';
    if (cfg.good === null) return '';
    if (!cfg.inverse) {
        return value >= cfg.good ? 'kpi-good' : value >= cfg.warn ? 'kpi-warn' : 'kpi-bad';
    } else {
        return value <= cfg.good ? 'kpi-good' : value <= cfg.warn ? 'kpi-warn' : 'kpi-bad';
    }
}

function fmt(value, decimals = 1, suffix = '') {
    if (value === null || value === undefined) return '<span class="kpi-na">N/A</span>';
    return Number(value).toFixed(decimals) + suffix;
}

// ---------------------------------------------------------------------------
// Load filter dropdowns
// ---------------------------------------------------------------------------
async function loadFilters() {
    const res = await fetch('/api/performance/filters');
    const data = await res.json();
    if (!data.success) return;

    const regionSel = document.getElementById('filter-region');
    data.regions.forEach(r => {
        const o = document.createElement('option');
        o.value = r; o.textContent = r;
        regionSel.appendChild(o);
    });

    const siteSel = document.getElementById('filter-site');
    data.sites.forEach(s => {
        const o = document.createElement('option');
        o.value = s.site_id;
        o.textContent = s.site_name;
        o.dataset.region = s.region || '';
        siteSel.appendChild(o);
    });

    // Filter site dropdown when region changes
    document.getElementById('filter-region').addEventListener('change', () => {
        const region = document.getElementById('filter-region').value;
        document.querySelectorAll('#filter-site option').forEach(o => {
            if (!o.value) { o.style.display = ''; return; }
            o.style.display = (!region || o.dataset.region === region) ? '' : 'none';
        });
        document.getElementById('filter-site').value = '';
    });
}

// ---------------------------------------------------------------------------
// Apply filters and reload cell table
// ---------------------------------------------------------------------------
async function applyFilters() {
    const tech   = document.getElementById('filter-tech').value;
    const region = document.getElementById('filter-region').value;
    const site   = document.getElementById('filter-site').value;

    document.getElementById('loading-indicator').style.display = 'block';
    document.getElementById('cell-tbody').innerHTML = '';

    const params = new URLSearchParams();
    if (tech)   params.set('technology', tech);
    if (region) params.set('region', region);
    if (site)   params.set('site_id', site);

    try {
        const res  = await fetch('/api/performance/cells?' + params);
        const data = await res.json();
        if (!data.success) throw new Error(data.error);
        allCells = data.cells;
        renderTable(allCells);
        renderSummary(allCells);
    } catch (e) {
        document.getElementById('cell-tbody').innerHTML =
            `<tr><td colspan="11" class="no-data">Error loading data: ${e.message}</td></tr>`;
    } finally {
        document.getElementById('loading-indicator').style.display = 'none';
    }
}

// ---------------------------------------------------------------------------
// Render cell table
// ---------------------------------------------------------------------------
function renderTable(cells) {
    const tbody = document.getElementById('cell-tbody');
    document.getElementById('cell-count-label').textContent = `${cells.length} cells`;

    if (!cells.length) {
        tbody.innerHTML = '<tr><td colspan="11" class="no-data">No cells found for the selected filters.</td></tr>';
        return;
    }

    tbody.innerHTML = cells.map(c => {
        const techClass = `tech-${c.technology || ''}`;
        const ts = c.timestamp ? new Date(c.timestamp).toLocaleString() : 'N/A';
        return `
        <tr onclick="openTrend('${c.cell_id}')" id="row-${c.cell_id}"
            class="${c.cell_id === selectedCellId ? 'selected' : ''}">
            <td><strong>${c.cell_name}</strong></td>
            <td>${c.site_name}</td>
            <td><span class="tech-badge ${techClass}">${c.technology || 'N/A'}</span></td>
            <td>${c.frequency_band || 'N/A'}</td>
            <td class="${kpiClass(c.availability_percent, 'availability_percent')}">${fmt(c.availability_percent, 2, '%')}</td>
            <td class="${kpiClass(c.rrc_success_rate, 'rrc_success_rate')}">${fmt(c.rrc_success_rate, 2, '%')}</td>
            <td class="${kpiClass(c.call_drop_rate, 'call_drop_rate')}">${fmt(c.call_drop_rate, 2, '%')}</td>
            <td>${fmt(c.throughput_dl_mbps, 1, ' Mbps')}</td>
            <td class="${kpiClass(c.rsrp, 'rsrp')}">${fmt(c.rsrp, 1, ' dBm')}</td>
            <td>${c.avg_users !== null && c.avg_users !== undefined ? Math.round(c.avg_users) : '<span class="kpi-na">N/A</span>'}</td>
            <td style="color:#95a5a6;font-size:0.85em;">${ts}</td>
        </tr>`;
    }).join('');
}

// ---------------------------------------------------------------------------
// Render summary cards
// ---------------------------------------------------------------------------
function renderSummary(cells) {
    const withKpi = cells.filter(c => c.availability_percent !== null);
    const avg = (key) => {
        const vals = cells.map(c => c[key]).filter(v => v !== null && v !== undefined);
        return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
    };

    document.getElementById('sum-cells').textContent = cells.length;
    document.getElementById('sum-availability').textContent =
        avg('availability_percent') !== null ? avg('availability_percent').toFixed(1) + '%' : 'N/A';
    document.getElementById('sum-rrc').textContent =
        avg('rrc_success_rate') !== null ? avg('rrc_success_rate').toFixed(1) + '%' : 'N/A';
    document.getElementById('sum-drop').textContent =
        avg('call_drop_rate') !== null ? avg('call_drop_rate').toFixed(2) + '%' : 'N/A';
    document.getElementById('sum-dl').textContent =
        avg('throughput_dl_mbps') !== null ? avg('throughput_dl_mbps').toFixed(1) + ' Mbps' : 'N/A';
    document.getElementById('sum-users').textContent =
        avg('avg_users') !== null ? Math.round(avg('avg_users')) : 'N/A';
}

// ---------------------------------------------------------------------------
// Open trend panel for a cell
// ---------------------------------------------------------------------------
async function openTrend(cellId) {
    selectedCellId = cellId;

    // Highlight row
    document.querySelectorAll('#cell-table tbody tr').forEach(r => r.classList.remove('selected'));
    const row = document.getElementById(`row-${cellId}`);
    if (row) { row.classList.add('selected'); row.scrollIntoView({ block: 'nearest' }); }

    const panel = document.getElementById('trend-panel');
    panel.style.display = 'block';
    document.getElementById('no-trend-data').style.display = 'none';
    document.getElementById('trend-title').textContent = 'Loading...';
    document.getElementById('trend-subtitle').textContent = '';

    const hours = document.getElementById('filter-hours').value;
    const res  = await fetch(`/api/performance/cell/${cellId}/trend?hours=${hours}`);
    const data = await res.json();

    if (!data.success) return;

    const cell = data.cell;
    document.getElementById('trend-title').textContent = cell.cell_name;
    document.getElementById('trend-subtitle').textContent =
        `${cell.site_name} · ${cell.technology || ''} ${cell.frequency_band || ''}`;

    // Map link back to network map filtered by site
    const mapLink = document.getElementById('map-link');
    mapLink.href = `/network-map`;
    mapLink.style.display = 'block';

    if (!data.trend.length) {
        document.getElementById('no-trend-data').style.display = 'block';
        if (trendChart) { trendChart.destroy(); trendChart = null; }
        return;
    }

    window._trendData = data.trend;
    renderChart();
}

// ---------------------------------------------------------------------------
// Render Chart.js line chart
// ---------------------------------------------------------------------------
function renderChart() {
    const trend = window._trendData;
    if (!trend || !trend.length) return;

    const kpiKey = document.getElementById('trend-kpi-select').value;
    const cfg    = KPI_CONFIG[kpiKey] || { label: kpiKey };

    const labels = trend.map(r => {
        const d = new Date(r.timestamp);
        return d.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ' ' +
               d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    });
    const values = trend.map(r => r[kpiKey]);

    // Color points by threshold
    const pointColors = values.map(v => {
        if (v === null) return '#bdc3c7';
        const cls = kpiClass(v, kpiKey);
        return cls === 'kpi-good' ? '#27ae60' : cls === 'kpi-warn' ? '#f39c12' : cls === 'kpi-bad' ? '#e74c3c' : '#3498db';
    });

    const ctx = document.getElementById('trend-chart').getContext('2d');
    if (trendChart) trendChart.destroy();

    trendChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels,
            datasets: [{
                label: cfg.label || kpiKey,
                data: values,
                borderColor: '#3498db',
                backgroundColor: 'rgba(52,152,219,0.08)',
                pointBackgroundColor: pointColors,
                pointRadius: 3,
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
                            return v !== null ? `${cfg.label || kpiKey}: ${Number(v).toFixed(2)}` : 'N/A';
                        }
                    }
                }
            },
            scales: {
                x: {
                    ticks: { maxTicksLimit: 8, font: { size: 10 }, maxRotation: 30 },
                    grid: { color: '#f0f0f0' }
                },
                y: {
                    ticks: { font: { size: 11 } },
                    grid: { color: '#f0f0f0' }
                }
            }
        }
    });
}

function closeTrendPanel() {
    document.getElementById('trend-panel').style.display = 'none';
    selectedCellId = null;
    document.querySelectorAll('#cell-table tbody tr').forEach(r => r.classList.remove('selected'));
    if (trendChart) { trendChart.destroy(); trendChart = null; }
}
