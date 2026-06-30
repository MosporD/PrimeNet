/**
 * Performance Analytics v5
 * - Cluster / Area derived from site_id (matching network map logic)
 * - Cell search in left panel (always visible after Apply)
 * - 2 charts per row from live KPI DB headers
 * - CSV export of tabular trend data
 */

const charts = {};
let _perfChartRenderSeq = 0;
let allCells    = [];
let allSites    = [];
let allClusters = [];
let allAreas    = [];   // [{cluster, area}]
let activeCellId = null;
let lastTrendData = null;  // {cell, trend} kept for export
let filteredSites = [];

let KPI_DEFS = [];
let perfAreaTreeData = new Map();
let KPI_HEADER_MAP = {};

/** Keys from the KPI scope list that are selected for charts / export */
let kpiSelectedKeys = new Set();
let _kpiColumnsSig = '';
let allCellGroups = [];
let lastQueryCellKeys = [];
let lastQuerySelectionType = 'cell';
let performanceReports = [];
let perfBottomMode = 'kpis';
let perfLeftPanelCollapsed = false;
let perfPreferredPmViewMode = 'charts';
let perfPmViewPrefPromise = null;
let performanceFilterPresets = [];

/** Chart view: trend, hourly day-over-day, or daily month-over-month. */
let perfChartDisplayMode = 'trend';
let perfDodSelectedDateSet = new Set();
let perfDodPickerSig = '';
let perfDodPickerNeedsReset = false;
let perfDodBarWired = false;
let perfDodDayChangeTimer = null;

// ── PM table view state ──────────────────────────────────
let hwCurrentPage   = 1;
let hwCurrentSearch = '';
let hwCurrentTech   = '';
let hwCurrentVendor = '';
let hwCurrentScopedCellNames = [];
let hwCurrentScopedGroupRefs = [];
let hwLastTablePayload = null;
let hwSearchTimer   = null;
const HW_PAGE_SIZE  = 20;

let KPI_CATEGORY_MAP = {};
let KPI_DISPLAY_NAMES = {};
let META_KPI_KEYS = new Set();
let _kpiCategoryConfigPromise = null;

const DEFAULT_KPI_CATEGORY = 'Other';
const DUPLICATE_KPI_KEYS = new Set([
    'RH303:Handover Success Rate(%)',
    'K3034:TCHH Traffic Volume(Erl)',
    'Drop Call Rate',
    'CS RAB Congestion Num',
    'TCH raw block.1',
    'Act HS-DSCH  end usr thp',
    'Expect cell size',
    'Avg PDCP cell thp UL',
    'TRS_SLOT_PDSCH (M55308C00017)',
]);
const META_KPI_KEYWORD_RE = /\b(cell|site|nodeb|enodeb|nrbts|nrcel|rnc|wbts|wcel|id|index|name|integrity|duplex|indication)\b/i;

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

function syncKpiSelectionWithDefs() {
    if (!KPI_DEFS.length) {
        _kpiColumnsSig = '';
        kpiSelectedKeys.clear();
        return;
    }
    const sig = KPI_DEFS.map(d => d.key).join('\0');
    if (sig !== _kpiColumnsSig) {
        _kpiColumnsSig = sig;
        kpiSelectedKeys.clear();
        KPI_DEFS.forEach(d => kpiSelectedKeys.add(d.key));
    }
}

function _scopeMapKey(vendor, technology) {
    return `${vendor}|${technology}`;
}

function _currentDataScope() {
    const el = document.getElementById('filter-data-scope');
    const v = String(el?.value || 'hourly').trim().toLowerCase();
    return v === 'daily' ? 'daily' : 'hourly';
}

function _normalizeKpiKey(k) {
    return String(k || '').trim();
}

function _isMetadataKpiKey(k) {
    const key = _normalizeKpiKey(k);
    if (!key) return true;
    if (DUPLICATE_KPI_KEYS.has(key)) return true;
    if (META_KPI_KEYS.has(key)) return true;
    const cat = KPI_CATEGORY_MAP[key];
    if (String(cat || '').toLowerCase() === 'identifiers / metadata') return true;
    return META_KPI_KEYWORD_RE.test(key);
}

function _kpiDisplayName(kpiKey) {
    const key = _normalizeKpiKey(kpiKey);
    return _normalizeKpiKey(KPI_DISPLAY_NAMES[key]) || key;
}

async function ensureKpiCategoryConfigLoaded() {
    if (_kpiCategoryConfigPromise) return _kpiCategoryConfigPromise;
    _kpiCategoryConfigPromise = (async () => {
        const url = window.PERF_KPI_CATEGORY_MAP_URL || '/performance/static/kpi_categories.json';
        try {
            const res = await fetch(url, { credentials: 'same-origin' });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            const cats = (data && typeof data.categories === 'object' && data.categories) ? data.categories : {};
            const disp = (data && typeof data.display_names === 'object' && data.display_names) ? data.display_names : {};
            KPI_CATEGORY_MAP = {};
            KPI_DISPLAY_NAMES = {};
            Object.keys(cats).forEach(k => {
                const key = _normalizeKpiKey(k);
                const cat = _normalizeKpiKey(cats[k]);
                if (key && cat) KPI_CATEGORY_MAP[key] = cat;
            });
            Object.keys(disp).forEach(k => {
                const key = _normalizeKpiKey(k);
                const label = _normalizeKpiKey(disp[k]);
                if (key && label) KPI_DISPLAY_NAMES[key] = label;
            });
            const meta = Array.isArray(data?.meta_kpis) ? data.meta_kpis : [];
            META_KPI_KEYS = new Set(meta.map(_normalizeKpiKey).filter(Boolean));
        } catch (e) {
            console.warn('Failed to load KPI category map:', e);
            KPI_CATEGORY_MAP = {};
            KPI_DISPLAY_NAMES = {};
            META_KPI_KEYS = new Set();
        }
    })();
    return _kpiCategoryConfigPromise;
}

function _labelForQueryKey(key) {
    const s = String(key || '');
    if (!s) return 'Unknown';
    if (s.includes(':raw:')) {
        const parts = s.split(':');
        return parts[parts.length - 1] || s;
    }
    const row = allCells.find(c => String(c.cell_key || c.cell_id) === s);
    if (row) return `${row.cell_name || 'Cell'} (${row.site_name || row.site_id || ''})`;
    const p = s.split('||');
    if (p.length === 4) return `${p[3]} (${p[2] || 'site'})`;
    return s;
}

function openChartConfigModal() {
    if (!lastQueryCellKeys.length) {
        _perfQueryUserMessage('Run Query first to configure chart objects/KPIs.');
        return;
    }
    const modal = document.getElementById('chart-config-modal');
    const objWrap = document.getElementById('chart-config-objects');
    const kpiWrap = document.getElementById('chart-config-kpis');
    if (!modal || !objWrap || !kpiWrap) return;

    objWrap.innerHTML = lastQueryCellKeys.map(k => `
        <label><input type="checkbox" class="cfg-obj-cb" data-key="${escAttr(String(k))}" checked> ${escHtml(_labelForQueryKey(k))}</label>
    `).join('');
    const allKpis = KPI_DEFS.map(d => d.key);
    kpiWrap.innerHTML = allKpis.map(k => `
        <label><input type="checkbox" class="cfg-kpi-cb" data-kpi="${escAttr(String(k))}" ${kpiSelectedKeys.has(k) ? 'checked' : ''}> ${escHtml(_kpiDisplayName(k))}</label>
    `).join('');

    modal.style.display = 'flex';
}

function closeChartConfigModal() {
    const modal = document.getElementById('chart-config-modal');
    if (!modal) return;
    modal.style.display = 'none';
}

async function applyChartConfigModal() {
    const objKeys = [...document.querySelectorAll('#chart-config-objects .cfg-obj-cb:checked')]
        .map(el => String(el.getAttribute('data-key') || '').trim())
        .filter(Boolean);
    const kpis = [...document.querySelectorAll('#chart-config-kpis .cfg-kpi-cb:checked')]
        .map(el => String(el.getAttribute('data-kpi') || '').trim())
        .filter(Boolean);

    if (!objKeys.length) {
        _perfQueryUserMessage('Select at least one object.');
        return;
    }
    if (!kpis.length) {
        _perfQueryUserMessage('Select at least one KPI.');
        return;
    }
    lastQueryCellKeys = objKeys;
    kpiSelectedKeys = new Set(kpis);
    updateKpiScopeUI();
    closeChartConfigModal();
    await addChartsFromLastQuery();
}

async function loadKpiHeaderMap() {
    try {
        const qs = new URLSearchParams({ data_scope: _currentDataScope() });
        const res = await fetch('/api/performance/kpi_headers_map?' + qs.toString(), { credentials: 'same-origin' });
        const data = await res.json();
        if (data.success && data.mapping && typeof data.mapping === 'object') {
            KPI_HEADER_MAP = data.mapping;
        } else {
            KPI_HEADER_MAP = {};
        }
    } catch (_) {
        KPI_HEADER_MAP = {};
    }
}

function _kpiHeadersForScope(vendor, technology) {
    if (!vendor || !technology) return [];
    const key = _scopeMapKey(vendor, technology);
    const list = KPI_HEADER_MAP[key];
    return Array.isArray(list) ? list : [];
}

function updateKpiSelectAllState() {
    const selectAll = document.getElementById('kpi-select-all');
    if (!selectAll) return;
    const allKeys = KPI_DEFS.map(d => d.key);
    if (!allKeys.length) {
        selectAll.checked = false;
        selectAll.indeterminate = false;
        selectAll.disabled = true;
        return;
    }
    const selectedCount = allKeys.filter(k => kpiSelectedKeys.has(k)).length;
    selectAll.disabled = false;
    selectAll.checked = selectedCount === allKeys.length;
    selectAll.indeterminate = selectedCount > 0 && selectedCount < allKeys.length;
}

function onKpiSelectAllToggle(checked) {
    const keys = KPI_DEFS.map(d => d.key);
    kpiSelectedKeys.clear();
    if (checked) {
        keys.forEach(k => kpiSelectedKeys.add(k));
    }
    document.querySelectorAll('#kpi-scope-list .kpi-scope-cb').forEach(cb => {
        cb.checked = !!checked;
    });
    updateKpiSelectAllState();
    onKpiSelectionChange();
}

function updateKpiScopeUI() {
    const titleEl = document.getElementById('kpi-scope-title');
    const countEl = document.getElementById('kpi-scope-count');
    const listEl = document.getElementById('kpi-scope-list');
    if (!titleEl || !listEl) return;

    const v = (document.getElementById('filter-vendor')?.value || '').trim();
    const t = (document.getElementById('filter-tech')?.value || '').trim();
    const vLabel = v || 'All vendors';
    const tLabel = t || 'all technologies';
    titleEl.textContent = `KPIs — ${vLabel} · ${tLabel}`;

    const cols = KPI_DEFS.map(d => d.key);
    const nSel = cols.filter(c => kpiSelectedKeys.has(c)).length;
    if (countEl) {
        countEl.textContent = cols.length
            ? `${nSel} / ${cols.length} selected`
            : '';
    }

    if (!cols.length) {
        listEl.innerHTML = '<p class="kpi-scope-empty">No KPI columns with data for this scope. Pick vendor/technology above, or import PM files.</p>';
        updateKpiSelectAllState();
        return;
    }
    listEl.innerHTML = cols.map((c, i) => {
        const checked = kpiSelectedKeys.has(c) ? ' checked' : '';
        return `<label class="kpi-scope-item" title="${escAttr(c)}">
            <input type="checkbox" class="kpi-scope-cb" id="kpi-cb-${i}" data-kpi-key="${escAttr(c)}"${checked}>
            <span class="kpi-scope-item-label">${escHtml(_kpiDisplayName(c))}</span>
        </label>`;
    }).join('');
    updateKpiSelectAllState();
}

function onKpiSelectionChange() {
    kpiSelectedKeys.clear();
    document.querySelectorAll('#kpi-scope-list .kpi-scope-cb:checked').forEach(cb => {
        const k = cb.getAttribute('data-kpi-key');
        if (k) kpiSelectedKeys.add(k);
    });
    const countEl = document.getElementById('kpi-scope-count');
    const cols = KPI_DEFS.map(d => d.key);
    const nSel = cols.filter(c => kpiSelectedKeys.has(c)).length;
    if (countEl && cols.length) countEl.textContent = `${nSel} / ${cols.length} selected`;
    updateKpiSelectAllState();

    if (lastTrendData && lastTrendData.trend && lastTrendData.trend.length) {
        renderAllCharts(lastTrendData.trend);
    }
}

async function loadKpiColumns() {
    try {
        await ensureKpiCategoryConfigLoaded();
        const v = (document.getElementById('filter-vendor')?.value || '').trim();
        const t = (document.getElementById('filter-tech')?.value || '').trim();

        const params = new URLSearchParams();
        if (v) params.set('vendor', v);
        if (t) params.set('technology', t);
        params.set('data_scope', _currentDataScope());
        const qs = params.toString();
        const res = await fetch('/api/performance/kpi_columns' + (qs ? '?' + qs : ''), {
            credentials: 'same-origin',
        });
        let data;
        try {
            data = await res.json();
        } catch (_) {
            data = { success: false, error: res.status ? `HTTP ${res.status}` : 'Invalid response' };
        }
        if (!data.success) {
            KPI_DEFS = [];
            updateKpiScopeUI();
            const listEl = document.getElementById('kpi-scope-list');
            if (listEl) {
                listEl.innerHTML = `<p class="kpi-scope-empty">Failed to load KPI list: ${escHtml(data.error || 'unknown error')}</p>`;
            }
            return;
        }
        let all = Array.isArray(data.columns)
            ? data.columns
            : [...new Set([...(data.nokia || []), ...(data.huawei || [])])];

        // If the live endpoint returned nothing, use cached header map (same scope only).
        if (!all.length && v && t) {
            all = _kpiHeadersForScope(v, t);
        }
        all = all
            .map(_normalizeKpiKey)
            .filter(Boolean)
            .filter(col => !_isMetadataKpiKey(col));

        KPI_DEFS = all.map(col => ({
            key:     col,
            label:   _kpiDisplayName(col),
            unit:    '',
            good:    null,
            warn:    null,
            inverse: false,
            color:   _colorFor(col),
        }));
        syncKpiSelectionWithDefs();
        updateKpiScopeUI();
    } catch (e) {
        console.warn('Could not load KPI columns:', e);
        KPI_DEFS = [];
        updateKpiScopeUI();
        const listEl = document.getElementById('kpi-scope-list');
        if (listEl) {
            listEl.innerHTML = `<p class="kpi-scope-empty">Could not load KPI columns. Please refresh and try again.</p>`;
        }
    }
}

async function onFilterTechChange() {
    _resetObjectScopeFilters();
    await loadKpiColumns();
    await loadCellGroups();
    await maybeAutoReloadCells();
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

/** PM trend row: always prefer backend-normalized ``timestamp`` for chart axis. */
function trendXRaw(row) {
    if (!row) return null;
    // Backend normalizes/buckets ``timestamp``; ``Date`` can remain vendor-raw and ambiguous.
    const v = row.timestamp ?? row.Date ?? row.date;
    if (v === null || v === undefined) return null;
    const s = String(v).trim();
    return s === '' ? null : s;
}

function formatTrendXLabel(raw) {
    if (raw == null) return '';
    const d = new Date(raw);
    if (!isNaN(d.getTime())) {
        return d.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ' ' +
               d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }
    return String(raw);
}

/** Two-line category label: time on first line, calendar day on second (Chart.js category multiline). */
function formatTrendXLabelHierarchy(raw) {
    if (raw == null) return [''];
    const d = new Date(raw);
    if (!isNaN(d.getTime())) {
        const line1 = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        const line2 = d.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' });
        return [line1, line2];
    }
    return [String(raw)];
}

function _parseTrendRowMoment(row) {
    const raw = trendXRaw(row);
    if (raw == null) return null;
    const d = new Date(raw);
    if (isNaN(d.getTime())) return null;
    return d;
}

function _dateKeyLocal(d) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function _monthKeyLocal(d) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

function _uniqueSortedDateKeysFromTrend(trend) {
    const set = new Set();
    (trend || []).forEach((row) => {
        const d = _parseTrendRowMoment(row);
        if (d) set.add(_dateKeyLocal(d));
    });
    return [...set].sort();
}

function _uniqueSortedMonthKeysFromTrend(trend) {
    const set = new Set();
    (trend || []).forEach((row) => {
        const d = _parseTrendRowMoment(row);
        if (d) set.add(_monthKeyLocal(d));
    });
    return [...set].sort();
}

function _perfDodSelectedDateKeysArray() {
    return [...perfDodSelectedDateSet].sort();
}

function _isDodChartMode() {
    return perfChartDisplayMode === 'dod' && _currentDataScope() === 'hourly';
}

function _isMomChartMode() {
    return perfChartDisplayMode === 'mom' && _currentDataScope() === 'daily';
}

function _isPeriodCompareChartMode() {
    return _isDodChartMode() || _isMomChartMode();
}

function _dodHourCategoryLabels() {
    const labels = [];
    for (let h = 0; h < 24; h++) {
        labels.push(`${String(h).padStart(2, '0')}:00`);
    }
    return labels;
}

function _momDayCategoryLabels() {
    const labels = [];
    for (let d = 1; d <= 31; d++) {
        labels.push(String(d).padStart(2, '0'));
    }
    return labels;
}

function _buildDodDatasetsForKpi(trend, def) {
    const sel = _perfDodSelectedDateKeysArray();
    const labels = _dodHourCategoryLabels();
    const datasets = [];
    sel.forEach((dk, di) => {
        const byHour = Array(24).fill(null);
        (trend || []).forEach((row) => {
            const d = _parseTrendRowMoment(row);
            if (!d || _dateKeyLocal(d) !== dk) return;
            const v = _toNumericOrNull(row[def.key]);
            byHour[d.getHours()] = v;
        });
        const color = _CHART_COLORS[di % _CHART_COLORS.length];
        datasets.push({
            label: dk,
            data: byHour,
            borderColor: color,
            backgroundColor: color + '18',
            pointBackgroundColor: color,
            pointRadius: 2,
            pointHoverRadius: 4,
            borderWidth: 2,
            tension: 0.25,
            spanGaps: true,
            fill: false,
        });
    });
    return { labels, datasets };
}

function _buildMomDatasetsForKpi(trend, def) {
    const sel = _perfDodSelectedDateKeysArray();
    const labels = _momDayCategoryLabels();
    const datasets = [];
    sel.forEach((mk, mi) => {
        const byDay = Array(31).fill(null);
        (trend || []).forEach((row) => {
            const d = _parseTrendRowMoment(row);
            if (!d || _monthKeyLocal(d) !== mk) return;
            const v = _toNumericOrNull(row[def.key]);
            byDay[d.getDate() - 1] = v;
        });
        const color = _CHART_COLORS[mi % _CHART_COLORS.length];
        datasets.push({
            label: mk,
            data: byDay,
            borderColor: color,
            backgroundColor: color + '18',
            pointBackgroundColor: color,
            pointRadius: 2,
            pointHoverRadius: 4,
            borderWidth: 2,
            tension: 0.25,
            spanGaps: true,
            fill: false,
        });
    });
    return { labels, datasets };
}

function _populatePerfPeriodCheckboxes(trend) {
    const wrap = document.getElementById('perf-dod-days');
    if (!wrap) return;
    const mom = _isMomChartMode();
    const keys = mom ? _uniqueSortedMonthKeysFromTrend(trend) : _uniqueSortedDateKeysFromTrend(trend);
    const sig = keys.join('|');
    if (perfDodPickerNeedsReset || sig !== perfDodPickerSig) {
        perfDodPickerNeedsReset = false;
        perfDodPickerSig = sig;
        perfDodSelectedDateSet.clear();
        const pick = keys.slice(-Math.min(3, keys.length));
        pick.forEach((k) => perfDodSelectedDateSet.add(k));
    }
    wrap.innerHTML = keys.map((k) => `
        <label class="perf-dod-day-chip">
            <input type="checkbox" class="perf-dod-day-cb" data-date-key="${escAttr(k)}" ${perfDodSelectedDateSet.has(k) ? 'checked' : ''}>
            ${escHtml(k)}
        </label>
    `).join('');
}

function _readPerfDodSelectionsFromDom() {
    perfDodSelectedDateSet.clear();
    document.querySelectorAll('.perf-dod-day-cb:checked').forEach((el) => {
        const k = String(el.getAttribute('data-date-key') || '').trim();
        if (k) perfDodSelectedDateSet.add(k);
    });
}

function _syncPerfDodRadiosFromState() {
    const scope = _currentDataScope();
    if ((perfChartDisplayMode === 'dod' && scope !== 'hourly') || (perfChartDisplayMode === 'mom' && scope !== 'daily')) {
        perfChartDisplayMode = 'trend';
    }
    document.querySelectorAll('input[name="perf-chart-display"]').forEach((el) => {
        el.checked = el.value === perfChartDisplayMode;
    });
    document.querySelectorAll('[data-chart-mode-option]').forEach((el) => {
        const mode = String(el.getAttribute('data-chart-mode-option') || '');
        const visible = mode === 'trend' || (mode === 'dod' && scope === 'hourly') || (mode === 'mom' && scope === 'daily');
        el.style.display = visible ? '' : 'none';
    });
    const label = document.getElementById('perf-chart-display-label');
    if (label) label.textContent = scope === 'daily' ? 'Daily charts' : 'Hourly charts';
    const daysWrap = document.getElementById('perf-dod-days-wrap');
    if (daysWrap) {
        daysWrap.style.display = _isPeriodCompareChartMode() ? 'flex' : 'none';
    }
}

function _wirePerfDodBarOnce() {
    if (perfDodBarWired) return;
    const bar = document.getElementById('perf-dod-bar');
    if (!bar) return;
    perfDodBarWired = true;
    bar.addEventListener('change', (e) => {
        const t = e.target;
        if (!t) return;
        if (t.name === 'perf-chart-display') {
            perfChartDisplayMode = t.value === 'dod' || t.value === 'mom' ? t.value : 'trend';
            _syncPerfDodRadiosFromState();
            if (Array.isArray(lastTrendData?.trend) && lastTrendData.trend.length) {
                if (_isPeriodCompareChartMode()) {
                    _populatePerfPeriodCheckboxes(lastTrendData.trend);
                }
                renderAllCharts(lastTrendData.trend);
            }
            return;
        }
        if (t.classList && t.classList.contains('perf-dod-day-cb')) {
            clearTimeout(perfDodDayChangeTimer);
            perfDodDayChangeTimer = setTimeout(() => {
                _readPerfDodSelectionsFromDom();
                if (Array.isArray(lastTrendData?.trend) && lastTrendData.trend.length) {
                    renderAllCharts(lastTrendData.trend);
                }
            }, 60);
        }
    });
}

function _syncPerfDodBar() {
    const bar = document.getElementById('perf-dod-bar');
    if (!bar) return;
    const tView = document.getElementById('pm-table-view');
    const chartsHidden = tView && tView.style.display === 'none';
    const trend = lastTrendData?.trend;
    const scope = _currentDataScope();
    if (!chartsHidden || !['hourly', 'daily'].includes(scope) || !Array.isArray(trend) || !trend.length || !chartTabs.length) {
        bar.style.display = 'none';
        return;
    }
    bar.style.display = 'flex';
    _wirePerfDodBarOnce();
    _syncPerfDodRadiosFromState();
    if (_isPeriodCompareChartMode()) {
        _populatePerfPeriodCheckboxes(trend);
        _readPerfDodSelectionsFromDom();
    }
}

function _perfTooltipTitleTrend(trend, items) {
    if (!items.length) return '';
    const i = items[0].dataIndex;
    return formatTrendXLabel(trendXRaw(trend[i]));
}

function _perfTooltipTitleDod(items) {
    if (!items.length) return '';
    const ds = items[0].dataset;
    const lab = ds && ds.label ? String(ds.label) : '';
    const h = items[0].dataIndex;
    const hh = String(h).padStart(2, '0');
    return `${lab} ${hh}:00`;
}

function _perfTooltipTitleMom(items) {
    if (!items.length) return '';
    const ds = items[0].dataset;
    const lab = ds && ds.label ? String(ds.label) : '';
    const day = String(items[0].dataIndex + 1).padStart(2, '0');
    return `${lab}-${day}`;
}

function _perfChartTheme() {
    const dark = document.body?.classList?.contains('dark-mode');
    return dark
        ? { tick: '#a9b7c9', grid: 'rgba(148, 163, 184, 0.12)' }
        : { tick: '#6d7f92', grid: 'rgba(127, 166, 194, 0.16)' };
}

function _perfChartYScaleOptions(extra = {}) {
    const theme = _perfChartTheme();
    return {
        ticks: { color: theme.tick, font: { size: 10 } },
        grid: { color: theme.grid },
        ...extra,
    };
}

function _perfChartXScaleOptions(trend, isDod) {
    const n = Array.isArray(trend) ? trend.length : 0;
    const theme = _perfChartTheme();
    return {
        ticks: {
            color: theme.tick,
            maxTicksLimit: isDod ? 24 : Math.min(24, Math.max(10, Math.ceil(n / 6) || 10)),
            font: { size: isDod ? 9 : 10, lineHeight: 1.25 },
            maxRotation: 0,
            autoSkip: !isDod,
        },
        grid: { color: theme.grid },
    };
}

// ============================================================
// Filter dropdowns
// ============================================================

async function loadFilters() {
    await loadKpiHeaderMap();
    await loadKpiColumns();
    await loadCellGroups();
    await loadPerformanceReports();

    const res  = await fetch('/api/performance/filters');
    const data = await res.json();
    if (!data.success) return;

    allSites    = data.sites;
    allClusters = data.clusters || [];
    allAreas    = data.areas    || [];

    _populateClusters(allClusters);
    _populateAreas(allAreas);
    _populateSites(allSites);
}

function setPerfBottomMode(mode) {
    perfBottomMode = mode === 'reports' ? 'reports' : 'kpis';
    const kBtn = document.getElementById('perf-mode-kpis');
    const rBtn = document.getElementById('perf-mode-reports');
    const kWrap = document.getElementById('perf-kpis-controls');
    const rWrap = document.getElementById('perf-reports-controls');
    if (kBtn) kBtn.classList.toggle('active', perfBottomMode === 'kpis');
    if (rBtn) rBtn.classList.toggle('active', perfBottomMode === 'reports');
    if (kWrap) kWrap.style.display = perfBottomMode === 'kpis' ? '' : 'none';
    if (rWrap) rWrap.style.display = perfBottomMode === 'reports' ? '' : 'none';
}

function _selectedCellKeysFromTree() {
    const mode = document.querySelector('input[name="perf-sel-mode"]:checked')?.value || 'single';
    const keys = [];
    if (mode === 'multiple') {
        document.querySelectorAll('#cell-list .hw-tree-leaf').forEach(leaf => {
            const cb = leaf.querySelector('.hw-tree-cb');
            if (cb && cb.checked) {
                const k = leaf.getAttribute('data-cell-key');
                if (k) keys.push(k);
            }
        });
    } else {
        const active = document.querySelector('#cell-list .hw-tree-leaf.active');
        const k = active && active.getAttribute('data-cell-key');
        if (k) keys.push(k);
    }
    return { mode, keys };
}

function _captureCurrentReportConfig() {
    const { mode, keys } = _selectedCellKeysFromTree();
    return {
        vendor: (document.getElementById('filter-vendor')?.value || '').trim(),
        technology: (document.getElementById('filter-tech')?.value || '').trim(),
        area: (document.getElementById('filter-area')?.value || '').trim(),
        cluster: (document.getElementById('filter-cluster')?.value || '').trim(),
        selection_type: (document.getElementById('filter-selection-type')?.value || 'cell').trim(),
        group_ref: (document.getElementById('filter-group')?.value || '').trim(),
        selection_mode: mode,
        selected_cell_keys: keys,
        selected_cell_value: (document.getElementById('filter-cell')?.value || '').trim(),
        data_scope: _currentDataScope(),
        kpi_keys: [...kpiSelectedKeys],
        hours: 'full',
    };
}

async function loadPerformanceReports() {
    const sel = document.getElementById('perf-report-select');
    if (!sel) return;
    try {
        const res = await fetch('/api/performance/reports');
        const data = await res.json();
        if (!data.success) return;
        performanceReports = Array.isArray(data.reports) ? data.reports : [];
        const prev = sel.value;
        sel.innerHTML = '<option value="">Select report...</option>';
        performanceReports.forEach(r => {
            const o = document.createElement('option');
            o.value = String(r.id);
            o.textContent = `${r.name}`;
            sel.appendChild(o);
        });
        if (prev && [...sel.options].some(o => o.value === prev)) sel.value = prev;
    } catch (_) {
        // keep UI silent on load failures
    }
}

async function saveCurrentReport() {
    const name = prompt('Report name?');
    if (!name || !name.trim()) return;
    const payload = {
        name: name.trim(),
        config: _captureCurrentReportConfig(),
    };
    const res = await fetch('/api/performance/reports', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!data.success) {
        alert(data.error || 'Could not save report');
        return;
    }
    await loadPerformanceReports();
    const sel = document.getElementById('perf-report-select');
    if (sel) sel.value = String(data.id);
}

async function deleteSelectedReport() {
    const sel = document.getElementById('perf-report-select');
    if (!sel || !sel.value) {
        alert('Select a report first.');
        return;
    }
    if (!confirm('Delete selected report?')) return;
    const res = await fetch(`/api/performance/reports/${encodeURIComponent(sel.value)}`, { method: 'DELETE' });
    const data = await res.json();
    if (!data.success) {
        alert(data.error || 'Could not delete report');
        return;
    }
    await loadPerformanceReports();
}

function setPerformanceFilterPresetStatus(message, kind = 'info') {
    const el = document.getElementById('perf-filter-preset-status');
    if (!el) return;
    el.textContent = message || '';
    el.className = `perf-filter-preset-status ${kind ? `is-${kind}` : ''}`;
}

async function loadPerformanceFilterPresets() {
    const sel = document.getElementById('perf-filter-preset-select');
    if (!sel) return;
    try {
        const res = await fetch('/api/profile/views?module=performance_filter_presets', {
            credentials: 'same-origin',
            cache: 'no-store',
            headers: { Accept: 'application/json' },
        });
        const data = await res.json().catch(() => ({}));
        performanceFilterPresets = res.ok && data.success && Array.isArray(data.views) ? data.views : [];
        const prev = sel.value;
        sel.innerHTML = performanceFilterPresets.length
            ? '<option value="">Select preset...</option>'
            : '<option value="">No saved presets</option>';
        performanceFilterPresets.forEach(preset => {
            const option = document.createElement('option');
            option.value = String(preset.id || '');
            option.textContent = String(preset.name || 'Untitled preset');
            sel.appendChild(option);
        });
        if (prev && performanceFilterPresets.some(p => String(p.id) === String(prev))) {
            sel.value = prev;
        }
    } catch (err) {
        performanceFilterPresets = [];
        sel.innerHTML = '<option value="">Could not load presets</option>';
        setPerformanceFilterPresetStatus('Could not load presets.', 'error');
    }
}

async function savePerformanceFilterPreset() {
    const name = prompt('Preset name?', 'My filter preset');
    if (name == null) return;
    const trimmed = String(name).trim();
    if (!trimmed) {
        setPerformanceFilterPresetStatus('Preset name is required.', 'error');
        return;
    }
    const payload = {
        module: 'performance_filter_presets',
        name: trimmed,
        state: getPerformanceState(),
    };
    try {
        const res = await fetch('/api/profile/views', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data.success) {
            throw new Error(data.error || 'Could not save preset');
        }
        await loadPerformanceFilterPresets();
        const sel = document.getElementById('perf-filter-preset-select');
        if (sel && data.id) sel.value = String(data.id);
        setPerformanceFilterPresetStatus(`Saved "${trimmed}".`, 'ok');
    } catch (err) {
        setPerformanceFilterPresetStatus(err.message || 'Could not save preset.', 'error');
    }
}

async function applySelectedPerformanceFilterPreset() {
    const sel = document.getElementById('perf-filter-preset-select');
    const id = String(sel?.value || '').trim();
    if (!id) {
        setPerformanceFilterPresetStatus('Select a preset first.', 'error');
        return;
    }
    try {
        setPerformanceFilterPresetStatus('Applying preset...', 'info');
        const res = await fetch(`/api/profile/views/${encodeURIComponent(id)}`, {
            credentials: 'same-origin',
            cache: 'no-store',
            headers: { Accept: 'application/json' },
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data.success || !data.view) {
            throw new Error(data.error || 'Could not load preset');
        }
        await applyPerformanceState(data.view.state || {});
        setPerformanceFilterPresetStatus(`Applied "${data.view.name || 'preset'}". Click Query when ready.`, 'ok');
    } catch (err) {
        setPerformanceFilterPresetStatus(err.message || 'Could not apply preset.', 'error');
    }
}

async function deleteSelectedPerformanceFilterPreset() {
    const sel = document.getElementById('perf-filter-preset-select');
    const id = String(sel?.value || '').trim();
    if (!id) {
        setPerformanceFilterPresetStatus('Select a preset first.', 'error');
        return;
    }
    const preset = performanceFilterPresets.find(p => String(p.id) === id);
    const name = preset?.name || 'selected preset';
    if (!confirm(`Delete "${name}"?`)) return;
    try {
        const res = await fetch(`/api/profile/views/${encodeURIComponent(id)}`, {
            method: 'DELETE',
            credentials: 'same-origin',
            headers: { Accept: 'application/json' },
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data.success) {
            throw new Error(data.error || 'Could not delete preset');
        }
        await loadPerformanceFilterPresets();
        setPerformanceFilterPresetStatus(`Deleted "${name}".`, 'ok');
    } catch (err) {
        setPerformanceFilterPresetStatus(err.message || 'Could not delete preset.', 'error');
    }
}

async function _applyReportConfig(cfg) {
    const setVal = (id, val) => {
        const el = document.getElementById(id);
        if (!el || val == null) return;
        el.value = String(val);
    };
    setVal('filter-vendor', cfg.vendor || '');
    setVal('filter-data-scope', cfg.data_scope || 'hourly');
    await onVendorChange();
    setVal('filter-tech', cfg.technology || '');
    await onFilterTechChange();
    setVal('filter-area', cfg.area || '');
    setVal('filter-cluster', cfg.cluster || '');
    const selType = cfg.selection_type || 'cell';
    setVal('filter-selection-type', selType);
    onSelectionTypeChange();
    if (selType === 'group') {
        await loadCellGroups();
        setVal('filter-group', cfg.group_ref || '');
    } else {
        await applyFilters({ skipAutoChart: true, skipKpiColumns: true });
        setVal('filter-cell', cfg.selected_cell_value || '');
        const savedMode = cfg.selection_mode === 'multiple' ? 'multiple' : 'single';
        const modeEl = document.querySelector(`input[name="perf-sel-mode"][value="${savedMode}"]`);
        if (modeEl) modeEl.checked = true;
        onPerfSelectionModeChange();
        const wanted = new Set(Array.isArray(cfg.selected_cell_keys) ? cfg.selected_cell_keys.map(String) : []);
        document.querySelectorAll('#cell-list .hw-tree-leaf').forEach(leaf => {
            const key = String(leaf.getAttribute('data-cell-key') || '');
            const hit = wanted.has(key);
            leaf.classList.toggle('active', hit && savedMode === 'single');
            const cb = leaf.querySelector('.hw-tree-cb');
            if (cb) cb.checked = hit && savedMode === 'multiple';
        });
        // Backward/robust fallback: if no explicit tree key was saved, reuse filter-cell value.
        if (!wanted.size && cfg.selected_cell_value) {
            const fallbackKey = String(cfg.selected_cell_value);
            document.querySelectorAll('#cell-list .hw-tree-leaf').forEach(leaf => {
                const key = String(leaf.getAttribute('data-cell-key') || '');
                const hit = key === fallbackKey;
                leaf.classList.toggle('active', hit && savedMode === 'single');
                const cb = leaf.querySelector('.hw-tree-cb');
                if (cb) cb.checked = hit && savedMode === 'multiple';
            });
        }
    }
    // Time window is fixed to full retained duration.
    if (Array.isArray(cfg.kpi_keys) && cfg.kpi_keys.length) {
        kpiSelectedKeys = new Set(cfg.kpi_keys.map(String));
        updateKpiScopeUI();
    }
}

async function runSelectedReport() {
    const sel = document.getElementById('perf-report-select');
    if (!sel || !sel.value) {
        alert('Select a report first.');
        return;
    }
    const report = performanceReports.find(r => String(r.id) === String(sel.value));
    if (!report || !report.config) {
        alert('Invalid report config.');
        return;
    }
    await _applyReportConfig(report.config);
    await runPerformanceQuery();
}

async function loadCellGroups() {
    const sel = document.getElementById('filter-group');
    if (!sel) return;
    try {
        const vendor = (document.getElementById('filter-vendor')?.value || '').trim();
        const technology = (document.getElementById('filter-tech')?.value || '').trim();
        const qs = new URLSearchParams();
        if (vendor) qs.set('vendor', vendor);
        if (technology) qs.set('technology', technology);
        qs.set('data_scope', _currentDataScope());
        const res = await fetch('/api/performance/groups' + (qs.toString() ? `?${qs.toString()}` : ''));
        const data = await res.json();
        if (!data.success) {
            return;
        }
        allCellGroups = Array.isArray(data.groups) ? data.groups : [];
        const prev = sel.value;
        sel.innerHTML = '<option value="">Select group...</option>';
        allCellGroups.forEach(g => {
            const o = document.createElement('option');
            o.value = String(g.group_ref || '');
            const n = Number(g.cell_count || 0);
            const tech = String(g.technology || '').trim();
            o.textContent = `${g.name} (${g.vendor || 'N/A'}${tech ? ' · ' + tech : ''} · ${n})`;
            sel.appendChild(o);
        });
        if (!allCellGroups.length) {
            const o = document.createElement('option');
            o.value = '';
            o.textContent = 'No groups for selected vendor/technology';
            sel.appendChild(o);
        }
        if (prev && [...sel.options].some(o => o.value === prev)) sel.value = prev;
        const selectionType = (document.getElementById('filter-selection-type')?.value || 'cell').trim();
        if (selectionType === 'group') {
            showGroupPicker(allCellGroups);
        }
    } catch (_) {
        // Keep UI usable even if group DB is not ready.
    }
}

async function onSelectionTypeChange() {
    const type = (document.getElementById('filter-selection-type')?.value || 'cell').trim();
    const groupWrap = document.getElementById('group-picker-wrap');
    const cellsBody = document.getElementById('perf-cells-body');
    if (groupWrap) groupWrap.style.display = 'none';
    if (cellsBody) cellsBody.style.display = '';
    if (type === 'group') {
        allCells = [];
        activeCellId = null;
        await loadCellGroups();
        showGroupPicker(allCellGroups);
        _perfQueryUserMessage('Select a group, then click Query.');
    } else {
        showCellPicker(allCells, { fromApply: true });
    }
}

function showGroupPicker(groups) {
    const list = document.getElementById('cell-list');
    if (!list) return;
    const g = Array.isArray(groups) ? groups : [];
    if (!g.length) {
        list.innerHTML = '<p class="perf-tree-empty">No groups for selected vendor/technology.</p>';
        const badge = document.getElementById('cell-count-badge');
        if (badge) badge.textContent = '0 groups';
        return;
    }
    const rows = g
        .slice()
        .sort((a, b) => String(a.name || '').localeCompare(String(b.name || ''), undefined, { sensitivity: 'base' }))
        .map(gr => {
            const ref = String(gr.group_ref || '');
            const vendor = String(gr.vendor || '');
            const tech = String(gr.technology || '').trim();
            const count = Number(gr.cell_count || 0);
            const search = `${gr.name || ''} ${vendor} ${tech}`.toLowerCase();
            return `<div class="hw-tree-leaf hw-tree-group-leaf" role="treeitem" data-group-ref="${escAttr(ref)}" data-search="${escAttr(search)}">
                <input type="checkbox" class="hw-tree-cb" onclick="event.stopPropagation()" aria-label="Select group">
                <span class="hw-tree-leaf-name">${escHtml(gr.name || 'Unnamed group')}</span>
                <span class="hw-tree-leaf-tech">${escHtml(vendor)}${tech ? ' · ' + escHtml(tech) : ''} · ${count}</span>
            </div>`;
        })
        .join('');
    list.innerHTML = `<div class="hw-tree" role="tree">${rows}</div>`;
    const badge = document.getElementById('cell-count-badge');
    if (badge) badge.textContent = `${g.length} groups`;
    onPerfSelectionModeChange();
}

function _populateClusters(clusters) {
    const sel = document.getElementById('filter-cluster');
    if (!sel || sel.tagName !== 'SELECT') return;
    const prev = sel.value;
    sel.innerHTML = '<option value="">All Clusters</option>';
    const nums = clusters.map(c => Number(c)).filter(c => !Number.isNaN(c)).sort((a, b) => a - b);
    nums.forEach(c => {
        const o = document.createElement('option');
        o.value = String(c); o.textContent = 'Cluster ' + c;
        sel.appendChild(o);
    });
    if (prev && [...sel.options].some(opt => opt.value === prev)) sel.value = prev;
    else sel.value = '';
}

function _populateAreas(areas) {
    const sel = document.getElementById('filter-area');
    if (!sel || sel.tagName !== 'SELECT') return;
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
    filteredSites = sites.slice();

    const siteHidden = document.getElementById('filter-site');
    const siteInput  = document.getElementById('filter-site-search');
    const siteList   = document.getElementById('filter-site-options');
    const prevId     = siteHidden && siteHidden.value;

    if (!siteList || !siteInput) {
        if (siteHidden && prevId) {
            const ok = sites.some(s => String(s.site_id) === String(prevId));
            if (!ok) siteHidden.value = '';
        }
        return;
    }

    siteList.innerHTML = '';
    sites.forEach(s => {
        const o = document.createElement('option');
        // Keep display unique/easy to pick.
        o.value = `${s.site_name} (${s.site_id})`;
        siteList.appendChild(o);
    });

    // Restore previous selection text when possible.
    const prevSite = sites.find(s => String(s.site_id) === String(prevId));
    if (prevSite) {
        siteHidden.value = String(prevSite.site_id);
        siteInput.value  = `${prevSite.site_name} (${prevSite.site_id})`;
    } else {
        siteHidden.value = '';
        siteInput.value  = '';
    }
}

function onSiteSearchInput() {
    const siteHidden = document.getElementById('filter-site');
    if (siteHidden) siteHidden.value = '';
}

function onSiteSearchSelect() {
    const siteInput = document.getElementById('filter-site-search');
    const siteHidden = document.getElementById('filter-site');
    const txt = (siteInput.value || '').trim();
    if (!txt) {
        siteHidden.value = '';
        onSiteChange();
        return;
    }

    // Expected format: "Site Name (12345)"
    const m = txt.match(/\(([^()]+)\)\s*$/);
    if (m) {
        const pickedId = m[1].trim();
        const found = filteredSites.find(s => String(s.site_id) === pickedId);
        if (found) {
            siteHidden.value = String(found.site_id);
            onSiteChange();
            return;
        }
    }

    // Fallback exact site name match (if user pasted only name).
    const byName = filteredSites.find(s => String(s.site_name) === txt);
    siteHidden.value = byName ? String(byName.site_id) : '';
    onSiteChange();
}

async function onVendorChange() {
    if (perfPmViewPrefPromise) {
        await perfPmViewPrefPromise;
    }
    const vendor  = document.getElementById('filter-vendor').value;
    const techSel = document.getElementById('filter-tech');
    const opt5g   = techSel.querySelector('option[value="5G"]');
    if (opt5g) opt5g.style.display = vendor === 'Huawei' ? 'none' : '';
    if (vendor === 'Huawei' && techSel.value === '5G') techSel.value = '';

    // Show view toggle only when a specific vendor is selected
    const toggle = document.getElementById('view-toggle');
    if (toggle) toggle.style.display = vendor ? 'flex' : 'none';

    // If no vendor, make sure we're back in charts mode
    if (!vendor) {
        const tView = document.getElementById('pm-table-view');
        if (tView && tView.style.display !== 'none') switchViewMode('charts');
    } else {
        const mode = perfPreferredPmViewMode === 'table' ? 'table' : 'charts';
        switchViewMode(mode);
    }
    _resetObjectScopeFilters();
    lastQueryCellKeys = [];
    hwCurrentScopedCellNames = [];
    hwCurrentScopedGroupRefs = [];
    _setPerfChartChoiceVisible(false);

    await loadKpiColumns();
    await loadCellGroups();
    await maybeAutoReloadCells();
}

async function loadPmViewPreference() {
    try {
        const res = await fetch('/api/profile/preferences');
        const data = await res.json();
        if (!data?.success) return;
        const prefs = data.preferences || {};
        const pmView = String(prefs.pm_view_mode || '').toLowerCase();
        if (pmView === 'table' || pmView === 'charts') {
            perfPreferredPmViewMode = pmView;
            return;
        }
        // Backward compatibility with old preference key.
        if (typeof prefs.compact_tables === 'boolean') {
            perfPreferredPmViewMode = prefs.compact_tables ? 'table' : 'charts';
        }
    } catch (_) {
        // Keep default if preferences cannot be loaded.
    }
}

function _resetObjectScopeFilters() {
    const areaSel = document.getElementById('filter-area');
    const clusterSel = document.getElementById('filter-cluster');
    const siteHidden = document.getElementById('filter-site');
    const siteInput = document.getElementById('filter-site-search');
    const cellHidden = document.getElementById('filter-cell');

    if (areaSel && areaSel.tagName === 'SELECT') areaSel.value = '';
    if (clusterSel && clusterSel.tagName === 'SELECT') clusterSel.value = '';
    if (siteHidden) siteHidden.value = '';
    if (siteInput) siteInput.value = '';
    if (cellHidden) cellHidden.value = '';
}

function onClusterChange() {
    const cEl = document.getElementById('filter-cluster');
    const aEl = document.getElementById('filter-area');
    if (!cEl || cEl.tagName !== 'SELECT' || !aEl || aEl.tagName !== 'SELECT') return;

    const cluster = cEl.value;
    let area = aEl.value;

    let filteredAreas;
    if (cluster) {
        filteredAreas = allAreas.filter(a => String(a.cluster) === cluster);
        const implied = filteredAreas[0];
        if (implied) area = implied.area;
    } else {
        filteredAreas = area
            ? allAreas.filter(a => a.area === area)
            : allAreas;
    }
    _populateAreas(filteredAreas);
    const areaSel = aEl;
    if (area && [...areaSel.options].some(o => o.value === area)) areaSel.value = area;
    else {
        area = '';
        areaSel.value = '';
    }

    _applyGeoFilters(cluster, area);
    // In the Cells panel, changing cluster should immediately refresh scoped cells.
    void applyFilters({ skipAutoChart: true, skipKpiColumns: true });
}

function onAreaChange() {
    const areaEl = document.getElementById('filter-area');
    const clusterSel = document.getElementById('filter-cluster');
    if (!areaEl || areaEl.tagName !== 'SELECT' || !clusterSel || clusterSel.tagName !== 'SELECT') return;

    const area = areaEl.value;
    const prevCluster = clusterSel.value;

    const clustersForDropdown = area
        ? [...new Set(allAreas.filter(a => a.area === area).map(a => Number(a.cluster)))]
            .filter(c => !Number.isNaN(c))
            .sort((a, b) => a - b)
        : allClusters.slice();

    _populateClusters(clustersForDropdown);
    const cluster = clusterSel.value;

    _applyGeoFilters(cluster, area);
    // In the Cells panel, changing area should immediately refresh scoped cells.
    void applyFilters({ skipAutoChart: true, skipKpiColumns: true });
}

function _applyGeoFilters(cluster, area) {
    let filtered = allSites;
    if (cluster) filtered = filtered.filter(s => String(s.cluster) === cluster);
    if (area)    filtered = filtered.filter(s => s.area === area);
    _populateSites(filtered);
    const siteH = document.getElementById('filter-site');
    if (siteH) siteH.value = '';
    const siteInput = document.getElementById('filter-site-search');
    if (siteInput) siteInput.value = '';
    const cellEl = document.getElementById('filter-cell');
    if (cellEl) {
        if (cellEl.tagName === 'SELECT') cellEl.innerHTML = '<option value="">All Cells</option>';
        else cellEl.value = '';
    }
}

async function onSiteChange() {
    const siteId = document.getElementById('filter-site')?.value;
    const cellSel = document.getElementById('filter-cell');
    if (!cellSel) return;
    if (cellSel.tagName !== 'SELECT') {
        cellSel.value = '';
        return;
    }
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
        o.value = c.cell_key || c.cell_id;
        o.textContent = `${c.cell_name} (${c.technology || 'N/A'})`;
        cellSel.appendChild(o);
    });
}

// ============================================================
// Scope: reload cell tree (vendor + technology required for auto scope)
// ============================================================

function _perfDefaultChartsTitle() {
    return 'Select cells and KPIs, then click Query';
}

function _resetPerfChartStateForNewScope() {
    chartTabs = [];
    activeChartTabId = null;
    activeKpiCategoryByTabId = {};
    lastTrendData = null;
    activeCellId = null;
    document.querySelectorAll('#cell-list .hw-tree-leaf').forEach(el => el.classList.remove('active'));
    Object.values(charts).forEach(c => { try { c.destroy(); } catch (_) { /* noop */ } });
    Object.keys(charts).forEach(k => delete charts[k]);
    const wrap = document.getElementById('charts-wrap');
    if (wrap) {
        wrap.innerHTML = '';
        wrap.style.display = 'none';
    }
    const exportBtn = document.getElementById('btn-export');
    if (exportBtn) exportBtn.style.display = 'none';
    const title = document.getElementById('charts-title');
    if (title) title.textContent = _perfDefaultChartsTitle();
    _setPerfChartChoiceVisible(false);
    const noSel = document.getElementById('no-selection');
    if (noSel) noSel.style.display = 'flex';
    const loading = document.getElementById('loading-charts');
    if (loading) loading.style.display = 'none';
    renderPerfChartTabs();
}

function _perfQueryUserMessage(msg) {
    const title = document.getElementById('charts-title');
    const noSel = document.getElementById('no-selection');
    if (title) title.textContent = msg;
    if (noSel) {
        const p = noSel.querySelector('p');
        if (p) p.textContent = msg;
        noSel.style.display = 'flex';
    }
    const wrap = document.getElementById('charts-wrap');
    if (wrap) wrap.style.display = 'none';
    const loading = document.getElementById('loading-charts');
    if (loading) loading.style.display = 'none';
    const catBar = document.getElementById('perf-kpi-category-tabs-bar');
    const catStrip = document.getElementById('perf-kpi-category-tabs-strip');
    if (catBar) catBar.style.display = 'none';
    if (catStrip) catStrip.innerHTML = '';
}

function _setPerfChartChoiceVisible(visible) {
    const display = visible ? 'inline-flex' : 'none';
    const addBtn = document.getElementById('btn-add-charts');
    const customBtn = document.getElementById('btn-custom-chart');
    const choiceBar = document.getElementById('perf-chart-choice-bar');
    if (addBtn) addBtn.style.display = display;
    if (customBtn) customBtn.style.display = display;
    if (choiceBar) choiceBar.style.display = visible ? 'flex' : 'none';
}

async function maybeAutoReloadCells() {
    const v = (document.getElementById('filter-vendor')?.value || '').trim();
    const t = (document.getElementById('filter-tech')?.value || '').trim();
    const cellH = document.getElementById('filter-cell');
    if (cellH) cellH.value = '';

    if (!v || !t) {
        allCells = [];
        showCellPicker([], { fromApply: false });
        _resetPerfChartStateForNewScope();
        const br = document.getElementById('btn-refresh');
        if (br) br.style.display = 'none';
        return;
    }

    await applyFilters({ skipAutoChart: true, skipKpiColumns: true });
}

async function runPerformanceQuery() {
    onKpiSelectionChange();

    const v = (document.getElementById('filter-vendor')?.value || '').trim();
    const t = (document.getElementById('filter-tech')?.value || '').trim();
    const selectionType = (document.getElementById('filter-selection-type')?.value || 'cell').trim();
    if (!v || !t) {
        _perfQueryUserMessage('Select a vendor and technology to load cells.');
        return;
    }

    let keys = [];
    let mode = document.querySelector('input[name="perf-sel-mode"]:checked')?.value || 'single';
    if (selectionType === 'group') {
        let groupRefs = [];
        if (mode === 'multiple') {
            document.querySelectorAll('#cell-list .hw-tree-group-leaf').forEach(leaf => {
                const cb = leaf.querySelector('.hw-tree-cb');
                if (cb && cb.checked) {
                    const gr = leaf.getAttribute('data-group-ref');
                    if (gr) groupRefs.push(gr);
                }
            });
        } else {
            const active = document.querySelector('#cell-list .hw-tree-group-leaf.active');
            const gr = active && active.getAttribute('data-group-ref');
            if (gr) groupRefs = [gr];
        }
        if (!groupRefs.length) {
            _perfQueryUserMessage(mode === 'multiple'
                ? 'Check one or more groups, then click Query.'
                : 'Click a group to select it, then click Query.');
            return;
        }
        keys = [...groupRefs];
    } else {
        mode = document.querySelector('input[name="perf-sel-mode"]:checked')?.value || 'single';
        if (mode === 'multiple') {
            document.querySelectorAll('#cell-list .hw-tree-leaf').forEach(leaf => {
                const cb = leaf.querySelector('.hw-tree-cb');
                if (cb && cb.checked) {
                    const k = leaf.getAttribute('data-cell-key');
                    if (k) keys.push(k);
                }
            });
        } else {
            const active = document.querySelector('#cell-list .hw-tree-leaf.active');
            const k = active && active.getAttribute('data-cell-key');
            if (k) keys = [k];
        }
    }

    if (!keys.length) {
        const fallbackCell = (document.getElementById('filter-cell')?.value || '').trim();
        if (fallbackCell) {
            keys = [fallbackCell];
        }
    }

    if (!keys.length) {
        if (selectionType === 'group') {
            _perfQueryUserMessage('This group has no cells for the selected vendor/technology.');
        } else {
            _perfQueryUserMessage(mode === 'multiple'
                ? 'Check one or more cells in the tree, then click Query.'
                : 'Click a cell in the tree to select it, then click Query.');
        }
        return;
    }

    lastQueryCellKeys = [...keys];
    lastQuerySelectionType = selectionType;
    // New query = new chart session; avoid old multi-chart tabs resurfacing.
    chartTabs = [];
    activeChartTabId = null;
    activeKpiCategoryByTabId = {};
    const tabBar = document.getElementById('perf-chart-tabs-bar');
    if (tabBar) tabBar.style.display = 'none';
    if (selectionType === 'group') {
        hwCurrentScopedGroupRefs = [...keys];
        hwCurrentScopedCellNames = [];
    } else {
        hwCurrentScopedGroupRefs = [];
        hwCurrentScopedCellNames = await _resolveCellNamesFromQueryKeys(keys, selectionType, v, t);
    }

    _setPerfChartChoiceVisible(true);

    const compareBtn = document.getElementById('btn-compare-charts');
    if (compareBtn) {
        // Compare only makes sense when at least two cells are selected.
        const cellOnlyCount = keys.filter(k => !String(k).includes(':raw:')).length;
        compareBtn.style.display = (selectionType !== 'group' && cellOnlyCount >= 2) ? 'inline-flex' : 'none';
    }

    switchViewMode('table');
    _perfQueryUserMessage(`Loaded ${keys.length} selected object(s). Choose Template Charts or Add Chart to visualize.`);
    const noSel = document.getElementById('no-selection');
    if (noSel) noSel.style.display = 'none';
}

async function addChartsFromLastQuery() {
    if (!lastQueryCellKeys.length) {
        _perfQueryUserMessage('Run Query first to load tabular data, then add charts.');
        return;
    }
    if (KPI_DEFS.length && kpiSelectedKeys.size === 0) {
        _perfQueryUserMessage('Select at least one KPI to chart.');
        return;
    }

    const noSel = document.getElementById('no-selection');
    if (noSel) noSel.style.display = 'none';
    const wrap = document.getElementById('charts-wrap');
    if (wrap) wrap.style.display = 'none';
    const loading = document.getElementById('loading-charts');
    if (loading) loading.style.display = 'flex';
    const choiceBar = document.getElementById('perf-chart-choice-bar');
    if (choiceBar) choiceBar.style.display = 'none';

    chartTabs = [];
    activeChartTabId = null;
    activeKpiCategoryByTabId = {};
    const tabBar = document.getElementById('perf-chart-tabs-bar');
    if (tabBar) tabBar.style.display = 'none';

    const uniqueKeys = [...new Set(lastQueryCellKeys.map(k => String(k || '').trim()).filter(Boolean))];
    let added = 0;

    for (const key of uniqueKeys) {
        try {
            if (key.includes(':raw:')) {
                const params = new URLSearchParams({
                    group_ref: key,
                    granularity: _currentTrendGranularity(),
                    data_scope: _currentDataScope(),
                });
                if (KPI_DEFS.length && kpiSelectedKeys.size > 0) {
                    params.set('kpi', [...kpiSelectedKeys].join(','));
                }
                const res = await fetch(`/api/performance/group/trend?${params.toString()}`);
                const data = await res.json();
                if (!data.success) throw new Error(data.error || 'Failed to load group trend');
                const group = data.group || {};
                const trend = Array.isArray(data.trend) ? data.trend : [];
                if (!trend.length) continue;
                const pseudoPayload = {
                    cell: {
                        cell_name: group.name || 'Group',
                        vendor: group.vendor || '',
                        technology: '',
                        site_id: '',
                        cell_key: key,
                    },
                    trend,
                };
                upsertPerfChartTab(pseudoPayload, 'full', key);
                added++;
            } else {
                const data = await fetchCellTrendData(key);
                const trend = Array.isArray(data.trend) ? data.trend : [];
                if (!trend.length) continue;
                upsertPerfChartTab(data, 'full', key);
                added++;
            }
        } catch (_) {
            // Skip failed object; continue with the rest.
        }
    }

    if (loading) loading.style.display = 'none';

    if (!added) {
        _perfQueryUserMessage('No trend data found for the selected objects/KPIs.');
        return;
    }

    switchViewMode('charts');
    perfDodPickerNeedsReset = true;
    const br = document.getElementById('btn-refresh');
    if (br) br.style.display = 'inline-flex';
}

function _buildCellTrendParamsFromKey(cellId) {
    const selected = allCells.find(c => String(c.cell_key || c.cell_id) === String(cellId));
    const keyParts = String(cellId || '').split('||');
    const params = new URLSearchParams({
        granularity: _currentTrendGranularity(),
        data_scope: _currentDataScope(),
    });
    if (selected) {
        params.set('cell_name', String(selected.cell_name || ''));
        params.set('technology', String(selected.technology || ''));
        params.set('site_id', String(selected.site_id || ''));
        params.set('vendor', String(selected.vendor || ''));
    } else if (keyParts.length === 4) {
        params.set('vendor', String(keyParts[0] || ''));
        params.set('technology', String(keyParts[1] || ''));
        params.set('site_id', String(keyParts[2] || ''));
        params.set('cell_name', String(keyParts[3] || ''));
    } else {
        params.set('cell_name', String(cellId || ''));
    }
    return params;
}

async function fetchCellTrendData(cellId) {
    const params = _buildCellTrendParamsFromKey(cellId);
    if (KPI_DEFS.length && kpiSelectedKeys.size > 0) {
        params.set('kpi', [...kpiSelectedKeys].join(','));
    }
    const res = await fetch(`/api/performance/cell/trend?${params.toString()}`);
    const data = await res.json();
    if (!data.success) throw new Error(data.error || 'Failed to load trend');
    return data;
}

async function _resolveCellNamesFromQueryKeys(keys, selectionType, vendor, technology) {
    const out = new Set();
    const dataScope = _currentDataScope();
    for (const key of (keys || [])) {
        const s = String(key || '').trim();
        if (!s) continue;

        if (selectionType === 'group' || s.includes(':raw:')) {
            try {
                const params = new URLSearchParams({
                    vendor: vendor || '',
                    technology: technology || '',
                    data_scope: dataScope,
                });
                const res = await fetch(`/api/performance/groups/${encodeURIComponent(s)}/cell_keys?${params.toString()}`);
                const data = await res.json();
                if (data?.success && Array.isArray(data.cell_keys)) {
                    data.cell_keys.forEach(r => {
                        const n = String(r?.cell_name || '').trim();
                        if (n) out.add(n);
                    });
                }
            } catch (_) {
                // Best-effort for scoped table filtering.
            }
            continue;
        }

        const row = allCells.find(c => String(c.cell_key || c.cell_id) === s);
        if (row?.cell_name) {
            out.add(String(row.cell_name).trim());
            continue;
        }
        const parts = s.split('||');
        if (parts.length === 4 && parts[3]) out.add(String(parts[3]).trim());
    }
    return [...out].filter(Boolean);
}

async function loadGroupCharts(groupRef) {
    activeCellId = String(groupRef);
    document.querySelectorAll('.hw-tree-leaf').forEach(el => {
        const match = (el.getAttribute('data-group-ref') || '') === String(groupRef);
        el.classList.toggle('active', match);
    });

    document.getElementById('no-selection').style.display   = 'none';
    document.getElementById('charts-wrap').style.display    = 'none';
    document.getElementById('loading-charts').style.display = 'flex';
    document.getElementById('btn-export').style.display     = 'none';
    document.getElementById('btn-refresh').style.display    = 'inline-flex';

    const hours = 'full';
    try {
        const params = new URLSearchParams({
            group_ref: String(groupRef || ''),
            granularity: _currentTrendGranularity(),
            data_scope: _currentDataScope(),
        });
        if (KPI_DEFS.length && kpiSelectedKeys.size > 0) {
            params.set('kpi', [...kpiSelectedKeys].join(','));
        }
        const res  = await fetch(`/api/performance/group/trend?${params.toString()}`);
        const data = await res.json();
        if (!data.success) throw new Error(data.error);
        const group = data.group || {};
        const trend = data.trend || [];
        const pseudoPayload = {
            cell: { cell_name: group.name || 'Group', vendor: group.vendor || '', technology: '', site_id: '' },
            trend,
        };
        upsertPerfChartTab(pseudoPayload, hours, groupRef);
        document.getElementById('charts-title').textContent = group.name || 'Group KPI trends';
        renderAllCharts(trend);
        document.getElementById('loading-charts').style.display = 'none';
        document.getElementById('charts-wrap').style.display = 'grid';
    } catch (e) {
        document.getElementById('loading-charts').style.display = 'none';
        document.getElementById('no-selection').style.display   = 'flex';
        document.getElementById('charts-title').textContent   =
            'Error loading data: ' + (e.message || String(e));
    }
}

async function onPerfTimeWindowChange() {
    // Kept for backward compatibility with template event hooks.
    // Time window is now fixed to full retained duration.
}

/** Match trend bucketing to selected data scope (hourly vs daily). */
function _currentTrendGranularity() {
    return _currentDataScope() === 'daily' ? 'day' : 'hour';
}

/**
 * @param {{ skipAutoChart?: boolean, skipKpiColumns?: boolean }} opts
 *  skipAutoChart: do not jump straight to chart when filter-cell is set (scope refresh from UI).
 *  skipKpiColumns: avoid duplicate KPI column fetch when caller just ran loadKpiColumns.
 */
async function applyFilters(opts = {}) {
    if (!opts.skipKpiColumns) await loadKpiColumns();

    const vendor  = document.getElementById('filter-vendor').value;
    const tech    = document.getElementById('filter-tech').value;
    const selectionType = (document.getElementById('filter-selection-type')?.value || 'cell').trim();
    const cluster = document.getElementById('filter-cluster')?.value || '';
    const area    = document.getElementById('filter-area')?.value || '';
    const site    = document.getElementById('filter-site').value;
    const cell    = document.getElementById('filter-cell').value;

    if (cell && !opts.skipAutoChart) {
        _resetPerfChartStateForNewScope();
        await loadCellCharts(cell);
        return;
    }

    if (selectionType === 'group') {
        // Groups mode should read from groups DB flow, not metadata /cells list.
        allCells = [];
        _resetPerfChartStateForNewScope();
        showGroupPicker(allCellGroups);
        const tView = document.getElementById('pm-table-view');
        if (tView && tView.style.display !== 'none') {
            const v = document.getElementById('filter-vendor').value;
            const t2 = document.getElementById('filter-tech').value;
            if (v && t2) loadPmTable(v, t2, hwCurrentSearch, 1);
        }
        return;
    }

    const params = new URLSearchParams();
    if (vendor)  params.set('vendor',     vendor);
    if (tech)    params.set('technology', tech);
    if (cluster) params.set('cluster',    cluster);
    if (area)    params.set('area',       area);
    if (site)    params.set('site_id',    site);
    params.set('data_scope', _currentDataScope());

    const res  = await fetch('/api/performance/cells?' + params);
    const data = await res.json();
    if (!data.success) return;

    allCells = data.cells;
    if (vendor) {
        allCells = allCells.filter(c => String(c.vendor || '') === vendor);
    }
    _rebuildGeoFiltersFromCells(allCells);

    _resetPerfChartStateForNewScope();

    showCellPicker(allCells, { fromApply: true });

    const tView = document.getElementById('pm-table-view');
    if (tView && tView.style.display !== 'none') {
        const v = document.getElementById('filter-vendor').value;
        const t2 = document.getElementById('filter-tech').value;
        if (v && t2) loadPmTable(v, t2, hwCurrentSearch, 1);
    }
}

// ============================================================
// Cell picker — Huawei-style tree after Apply
// ============================================================

function escHtml(s) {
    return String(s ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/"/g, '&quot;');
}

function escAttr(s) {
    return String(s ?? '')
        .replace(/&/g, '&amp;')
        .replace(/"/g, '&quot;')
        .replace(/</g, '&lt;');
}

const PERF_GEO_EM_DASH = '—';

function _perfNormArea(c) {
    const a = (c.area || '').trim();
    return a || PERF_GEO_EM_DASH;
}
function _perfNormCluster(c) {
    if (c.cluster == null || String(c.cluster).trim() === '') return PERF_GEO_EM_DASH;
    return String(c.cluster).trim();
}
function _perfClusterFolderLabel(k) {
    return k === PERF_GEO_EM_DASH ? PERF_GEO_EM_DASH : ('Cluster ' + k);
}
function _perfSortAreaKeys(a, b) {
    if (a === PERF_GEO_EM_DASH && b !== PERF_GEO_EM_DASH) return 1;
    if (b === PERF_GEO_EM_DASH && a !== PERF_GEO_EM_DASH) return -1;
    return String(a).localeCompare(String(b), undefined, { sensitivity: 'base' });
}
function _perfSortClusterKeys(a, b) {
    if (a === PERF_GEO_EM_DASH && b !== PERF_GEO_EM_DASH) return 1;
    if (b === PERF_GEO_EM_DASH && a !== PERF_GEO_EM_DASH) return -1;
    const na = Number(a);
    const nb = Number(b);
    if (!Number.isNaN(na) && !Number.isNaN(nb) && String(na) === String(a) && String(nb) === String(b)) return na - nb;
    return String(a).localeCompare(String(b), undefined, { sensitivity: 'base' });
}

/**
 * True when metadata marks the cell on-air (same rules as Network Map / ``metadata_active_sql``:
 * vendor-specific admin_state / active_state → ``activity_status`` Active | Inactive).
 */
function cellPmOnAir(c) {
    const v = c.activity_status != null ? c.activity_status : c.status;
    return String(v || '').trim().toLowerCase() === 'active';
}

function cellMetadataStatusTitle(onAir) {
    if (onAir) {
        return 'On-air in metadata (Active — matches vendor admin/active rules). PM can still be queried.';
    }
    return 'Inactive in metadata (admin / active-state rules). Symbol reflects metadata, not PM availability.';
}

function perfSidebarToggle(btn) {
    if (!btn) return;
    const panelId = btn.getAttribute('aria-controls');
    const body = panelId && document.getElementById(panelId);
    if (!body) return;
    const open = btn.getAttribute('aria-expanded') === 'true';
    btn.setAttribute('aria-expanded', open ? 'false' : 'true');
    body.hidden = open;
    if (open) {
        body.classList.add('is-collapsed');
        body.style.display = 'none';
    } else {
        body.classList.remove('is-collapsed');
        body.style.display = '';
    }
    const ch = btn.querySelector('.perf-chevron');
    if (ch) ch.textContent = open ? '▶' : '▼';
}

function togglePerfLeftPanel(forceCollapsed = null) {
    const body = document.querySelector('.perf-body');
    const btn = document.getElementById('perf-left-panel-toggle');
    if (!body || !btn) return;
    const next = forceCollapsed == null ? !perfLeftPanelCollapsed : !!forceCollapsed;
    perfLeftPanelCollapsed = next;
    body.classList.toggle('left-collapsed', next);
    btn.textContent = next ? '▶' : '◀';
    btn.setAttribute('aria-expanded', next ? 'false' : 'true');
    btn.setAttribute('title', next ? 'Expand filters' : 'Collapse filters');
}

function _rebuildGeoFiltersFromCells(cells) {
    const siteMap = new Map();
    (cells || []).forEach(c => {
        const sid = c.site_id == null ? '' : String(c.site_id);
        const key = sid || c.cell_name || '';
        if (!siteMap.has(key)) {
            siteMap.set(key, {
                site_id: c.site_id,
                site_name: c.site_name,
                vendor: c.vendor,
                cluster: c.cluster,
                area: c.area,
            });
        }
    });
    allSites = [...siteMap.values()];
    allClusters = [...new Set(allSites.map(s => Number(s.cluster)).filter(n => !Number.isNaN(n)))].sort((a, b) => a - b);
    allAreas = [];
    const seen = new Set();
    allSites.forEach(s => {
        const c = Number(s.cluster);
        const a = (s.area || '').trim();
        if (Number.isNaN(c) || !a) return;
        const k = `${c}::${a}`;
        if (seen.has(k)) return;
        seen.add(k);
        allAreas.push({ cluster: c, area: a });
    });
    _populateClusters(allClusters);
    _populateAreas(allAreas);
    _populateSites(allSites);
}

function showCellPicker(cells, opts = {}) {
    const fromApply = opts && opts.fromApply === true;

    if (fromApply) {
        document.getElementById('btn-refresh').style.display = 'inline-flex';
    }

    if (cells.length) {
        document.getElementById('charts-title').textContent =
            `${cells.length} cell${cells.length !== 1 ? 's' : ''} — pick KPIs, then Query`;
    } else if (fromApply) {
        document.getElementById('charts-title').textContent = 'No cells match these filters';
    } else {
        document.getElementById('charts-title').textContent = _perfDefaultChartsTitle();
    }

    const wrap = document.getElementById('cell-list-wrap');
    const list = document.getElementById('cell-list');
    if (!list || !wrap) return;
    list.innerHTML = '';

    if (!cells.length) {
        list.innerHTML = fromApply
            ? '<p class="perf-tree-empty">No cells match these filters.</p>'
            : '<p class="perf-tree-empty">No cells yet. Choose a <strong>vendor</strong> and <strong>technology</strong> above (cells load automatically).</p>';
        const searchInput = document.getElementById('cell-search');
        if (searchInput) searchInput.value = '';
        _updateCellCountBadge(0, 0);
        onPerfSelectionModeChange();
        return;
    }

    const searchInput = document.getElementById('cell-search');
    if (searchInput) searchInput.value = '';
    _updateCellCountBadge(cells.length, cells.length);

    onPerfSelectionModeChange();

    const byArea = new Map();
    cells.forEach(c => {
        const ak = _perfNormArea(c);
        const ck = _perfNormCluster(c);
        const sid = String(c.site_id != null ? c.site_id : '');
        const siteName = c.site_name || (sid ? `Site ${sid}` : 'Unknown site');
        if (!byArea.has(ak)) byArea.set(ak, new Map());
        const byCluster = byArea.get(ak);
        if (!byCluster.has(ck)) byCluster.set(ck, new Map());
        const bySite = byCluster.get(ck);
        if (!bySite.has(sid)) bySite.set(sid, { site_id: sid, site_name: siteName, cells: [] });
        bySite.get(sid).cells.push(c);
    });

    perfAreaTreeData = byArea;

    const sortedAreas = [...byArea.keys()].sort(_perfSortAreaKeys);
    const areasHtml = sortedAreas.map(areaKey => {
        const byCluster = byArea.get(areaKey);
        const clusterKeys = [...byCluster.keys()].sort(_perfSortClusterKeys);
        let areaCellCount = 0;
        clusterKeys.forEach(ck => {
            byCluster.get(ck).forEach(g => { areaCellCount += g.cells.length; });
        });

        const aTitle = areaKey === PERF_GEO_EM_DASH ? 'No area' : areaKey;
        return `<div class="hw-tree-area" data-area="${escAttr(areaKey)}">
            <div class="hw-tree-node-block">
                <div class="hw-tree-folder-row">
                    <button type="button" class="hw-tree-twisty" aria-expanded="false">+</button>
                    <span class="hw-tree-ico" aria-hidden="true">📁</span>
                    <span class="hw-tree-folder-name" title="${escAttr(aTitle)}">${escHtml(areaKey)}</span>
                    <span class="hw-tree-folder-meta">${areaCellCount}</span>
                </div>
                <div class="hw-tree-children hw-collapsed" data-area-loaded="0"></div>
            </div>
        </div>`;
    }).join('');

    list.innerHTML = `
        <div class="hw-tree" role="tree">
            <div class="hw-tree-node-block hw-tree-root-block">
                <div class="hw-tree-folder-row">
                    <button type="button" class="hw-tree-twisty" aria-expanded="true">−</button>
                    <span class="hw-tree-ico" aria-hidden="true">📁</span>
                    <span class="hw-tree-folder-name">Whole network</span>
                    <span class="hw-tree-folder-meta">${cells.length}</span>
                </div>
                <div class="hw-tree-children hw-tree-root-sites">${areasHtml}</div>
            </div>
        </div>`;
}

function _buildAreaChildrenHtml(areaKey) {
    const byCluster = perfAreaTreeData.get(areaKey);
    if (!byCluster) return '';
    const clusterKeys = [...byCluster.keys()].sort(_perfSortClusterKeys);
    return clusterKeys.map(ck => {
        const bySite = byCluster.get(ck);
        const siteGroups = [...bySite.values()].sort((a, b) =>
            String(a.site_name).localeCompare(String(b.site_name), undefined, { sensitivity: 'base' })
        );
        siteGroups.forEach(g => {
            g.cells.sort((a, b) =>
                String(a.cell_name).localeCompare(String(b.cell_name), undefined, { sensitivity: 'base' })
            );
        });
        const clusterCellCount = siteGroups.reduce((n, g) => n + g.cells.length, 0);
        const cLabel = _perfClusterFolderLabel(ck);

        const sitesHtml = siteGroups.map(site => {
            const siteLeaves = site.cells.map(c => {
                const key = String(c.cell_key || c.cell_id);
                const onAir = cellPmOnAir(c);
                const inactive = onAir ? '' : ' hw-tree-leaf--metadata-inactive';
                const active = key === activeCellId ? ' active' : '';
                const tech = c.technology || '';
                const ds = (c.cell_name + ' ' + site.site_name + ' ' + (c.cluster || '') + ' ' + (c.area || '') + ' ' + tech).toLowerCase();
                const stTitle = escAttr(cellMetadataStatusTitle(onAir));
                return `<div class="hw-tree-leaf${inactive}${active}" role="treeitem" data-cell-key="${escAttr(key)}" data-metadata-on-air="${onAir ? '1' : '0'}" data-search="${escAttr(ds)}">
            <input type="checkbox" class="hw-tree-cb" onclick="event.stopPropagation()" aria-label="Select cell">
            <span class="hw-tree-status hw-tree-status--${onAir ? 'on' : 'off'}" title="${stTitle}" aria-hidden="true"></span>
            <span class="hw-tree-leaf-name">${escHtml(c.cell_name)}</span>
            <span class="hw-tree-leaf-tech">${escHtml(tech)}</span>
        </div>`;
            }).join('');

            return `<div class="hw-tree-site" data-site-id="${escAttr(site.site_id)}">
        <div class="hw-tree-node-block">
            <div class="hw-tree-folder-row">
                <button type="button" class="hw-tree-twisty" aria-expanded="true">−</button>
                <span class="hw-tree-ico" aria-hidden="true">📁</span>
                <span class="hw-tree-folder-name" title="${escAttr(site.site_name)}">${escHtml(site.site_name)}</span>
                <span class="hw-tree-folder-meta">${site.cells.length}</span>
            </div>
            <div class="hw-tree-children">${siteLeaves}</div>
        </div>
    </div>`;
        }).join('');

        return `<div class="hw-tree-cluster" data-cluster="${escAttr(ck)}">
        <div class="hw-tree-node-block">
            <div class="hw-tree-folder-row">
                <button type="button" class="hw-tree-twisty" aria-expanded="true">−</button>
                <span class="hw-tree-ico" aria-hidden="true">📁</span>
                <span class="hw-tree-folder-name" title="${escAttr(cLabel)}">${escHtml(cLabel)}</span>
                <span class="hw-tree-folder-meta">${clusterCellCount}</span>
            </div>
            <div class="hw-tree-children">${sitesHtml}</div>
        </div>
    </div>`;
    }).join('');
}

function _materializeArea(areaEl) {
    if (!areaEl) return;
    const children = areaEl.querySelector(':scope > .hw-tree-node-block > .hw-tree-children');
    if (!children) return;
    if (children.getAttribute('data-area-loaded') === '1') return;
    const areaKey = areaEl.getAttribute('data-area');
    if (!areaKey) return;
    children.innerHTML = _buildAreaChildrenHtml(areaKey);
    children.setAttribute('data-area-loaded', '1');
}

function _materializeAllAreas() {
    document.querySelectorAll('#cell-list .hw-tree-area').forEach(_materializeArea);
}

function filterCellChips(query) {
    const q = query.toLowerCase().trim();
    if (q) _materializeAllAreas();
    const leaves = document.querySelectorAll('#cell-list .hw-tree-leaf');
    let visible = 0;
    leaves.forEach(leaf => {
        const ds = (leaf.getAttribute('data-search') || '').toLowerCase();
        const match = !q || ds.includes(q);
        leaf.style.display = match ? '' : 'none';
        if (match) visible++;
    });
    document.querySelectorAll('#cell-list .hw-tree-site').forEach(siteEl => {
        const any = [...siteEl.querySelectorAll('.hw-tree-leaf')].some(
            l => l.style.display !== 'none'
        );
        siteEl.style.display = any ? '' : 'none';
    });
    document.querySelectorAll('#cell-list .hw-tree-cluster').forEach(el => {
        const any = [...el.querySelectorAll('.hw-tree-site')].some(
            s => s.style.display !== 'none'
        );
        el.style.display = any ? '' : 'none';
    });
    document.querySelectorAll('#cell-list .hw-tree-area').forEach(el => {
        const any = [...el.querySelectorAll('.hw-tree-cluster')].some(
            c => c.style.display !== 'none'
        );
        el.style.display = any ? '' : 'none';
    });
    _updateCellCountBadge(visible, leaves.length);
}

function perfTreeClick(e) {
    if (e.target.closest('.hw-tree-cb')) return;

    const twisty = e.target.closest('.hw-tree-twisty');
    if (twisty) {
        e.preventDefault();
        const row = twisty.closest('.hw-tree-folder-row');
        const block = row && row.parentElement;
        const ch = block && block.querySelector(':scope > .hw-tree-children');
        if (!ch) return;
        const areaEl = twisty.closest('.hw-tree-area');
        if (areaEl) _materializeArea(areaEl);
        const collapsed = ch.classList.toggle('hw-collapsed');
        twisty.textContent = collapsed ? '+' : '−';
        twisty.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
        return;
    }

    const leaf = e.target.closest('.hw-tree-leaf');
    if (leaf) {
        const selType = (document.getElementById('filter-selection-type')?.value || 'cell').trim();
        const key = selType === 'group'
            ? leaf.getAttribute('data-group-ref')
            : leaf.getAttribute('data-cell-key');
        if (!key) return;
        const mode = document.querySelector('input[name="perf-sel-mode"]:checked')?.value || 'single';
        if (mode === 'multiple') {
            const cb = leaf.querySelector('.hw-tree-cb');
            if (cb) cb.checked = !cb.checked;
            return;
        }
        activeCellId = String(key);
        document.querySelectorAll('#cell-list .hw-tree-leaf').forEach(el => {
            const matchCell = (el.getAttribute('data-cell-key') || '') === String(key);
            const matchGroup = (el.getAttribute('data-group-ref') || '') === String(key);
            const match = matchCell || matchGroup;
            el.classList.toggle('active', match);
        });
    }
}

function perfTreeCollapseAll() {
    document.querySelectorAll('#cell-list .hw-tree-children').forEach(ch => {
        ch.classList.add('hw-collapsed');
    });
    document.querySelectorAll('#cell-list .hw-tree-twisty').forEach(btn => {
        btn.textContent = '+';
        btn.setAttribute('aria-expanded', 'false');
    });
}

function perfTreeExpandAll() {
    _materializeAllAreas();
    document.querySelectorAll('#cell-list .hw-tree-children').forEach(ch => {
        ch.classList.remove('hw-collapsed');
    });
    document.querySelectorAll('#cell-list .hw-tree-twisty').forEach(btn => {
        btn.textContent = '−';
        btn.setAttribute('aria-expanded', 'true');
    });
}

function onPerfSelectionModeChange() {
    const wrap = document.getElementById('cell-list-wrap');
    if (!wrap) return;
    const m = document.querySelector('input[name="perf-sel-mode"]:checked');
    if (m && m.value === 'multiple') wrap.classList.add('hw-mode-multiple');
    else wrap.classList.remove('hw-mode-multiple');
}

function _updateCellCountBadge(visible, total) {
    const badge = document.getElementById('cell-count-badge');
    if (!badge) return;
    const selType = (document.getElementById('filter-selection-type')?.value || 'cell').trim();
    const noun = selType === 'group' ? 'groups' : 'cells';
    badge.textContent = visible === total
        ? `${total} ${noun}`
        : `${visible} / ${total} ${noun}`;
}

// ============================================================
// Chart sessions — tabs by query (cell + timeframe + identity); same query updates one tab
// ============================================================

let chartTabs = [];
let activeChartTabId = null;
let _perfChartTabSeq = 1;
let activeKpiCategoryByTabId = {};

function _perfHoursLabel(hoursVal) {
    if (String(hoursVal) === 'full') return 'Full';
    const h = Number(hoursVal);
    if (h === 720) return '30d';
    if (h === 336) return '14d';
    if (h === 168) return '7d';
    if (h === 72) return '72h';
    if (h === 48) return '48h';
    if (h === 24) return '24h';
    return `${h}h`;
}

function _perfChartQuerySig(apiData, hoursVal, treeCellId) {
    const cell = apiData.cell || {};
    return [
        String(treeCellId ?? ''),
        String(hoursVal ?? ''),
        String(cell.cell_name ?? ''),
        String(cell.technology ?? ''),
        String(cell.site_id ?? ''),
        String(cell.vendor ?? ''),
    ].join('\0');
}

function _scrollPerfActiveTabIntoView() {
    const strip = document.getElementById('perf-chart-tabs-strip');
    const el = strip && strip.querySelector('.perf-chart-tab.active');
    if (el) el.scrollIntoView({ inline: 'nearest', behavior: 'smooth', block: 'nearest' });
}

/** New tab only for a new query; same cell + hours + identity replaces that tab’s data. */
function upsertPerfChartTab(apiData, hoursVal, treeCellId, kind) {
    const cell = apiData.cell || {};
    const rawName = cell.cell_name ? String(cell.cell_name) : 'Cell';
    const title = (kind === 'compare' && apiData._compareTitle)
        ? String(apiData._compareTitle)
        : `${rawName} · ${_perfHoursLabel(hoursVal)}`;
    const treeKey = treeCellId != null && String(treeCellId).trim() !== '' ? String(treeCellId) : null;
    const querySig = _perfChartQuerySig(apiData, hoursVal, treeCellId);
    const tabKind = kind === 'compare' ? 'compare' : 'single';

    const existing = chartTabs.find(t => t.querySig === querySig);
    if (existing) {
        existing.payload = apiData;
        existing.title = title;
        existing.kind = tabKind;
        if (treeKey) existing.treeKey = treeKey;
        activeChartTabId = existing.id;
        lastTrendData = apiData;
        renderPerfChartTabs();
        _scrollPerfActiveTabIntoView();
        if (tabKind === 'compare') renderCompareCharts(apiData);
        return;
    }

    const id = 'ct' + _perfChartTabSeq++;
    chartTabs.push({ id, title, payload: apiData, treeKey, querySig, kind: tabKind });
    activeChartTabId = id;
    lastTrendData = apiData;
    renderPerfChartTabs();
    const strip = document.getElementById('perf-chart-tabs-strip');
    if (strip) strip.scrollLeft = strip.scrollWidth;
    if (tabKind === 'compare') renderCompareCharts(apiData);
}

function renderPerfChartTabs() {
    const bar = document.getElementById('perf-chart-tabs-bar');
    const strip = document.getElementById('perf-chart-tabs-strip');
    const kpiCatBar = document.getElementById('perf-kpi-category-tabs-bar');
    const kpiCatStrip = document.getElementById('perf-kpi-category-tabs-strip');
    if (!bar || !strip) return;

    const tView = document.getElementById('pm-table-view');
    if (tView && tView.style.display !== 'none') {
        bar.style.display = 'none';
        if (kpiCatBar) kpiCatBar.style.display = 'none';
        if (kpiCatStrip) kpiCatStrip.innerHTML = '';
        return;
    }

    if (!chartTabs.length) {
        bar.style.display = 'none';
        strip.innerHTML = '';
        if (kpiCatBar) kpiCatBar.style.display = 'none';
        if (kpiCatStrip) kpiCatStrip.innerHTML = '';
        return;
    }

    bar.style.display = 'flex';
    strip.innerHTML = chartTabs.map(tab => {
        const active = tab.id === activeChartTabId;
        return `<div class="perf-chart-tab${active ? ' active' : ''}" role="tab" aria-selected="${active}" data-tab-id="${tab.id}">
            <button type="button" class="perf-chart-tab-activate">${escHtml(tab.title)}</button>
            <button type="button" class="perf-chart-tab-close" title="Close tab" aria-label="Close tab">&times;</button>
        </div>`;
    }).join('');

    strip.querySelectorAll('.perf-chart-tab').forEach(row => {
        const tid = row.getAttribute('data-tab-id');
        const activate = row.querySelector('.perf-chart-tab-activate');
        const closeBtn = row.querySelector('.perf-chart-tab-close');
        if (activate) {
            activate.addEventListener('click', () => switchPerfChartTab(tid));
        }
        if (closeBtn) {
            closeBtn.addEventListener('click', e => {
                e.stopPropagation();
                closePerfChartTab(tid);
            });
        }
    });
}

function switchPerfChartTab(tabId) {
    const tab = chartTabs.find(t => t.id === tabId);
    if (!tab || !tab.payload) return;

    activeChartTabId = tabId;
    lastTrendData = tab.payload;
    perfDodPickerNeedsReset = true;
    const cell = tab.payload.cell || {};
    const key = tab.treeKey
        || (cell.cell_key != null ? String(cell.cell_key) : '')
        || (cell.cell_id != null ? String(cell.cell_id) : '');
    if (key && tab.kind !== 'compare') {
        activeCellId = key;
        document.querySelectorAll('.hw-tree-leaf').forEach(el => {
            const match = (el.getAttribute('data-cell-key') || '') === key
                || (el.getAttribute('data-group-ref') || '') === key;
            el.classList.toggle('active', match);
        });
    }

    document.getElementById('charts-title').textContent = cell.cell_name || 'KPI trends';
    renderPerfChartTabs();

    document.getElementById('no-selection').style.display = 'none';
    document.getElementById('charts-wrap').style.display = 'grid';
    document.getElementById('loading-charts').style.display = 'none';

    if (tab.kind === 'compare') {
        renderCompareCharts(tab.payload);
    } else {
        renderAllCharts(tab.payload.trend || []);
    }
}

function closePerfChartTab(tabId) {
    const idx = chartTabs.findIndex(t => t.id === tabId);
    if (idx < 0) return;

    chartTabs.splice(idx, 1);
    delete activeKpiCategoryByTabId[tabId];

    if (activeChartTabId !== tabId) {
        renderPerfChartTabs();
        return;
    }

    if (chartTabs.length) {
        const next = chartTabs[Math.min(idx, chartTabs.length - 1)];
        switchPerfChartTab(next.id);
        return;
    }

    activeChartTabId = null;
    delete activeKpiCategoryByTabId.__default;
    lastTrendData = null;
    perfChartDisplayMode = 'trend';
    perfDodPickerNeedsReset = true;
    perfDodPickerSig = '';
    perfDodSelectedDateSet.clear();
    _syncPerfDodRadiosFromState();
    const dodBar = document.getElementById('perf-dod-bar');
    if (dodBar) dodBar.style.display = 'none';
    activeCellId = null;
    document.querySelectorAll('.hw-tree-leaf').forEach(el => el.classList.remove('active'));

    Object.values(charts).forEach(c => { try { c.destroy(); } catch (_) { /* noop */ } });
    Object.keys(charts).forEach(k => delete charts[k]);

    const wrap = document.getElementById('charts-wrap');
    if (wrap) {
        wrap.innerHTML = '';
        wrap.style.display = 'none';
    }
    document.getElementById('btn-export').style.display = 'none';
    document.getElementById('charts-title').textContent = _perfDefaultChartsTitle();
    document.getElementById('no-selection').style.display = 'flex';
    renderPerfChartTabs();
}

// ============================================================
// Load charts for a selected cell
// ============================================================

async function loadCellCharts(cellId) {
    if (String(cellId || '').includes(':raw:')) {
        await loadGroupCharts(cellId);
        return;
    }
    activeCellId = String(cellId);
    // Keep current UI selection if the queried cell is not present in the
    // currently rendered tree (can happen with saved-report fallbacks).
    const leaves = [...document.querySelectorAll('.hw-tree-leaf')];
    const hasMatch = leaves.some(
        el => (el.getAttribute('data-cell-key') || '') === String(cellId)
    );
    if (hasMatch) {
        leaves.forEach(el => {
            const match = (el.getAttribute('data-cell-key') || '') === String(cellId);
            el.classList.toggle('active', match);
        });
    }

    document.getElementById('no-selection').style.display   = 'none';
    document.getElementById('charts-wrap').style.display    = 'none';
    document.getElementById('loading-charts').style.display = 'flex';
    document.getElementById('btn-export').style.display     = 'none';
    document.getElementById('btn-refresh').style.display    = 'inline-flex';

    const hours = 'full';

    try {
        const data = await fetchCellTrendData(cellId);

        const cell  = data.cell;
        const trend = data.trend;

        upsertPerfChartTab(data, hours, cellId);
        document.getElementById('charts-title').textContent = cell.cell_name || 'KPI trends';

        renderAllCharts(trend);

    } catch (e) {
        document.getElementById('loading-charts').style.display = 'none';
        document.getElementById('no-selection').style.display   = 'flex';
        document.getElementById('charts-title').textContent   =
            'Error loading data: ' + (e.message || String(e));
    }
}

// ============================================================
// Render charts — 2 per row
// ============================================================

const CHART_X_SKIP = new Set([
    'id', 'cell_name', 'timestamp', 'Date', 'date', 'Time', 'PERIOD_START_TIME',
    'site_id', 'site_name', 'technology', 'vendor', 'cluster', 'area',
    '__time_source',
]);

function _toNumericOrNull(v) {
    if (v === null || v === undefined) return null;
    if (typeof v === 'number') return Number.isFinite(v) ? v : null;
    if (typeof v === 'string') {
        const s = v.trim();
        if (!s) return null;
        // Handle common PM formats: "1,234.56", "98.7", "12"
        const n = Number(s.replace(/,/g, ''));
        return Number.isFinite(n) ? n : null;
    }
    return null;
}

function _defsForTrendRender(trend) {
    let defs = KPI_DEFS;
    if (!defs.length && trend.length) {
        defs = Object.keys(trend[0])
            .filter(k => !CHART_X_SKIP.has(k))
            .map(col => ({ key: col, label: col, unit: '', good: null, warn: null, inverse: false, color: _colorFor(col) }));
    }

    defs = (defs || []).filter(d => d && !CHART_X_SKIP.has(d.key) && !_isMetadataKpiKey(d.key));

    if (trend.length) {
        defs = defs.filter(def => trend.some(r => _toNumericOrNull(r[def.key]) !== null));
    }

    const scopeFromApi = KPI_DEFS.length > 0;
    if (scopeFromApi) {
        defs = defs.filter(def => kpiSelectedKeys.has(def.key));
    }
    return { defs, scopeFromApi };
}

function _kpiCategoryForKey(kpiKey) {
    const key = String(kpiKey || '').trim();
    if (!key) return DEFAULT_KPI_CATEGORY;
    const mapped = KPI_CATEGORY_MAP[key];
    return mapped ? String(mapped).trim() : DEFAULT_KPI_CATEGORY;
}

function _kpiCategoriesFromDefs(defs) {
    const set = new Set();
    for (const def of (defs || [])) {
        set.add(_kpiCategoryForKey(def.key));
    }
    const categories = [...set].filter(Boolean).sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' }));
    if (!categories.length) categories.push(DEFAULT_KPI_CATEGORY);
    if (!categories.includes('All')) categories.unshift('All');
    return categories;
}

function _activeKpiCategoryKey() {
    return activeChartTabId || '__default';
}

function _getActiveKpiCategory() {
    const key = _activeKpiCategoryKey();
    return activeKpiCategoryByTabId[key] || 'All';
}

function _setActiveKpiCategory(category) {
    const key = _activeKpiCategoryKey();
    activeKpiCategoryByTabId[key] = String(category || 'All');
}

function renderKpiCategoryTabs(defs = []) {
    const bar = document.getElementById('perf-kpi-category-tabs-bar');
    const strip = document.getElementById('perf-kpi-category-tabs-strip');
    if (!bar || !strip) return;

    const tView = document.getElementById('pm-table-view');
    if (tView && tView.style.display !== 'none') {
        bar.style.display = 'none';
        strip.innerHTML = '';
        return;
    }
    if (!defs.length) {
        bar.style.display = 'none';
        strip.innerHTML = '';
        return;
    }

    const categories = _kpiCategoriesFromDefs(defs);
    const active = categories.includes(_getActiveKpiCategory()) ? _getActiveKpiCategory() : 'All';
    _setActiveKpiCategory(active);

    strip.innerHTML = categories.map(cat => `
        <button type="button" class="perf-kpi-category-tab${cat === active ? ' active' : ''}"
            data-kpi-category="${escAttr(cat)}">${escHtml(cat)}</button>
    `).join('');
    bar.style.display = 'flex';

    strip.querySelectorAll('.perf-kpi-category-tab').forEach(btn => {
        btn.addEventListener('click', () => {
            const cat = String(btn.getAttribute('data-kpi-category') || 'All').trim();
            _setActiveKpiCategory(cat || 'All');
            if (Array.isArray(lastTrendData?.trend) && lastTrendData.trend.length) {
                renderAllCharts(lastTrendData.trend);
            }
        });
    });
}

function _renderOneKpiChartWithOptions(canvasId, def, trend, chartType) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;

    const compareMode = _isPeriodCompareChartMode();
    if (compareMode) {
        _readPerfDodSelectionsFromDom();
        if (!_perfDodSelectedDateKeysArray().length) return;
    }

    const values = trend.map(r => _toNumericOrNull(r[def.key]));
    const existing = charts[canvasId];
    if (existing) {
        try { existing.destroy(); } catch (_) { /* noop */ }
        delete charts[canvasId];
    }

    if (typeof Chart === 'undefined') {
        console.error('[performance] Chart.js is not loaded – cannot render charts');
        const wrap = canvas.closest('.kpi-chart-canvas-wrap');
        if (wrap) wrap.innerHTML = '<p style="color:#e74c3c;padding:1rem">Chart library failed to load. Check network/CDN access.</p>';
        return;
    }

    const ctx = canvas.getContext('2d');

    try {
        if (compareMode) {
            const mom = _isMomChartMode();
            const { labels, datasets } = mom
                ? _buildMomDatasetsForKpi(trend, def)
                : _buildDodDatasetsForKpi(trend, def);
            if (!datasets.length) return;

            charts[canvasId] = new Chart(ctx, {
                type: chartType,
                data: { labels, datasets },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            display: datasets.length > 1,
                            position: 'bottom',
                            labels: { font: { size: 10 }, boxWidth: 10 },
                        },
                        tooltip: {
                            callbacks: {
                                title: items => mom ? _perfTooltipTitleMom(items) : _perfTooltipTitleDod(items),
                                label: (ctx) => {
                                    const v = ctx.parsed.y;
                                    const period = ctx.dataset.label || '';
                                    return v !== null
                                        ? `${period} · ${def.label}: ${Number(v).toFixed(2)}${def.unit ? ' ' + def.unit : ''}`
                                        : 'N/A';
                                },
                            },
                        },
                    },
                    scales: {
                        x: _perfChartXScaleOptions(trend, !mom),
                        y: _perfChartYScaleOptions(),
                    },
                },
            });
            return;
        }

        const labels = trend.map(r => formatTrendXLabelHierarchy(trendXRaw(r)));
        const pointColors = values.map((v) => {
            if (v === null || v === undefined) return '#bdc3c7';
            const c = kpiClass(v, def);
            return c === 'good' ? '#27ae60' : c === 'warn' ? '#f39c12' : c === 'bad' ? '#e74c3c' : def.color;
        });

        charts[canvasId] = new Chart(ctx, {
            type: chartType,
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
                    fill: chartType === 'line',
                    spanGaps: true,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            title: items => _perfTooltipTitleTrend(trend, items),
                            label: (ctx) => {
                                const v = ctx.parsed.y;
                                return v !== null
                                    ? `${def.label}: ${Number(v).toFixed(2)}${def.unit ? ' ' + def.unit : ''}`
                                    : 'N/A';
                            },
                        },
                    },
                },
                scales: {
                    x: _perfChartXScaleOptions(trend, false),
                    y: _perfChartYScaleOptions(),
                },
            },
        });
    } catch (err) {
        console.error('[performance] Chart render failed for', def.key, err);
    }
}

function onPerfKpiChartTypeChange(selectEl) {
    const canvasId = selectEl?.getAttribute('data-canvas-id') || '';
    const kpiKey = selectEl?.getAttribute('data-kpi-key') || '';
    const chartType = selectEl?.value === 'bar' ? 'bar' : 'line';
    const trend = lastTrendData?.trend;
    if (!canvasId || !kpiKey || !Array.isArray(trend) || !trend.length) return;

    const { defs } = _defsForTrendRender(trend);
    const def = defs.find(d => d.key === kpiKey);
    if (!def) return;

    _renderOneKpiChartWithOptions(canvasId, def, trend, chartType);
}

function renderAllCharts(trend) {
    Object.values(charts).forEach(c => { try { c.destroy(); } catch (_) { /* noop */ } });
    Object.keys(charts).forEach(k => delete charts[k]);

    const wrap = document.getElementById('charts-wrap');
    wrap.innerHTML = '';

    const { defs, scopeFromApi } = _defsForTrendRender(trend);

    if (!defs.length) {
        const trendKeys = trend.length ? Object.keys(trend[0]) : [];
        console.warn('[performance] renderAllCharts: 0 defs after filter.',
            'scopeFromApi:', scopeFromApi,
            'KPI_DEFS.length:', KPI_DEFS.length,
            'kpiSelectedKeys.size:', kpiSelectedKeys.size,
            'trend rows:', trend.length,
            'trend columns:', trendKeys);
        const msg = scopeFromApi && kpiSelectedKeys.size === 0
            ? 'Select one or more KPIs in the list under the cell tree.'
            : 'No KPI data available yet.';
        wrap.innerHTML = `<p style="padding:1rem;color:#888">${msg}</p>`;
        document.getElementById('loading-charts').style.display = 'none';
        wrap.style.display = 'grid';
        _syncPerfDodBar();
        return;
    }

    const activeCategory = _getActiveKpiCategory();
    renderKpiCategoryTabs(defs);
    const scopedDefs = activeCategory === 'All'
        ? defs
        : defs.filter(def => _kpiCategoryForKey(def.key) === activeCategory);
    const finalDefs = scopedDefs.length ? scopedDefs : defs;
    const chartType = 'line';
    const renderSeq = ++_perfChartRenderSeq;

    if (_isPeriodCompareChartMode()) {
        _readPerfDodSelectionsFromDom();
        if (!_perfDodSelectedDateKeysArray().length) {
            const noun = _isMomChartMode() ? 'month' : 'day';
            const label = _isMomChartMode() ? 'MOM' : 'DOD';
            wrap.innerHTML = `<p class="perf-dod-empty">Select at least one ${noun} to plot ${label} charts.</p>`;
            document.getElementById('loading-charts').style.display = 'none';
            wrap.style.display = 'grid';
            _syncPerfDodBar();
            return;
        }
    }

    finalDefs.forEach((def, idx) => {
        const values   = trend.map(r => _toNumericOrNull(r[def.key]));
        const canvasId = `chartCnv${renderSeq}_${idx}`;

        const card = document.createElement('div');
        card.className = 'kpi-chart-card';
        card.innerHTML = `
            <div class="kpi-chart-top-controls">
                <select class="perf-report-select kpi-chart-type-sel"
                    data-canvas-id="${escAttr(canvasId)}"
                    data-kpi-key="${escAttr(def.key)}"
                    title="Chart type"
                    aria-label="Chart type"
                    onchange="onPerfKpiChartTypeChange(this)">
                    <option value="line" selected>Line</option>
                    <option value="bar">Bar</option>
                </select>
                <button type="button" class="chart-gear-btn" title="Chart settings" onclick="openChartConfigModal()">⚙</button>
            </div>
            <div class="kpi-chart-title">
                <span class="kpi-chart-name">${escHtml(def.label)}</span>
            </div>
            <div class="kpi-chart-canvas-wrap">
                <canvas id="${canvasId}"></canvas>
            </div>
        `;
        wrap.appendChild(card);

        _renderOneKpiChartWithOptions(canvasId, def, trend, chartType);
    });

    document.getElementById('loading-charts').style.display = 'none';
    wrap.style.display = 'grid';
    _syncPerfDodBar();
}

// ============================================================
// Refresh
// ============================================================

async function triggerPipelineActivationForCurrentScope() {
    const scope = _currentDataScope(); // hourly | daily
    const selectionType = (document.getElementById('filter-selection-type')?.value || 'cell').trim();
    let endpoint = '/api/sync/trigger/cells_hourly';
    if (scope === 'daily') {
        endpoint = selectionType === 'group'
            ? '/api/sync/trigger/groups_daily'
            : '/api/sync/trigger/cells_daily';
    } else {
        endpoint = selectionType === 'group'
            ? '/api/sync/trigger/groups_hourly'
            : '/api/sync/trigger/cells_hourly';
    }
    try {
        const res = await fetch(endpoint, { method: 'POST' });
        if (!res.ok) {
            console.warn('[performance] pipeline trigger rejected', endpoint, res.status);
            return;
        }
        const data = await res.json().catch(() => ({}));
        if (!data.success) {
            console.warn('[performance] pipeline trigger failed', endpoint, data.error || data.message || 'unknown');
        }
    } catch (err) {
        console.warn('[performance] pipeline trigger error', endpoint, err);
    }
}

async function refreshData() {
    const btn = document.getElementById('btn-refresh');
    if (btn) {
        btn.disabled = true;
        btn.querySelector('.refresh-icon').classList.add('spinning');
    }
    try {
        // Kick off backend pull+load for the current analytics scope.
        await triggerPipelineActivationForCurrentScope();
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
    if (!hwLastTablePayload || !Array.isArray(hwLastTablePayload.rows) || !hwLastTablePayload.rows.length) return;
    const cols = Array.isArray(hwLastTablePayload.columns) ? hwLastTablePayload.columns : [];
    const rows = hwLastTablePayload.rows;
    if (!cols.length) return;

    const escape = v => {
        if (v === null || v === undefined) return '';
        const s = String(v);
        return s.includes(',') || s.includes('"') || s.includes('\n')
            ? `"${s.replace(/"/g, '""')}"` : s;
    };

    const lines = [];
    lines.push(cols.map(escape).join(','));
    rows.forEach(row => {
        lines.push(cols.map(c => escape(row[c])).join(','));
    });

    const blob = new Blob([lines.join('\r\n')], { type: 'text/csv;charset=utf-8;' });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href     = url;
    a.download = `pm_table_export_${new Date().toISOString().replace(/[:.]/g, '-')}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

// ============================================================
// PM Database table view
// ============================================================

/** Escape a string for safe insertion into innerHTML. */
function _esc(str) {
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

/**
 * Switch between Charts and PM Database modes.
 * @param {'charts'|'table'} mode
 */
function switchViewMode(mode) {
    const noSel     = document.getElementById('no-selection');
    const cWrap     = document.getElementById('charts-wrap');
    const cLoad     = document.getElementById('loading-charts');
    const tView     = document.getElementById('pm-table-view');
    const btnC      = document.getElementById('btn-charts-view');
    const btnT      = document.getElementById('btn-table-view');
    const exportBtn = document.getElementById('btn-export');

    if (mode === 'table') {
        const tabBar = document.getElementById('perf-chart-tabs-bar');
        const catBar = document.getElementById('perf-kpi-category-tabs-bar');
        const catStrip = document.getElementById('perf-kpi-category-tabs-strip');
        if (tabBar) tabBar.style.display = 'none';
        if (catBar) catBar.style.display = 'none';
        if (catStrip) catStrip.innerHTML = '';
        if (noSel)     noSel.style.display     = 'none';
        if (cWrap)     cWrap.style.display     = 'none';
        if (cLoad)     cLoad.style.display     = 'none';
        if (exportBtn) {
            const hasRows = !!(hwLastTablePayload && Array.isArray(hwLastTablePayload.rows) && hwLastTablePayload.rows.length);
            exportBtn.style.display = hasRows ? 'inline-flex' : 'none';
        }
        tView.style.display = 'flex';
        btnC && btnC.classList.remove('active');
        btnT && btnT.classList.add('active');

        // Clear search bar
        hwCurrentSearch = '';
        const searchInput = document.getElementById('hw-search');
        if (searchInput) searchInput.value = '';

        const vendor = document.getElementById('filter-vendor').value;
        const tech   = document.getElementById('filter-tech').value;
        if (vendor && tech) {
            loadPmTable(vendor, tech, '', 1, hwCurrentScopedCellNames);
        } else {
            document.getElementById('hw-table-container').innerHTML =
                '<p class="hw-empty-msg" style="color:#e74c3c">Select a vendor and technology first.</p>';
        }
    } else {
        if (exportBtn) exportBtn.style.display = 'none';
        tView.style.display = 'none';
        btnC && btnC.classList.add('active');
        btnT && btnT.classList.remove('active');

        renderPerfChartTabs();
        if (chartTabs.length && activeChartTabId) {
            switchPerfChartTab(activeChartTabId);
        } else if (lastQueryCellKeys.length && !chartTabs.length) {
            _perfQueryUserMessage('Choose Template Charts or Add Chart to visualize this query.');
            _setPerfChartChoiceVisible(true);
        } else if (activeCellId && cWrap) {
            cWrap.style.display = 'grid';
            if (noSel) noSel.style.display = 'none';
        } else {
            if (noSel) noSel.style.display = 'flex';
            if (cWrap) cWrap.style.display = 'none';
        }
    }
}

/**
 * Fetch a page of PM raw data from the server and render it.
 */
async function loadPmTable(vendor, technology, search, page, scopedCellNames = null) {
    hwCurrentVendor = vendor;
    hwCurrentTech   = technology;
    hwCurrentSearch = search;
    hwCurrentPage   = page;
    if (scopedCellNames !== null) {
        hwCurrentScopedCellNames = Array.isArray(scopedCellNames) ? scopedCellNames.filter(Boolean) : [];
    }

    const container = document.getElementById('hw-table-container');
    container.innerHTML = '<div style="padding:20px;color:#999">Loading…</div>';
    hwLastTablePayload = null;

    const params = new URLSearchParams({ vendor, technology, page, page_size: HW_PAGE_SIZE });
    if (search) params.set('search', search);
    params.set('data_scope', _currentDataScope());
    (hwCurrentScopedCellNames || []).forEach(n => params.append('cell_name', n));
    (hwCurrentScopedGroupRefs || []).forEach(g => params.append('group_ref', g));

    try {
        const res  = await fetch('/api/performance/pm-table?' + params);
        const data = await res.json();
        if (!data.success) throw new Error(data.error || 'Server error');
        renderPmTable(data);
    } catch (e) {
        container.innerHTML =
            `<div style="padding:20px;color:#e74c3c">Error: ${_esc(e.message)}</div>`;
        const exportBtn = document.getElementById('btn-export');
        if (exportBtn) exportBtn.style.display = 'none';
    }
}

/**
 * Render the PM data table from an API response object.
 */
function renderPmTable(data) {
    const container  = document.getElementById('hw-table-container');
    const pagination = document.getElementById('hw-pagination');
    const countEl    = document.getElementById('hw-row-count');

    hwLastTablePayload = data;
    const { columns, static_cols, column_labels, rows, total, page, page_size, cell_label } = data;
    const staticSet = new Set(static_cols);

    // Update row count badge
    const start = total ? (page - 1) * page_size + 1 : 0;
    const end   = Math.min(page * page_size, total);
    countEl.textContent = total
        ? `${start.toLocaleString()}–${end.toLocaleString()} of ${total.toLocaleString()} rows`
        : '0 rows';

    // Update search placeholder to show the right cell label
    const searchInput = document.getElementById('hw-search');
    if (searchInput && cell_label) searchInput.placeholder = `Search by ${cell_label}…`;

    if (!rows.length) {
        container.innerHTML = '<div class="hw-empty-msg">No data found.</div>';
        pagination.innerHTML = '';
        const exportBtn = document.getElementById('btn-export');
        if (exportBtn) exportBtn.style.display = 'none';
        return;
    }
    const exportBtn = document.getElementById('btn-export');
    if (exportBtn) exportBtn.style.display = 'inline-flex';

    // Build <thead>
    const colHeaders = columns.map(col => {
        const isStatic = staticSet.has(col);
        const label    = column_labels[col] || col;
        return `<th class="${isStatic ? 'hw-static' : ''}">${_esc(label)}</th>`;
    }).join('');

    // Build <tbody>
    const tableRows = rows.map(row => {
        const cells = columns.map(col => {
            const v        = row[col];
            const isStatic = staticSet.has(col);
            let display;
            if (v === null || v === undefined) {
                display = '';
            } else if (typeof v === 'number') {
                display = Number.isInteger(v) ? String(v) : v.toFixed(4);
            } else {
                display = _esc(String(v));
            }
            return `<td class="${isStatic ? 'hw-static-cell' : ''}">${display}</td>`;
        }).join('');
        return `<tr>${cells}</tr>`;
    }).join('');

    container.innerHTML = `
        <div class="hw-table-wrapper">
            <table class="hw-table">
                <thead><tr>${colHeaders}</tr></thead>
                <tbody>${tableRows}</tbody>
            </table>
        </div>`;

    // Build pagination controls
    const totalPages = Math.ceil(total / page_size);
    if (totalPages <= 1) { pagination.innerHTML = ''; return; }

    const pages = [];
    for (let i = 1; i <= totalPages; i++) {
        if (i === 1 || i === totalPages || (i >= page - 2 && i <= page + 2)) {
            pages.push(i);
        } else if (pages[pages.length - 1] !== '…') {
            pages.push('…');
        }
    }

    // Use global vars in onclick so search strings with special chars don't break
    pagination.innerHTML =
        `<button ${page === 1 ? 'disabled' : ''}
            onclick="loadPmTable(hwCurrentVendor,hwCurrentTech,hwCurrentSearch,${page - 1})">← Prev</button>` +
        pages.map(p =>
            p === '…'
                ? `<span class="hw-ellipsis">…</span>`
                : `<button class="${p === page ? 'hw-page-active' : ''}"
                    onclick="loadPmTable(hwCurrentVendor,hwCurrentTech,hwCurrentSearch,${p})">${p}</button>`
        ).join('') +
        `<button ${page === totalPages ? 'disabled' : ''}
            onclick="loadPmTable(hwCurrentVendor,hwCurrentTech,hwCurrentSearch,${page + 1})">Next →</button>`;
}

/** Debounced handler for the search input. */
function onHwSearch(value) {
    clearTimeout(hwSearchTimer);
    hwSearchTimer = setTimeout(() => {
        if (hwCurrentVendor && hwCurrentTech) {
            loadPmTable(hwCurrentVendor, hwCurrentTech, value.trim(), 1);
        }
    }, 400);
}

async function onDataScopeChange() {
    perfChartDisplayMode = 'trend';
    perfDodPickerNeedsReset = true;
    perfDodPickerSig = '';
    perfDodSelectedDateSet.clear();
    _syncPerfDodRadiosFromState();

    _resetObjectScopeFilters();
    lastQueryCellKeys = [];
    hwCurrentScopedCellNames = [];
    hwCurrentScopedGroupRefs = [];
    _setPerfChartChoiceVisible(false);
    await loadKpiHeaderMap();
    await loadKpiColumns();
    await loadCellGroups();
    await maybeAutoReloadCells();
}

document.addEventListener('DOMContentLoaded', () => {
    const tree = document.getElementById('cell-list');
    if (tree) tree.addEventListener('click', perfTreeClick);
    const kpiList = document.getElementById('kpi-scope-list');
    if (kpiList) {
        kpiList.addEventListener('change', e => {
            if (e.target && e.target.classList && e.target.classList.contains('kpi-scope-cb')) {
                onKpiSelectionChange();
            }
        });
    }
    const kpiSelectAll = document.getElementById('kpi-select-all');
    if (kpiSelectAll) {
        kpiSelectAll.addEventListener('change', e => onKpiSelectAllToggle(!!e.target.checked));
    }
    showCellPicker([], { fromApply: false });
    onSelectionTypeChange();
    setPerfBottomMode('kpis');
    ensureKpiCategoryConfigLoaded();
    perfPmViewPrefPromise = loadPmViewPreference();
});

// ============================================================
// Saved Views adapter (delegates to existing report-config helpers)
// ============================================================

function getPerformanceState() {
    return {
        v: 1,
        config: _captureCurrentReportConfig(),
        bottom_mode: (typeof perfBottomMode !== 'undefined' ? perfBottomMode : 'kpis'),
    };
}

async function applyPerformanceState(state /* , opts */) {
    if (!state || typeof state !== 'object') return;
    const cfg = (state.config && typeof state.config === 'object') ? state.config : null;
    if (!cfg) return;
    try {
        await _applyReportConfig(cfg);
    } catch (e) {
        console.warn('[performance] applyPerformanceState failed', e);
    }
    if (state.bottom_mode === 'reports' || state.bottom_mode === 'kpis') {
        try { setPerfBottomMode(state.bottom_mode); } catch (_) { /* ignore */ }
    }
}

window.getPerformanceState = getPerformanceState;
window.applyPerformanceState = applyPerformanceState;

// ============================================================
// Multi-cell comparison (overlay up to 6 cells per KPI)
// ============================================================

const PERF_COMPARE_MAX_CELLS = 6;
const PERF_COMPARE_COLORS = [
    '#1f77b4', '#e74c3c', '#27ae60', '#f39c12',
    '#9b59b6', '#16a085', '#34495e', '#d35400',
];

async function addCompareTabFromLastQuery() {
    if (!Array.isArray(lastQueryCellKeys) || !lastQueryCellKeys.length) {
        _perfQueryUserMessage('Run Query first with multiple cells, then click Compare Cells.');
        return;
    }
    if (KPI_DEFS.length && kpiSelectedKeys.size === 0) {
        _perfQueryUserMessage('Select at least one KPI to compare.');
        return;
    }

    // Comparison only makes sense for cell-level selection (not group rollups).
    const cellKeys = lastQueryCellKeys
        .map(k => String(k || '').trim())
        .filter(k => k && !k.includes(':raw:'));
    if (cellKeys.length < 2) {
        _perfQueryUserMessage('Select two or more cells (Multiple mode), then run Query, then Compare Cells.');
        return;
    }

    const limited = cellKeys.slice(0, PERF_COMPARE_MAX_CELLS);
    if (cellKeys.length > PERF_COMPARE_MAX_CELLS) {
        showNotification(`Comparing first ${PERF_COMPARE_MAX_CELLS} of ${cellKeys.length} cells.`, 'info');
    }

    const noSel = document.getElementById('no-selection');
    if (noSel) noSel.style.display = 'none';
    const wrap = document.getElementById('charts-wrap');
    if (wrap) wrap.style.display = 'none';
    const loading = document.getElementById('loading-charts');
    if (loading) loading.style.display = 'flex';

    const cells = [];
    for (const key of limited) {
        try {
            const data = await fetchCellTrendData(key);
            const trend = Array.isArray(data.trend) ? data.trend : [];
            if (!trend.length) continue;
            cells.push({
                key,
                cell: data.cell || { cell_name: key },
                trend,
            });
        } catch (_) {
            // Skip cells with no trend data; continue with others.
        }
    }

    if (loading) loading.style.display = 'none';

    if (cells.length < 2) {
        _perfQueryUserMessage('Could not load trend data for at least two of the selected cells.');
        return;
    }

    const payload = {
        kind: 'compare',
        cells,
        normalize: false,
        // Synthetic single-cell payload for the rest of the UI plumbing
        // (axis labels, KPI category tabs, etc. read from `trend`).
        cell: {
            cell_name: `Compare · ${cells.length} cells`,
            vendor: cells[0].cell.vendor || '',
            technology: cells[0].cell.technology || '',
            site_id: '',
        },
        trend: cells[0].trend,
    };

    const titleSuffix = `Compare · ${cells.length}`;
    const compareKey = `__compare__::${cells.map(c => c.key).join('||')}`;
    upsertPerfChartTab({ ...payload, _compareTitle: titleSuffix }, 'compare', compareKey, 'compare');
    switchViewMode('charts');
}

/**
 * Build a unified timestamp axis (union, sorted) for all cells.
 * @param {Array<{trend: Array}>} cells
 * @returns {{labels: string[], rawKeys: string[]}}
 */
function _perfCompareAxis(cells) {
    const set = new Map();
    cells.forEach(({ trend }) => {
        (trend || []).forEach((row) => {
            const raw = trendXRaw(row);
            const key = String(raw == null ? '' : raw);
            if (!set.has(key)) set.set(key, raw);
        });
    });
    const keys = [...set.keys()].sort((a, b) => {
        const da = Date.parse(a);
        const db = Date.parse(b);
        if (Number.isFinite(da) && Number.isFinite(db)) return da - db;
        return String(a).localeCompare(String(b));
    });
    const labels = keys.map(k => formatTrendXLabelHierarchy(set.get(k)));
    return { labels, rawKeys: keys };
}

function _perfCompareValuesForCell(cell, kpiKey, rawKeys) {
    const map = new Map();
    (cell.trend || []).forEach((row) => {
        const raw = trendXRaw(row);
        const key = String(raw == null ? '' : raw);
        const v = _toNumericOrNull(row[kpiKey]);
        if (!map.has(key)) map.set(key, v);
    });
    return rawKeys.map(k => (map.has(k) ? map.get(k) : null));
}

function _perfCompareNormalize(values) {
    let max = 0;
    for (const v of values) {
        if (v == null) continue;
        const a = Math.abs(Number(v));
        if (Number.isFinite(a) && a > max) max = a;
    }
    if (max <= 0) return values;
    return values.map(v => (v == null ? null : Number(v) / max));
}

function _perfCompareCellShortLabel(cell) {
    const c = cell.cell || {};
    return c.cell_name || c.cell_id || cell.key || 'Cell';
}

function renderCompareCharts(payload) {
    Object.values(charts).forEach(c => { try { c.destroy(); } catch (_) { /* noop */ } });
    Object.keys(charts).forEach(k => delete charts[k]);

    const wrap = document.getElementById('charts-wrap');
    wrap.innerHTML = '';

    const cells = Array.isArray(payload?.cells) ? payload.cells : [];
    const normalize = !!payload.normalize;

    const sampleTrend = cells.reduce((arr, c) => arr.length >= (c.trend?.length || 0) ? arr : c.trend, []);
    const { defs } = _defsForTrendRender(sampleTrend);
    if (!defs.length) {
        wrap.innerHTML = '<p style="padding:1rem;color:#888">Select one or more KPIs to compare.</p>';
        document.getElementById('loading-charts').style.display = 'none';
        wrap.style.display = 'grid';
        return;
    }

    renderKpiCategoryTabs(defs);
    const activeCategory = _getActiveKpiCategory();
    const scopedDefs = activeCategory === 'All'
        ? defs
        : defs.filter(def => _kpiCategoryForKey(def.key) === activeCategory);
    const finalDefs = scopedDefs.length ? scopedDefs : defs;

    // Header row with compare-specific controls (cell legend + normalize toggle).
    const header = document.createElement('div');
    header.className = 'perf-compare-header';
    const legend = cells.map((c, idx) => {
        const color = PERF_COMPARE_COLORS[idx % PERF_COMPARE_COLORS.length];
        return `<span class="perf-compare-legend-item">
            <span class="perf-compare-legend-swatch" style="background:${color}"></span>
            ${escHtml(_perfCompareCellShortLabel(c))}
        </span>`;
    }).join('');
    header.innerHTML = `
        <div class="perf-compare-legend">${legend}</div>
        <label class="perf-compare-norm">
            <input type="checkbox" id="perf-compare-norm-toggle" ${normalize ? 'checked' : ''}>
            Normalize axes (per-cell scale to 0–1 of its peak)
        </label>
    `;
    wrap.appendChild(header);

    const renderSeq = ++_perfChartRenderSeq;
    const axis = _perfCompareAxis(cells);

    finalDefs.forEach((def, idx) => {
        const canvasId = `cmpCnv${renderSeq}_${idx}`;
        const card = document.createElement('div');
        card.className = 'kpi-chart-card';
        card.innerHTML = `
            <div class="kpi-chart-title">
                <span class="kpi-chart-name">${escHtml(def.label)}</span>
                ${normalize ? '<span class="perf-compare-norm-badge">normalized</span>' : ''}
            </div>
            <div class="kpi-chart-canvas-wrap">
                <canvas id="${canvasId}"></canvas>
            </div>
        `;
        wrap.appendChild(card);

        const datasets = cells.map((c, ci) => {
            const color = PERF_COMPARE_COLORS[ci % PERF_COMPARE_COLORS.length];
            let values = _perfCompareValuesForCell(c, def.key, axis.rawKeys);
            if (normalize) values = _perfCompareNormalize(values);
            return {
                label: _perfCompareCellShortLabel(c),
                data: values,
                borderColor: color,
                backgroundColor: color + '22',
                pointBackgroundColor: color,
                pointRadius: axis.rawKeys.length > 48 ? 1.5 : 2.5,
                pointHoverRadius: 5,
                borderWidth: 2,
                tension: 0.25,
                fill: false,
                spanGaps: true,
            };
        });

        const canvas = document.getElementById(canvasId);
        if (!canvas || typeof Chart === 'undefined') return;
        const ctx = canvas.getContext('2d');
        try {
            charts[canvasId] = new Chart(ctx, {
                type: 'line',
                data: { labels: axis.labels, datasets },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: true, position: 'bottom', labels: { font: { size: 10 }, boxWidth: 10 } },
                        tooltip: {
                            callbacks: {
                                label: (item) => {
                                    const v = item.parsed.y;
                                    if (v == null) return `${item.dataset.label}: N/A`;
                                    const formatted = normalize
                                        ? Number(v).toFixed(3)
                                        : `${Number(v).toFixed(2)}${def.unit ? ' ' + def.unit : ''}`;
                                    return `${item.dataset.label}: ${formatted}`;
                                },
                            },
                        },
                    },
                    scales: {
                        x: {
                            ticks: { color: _perfChartTheme().tick, font: { size: 10 }, maxRotation: 0, autoSkip: true },
                            grid: { color: _perfChartTheme().grid },
                        },
                        y: _perfChartYScaleOptions(normalize ? { suggestedMin: 0, suggestedMax: 1 } : {}),
                    },
                },
            });
        } catch (err) {
            console.error('[performance] compare chart render failed for', def.key, err);
        }
    });

    document.getElementById('loading-charts').style.display = 'none';
    wrap.style.display = 'grid';

    const normToggle = document.getElementById('perf-compare-norm-toggle');
    if (normToggle) {
        normToggle.addEventListener('change', () => {
            payload.normalize = !!normToggle.checked;
            renderCompareCharts(payload);
        });
    }
}
