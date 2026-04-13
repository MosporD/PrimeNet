/**
 * Performance Analytics v5
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
let filteredSites = [];

let KPI_DEFS = [];
let perfAreaTreeData = new Map();
let KPI_HEADER_MAP = {};

/** Keys from the KPI scope list that are selected for charts / export */
let kpiSelectedKeys = new Set();
let _kpiColumnsSig = '';
let allCellGroups = [];
let performanceReports = [];
let perfBottomMode = 'kpis';

// ── PM table view state ──────────────────────────────────
let hwCurrentPage   = 1;
let hwCurrentSearch = '';
let hwCurrentTech   = '';
let hwCurrentVendor = '';
let hwSearchTimer   = null;
const HW_PAGE_SIZE  = 100;

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

async function loadKpiHeaderMap() {
    try {
        const res = await fetch('/api/performance/kpi_headers_map', { credentials: 'same-origin' });
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
            <span class="kpi-scope-item-label">${escHtml(c)}</span>
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
        const v = (document.getElementById('filter-vendor')?.value || '').trim();
        const t = (document.getElementById('filter-tech')?.value || '').trim();

        const params = new URLSearchParams();
        if (v) params.set('vendor', v);
        if (t) params.set('technology', t);
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

        KPI_DEFS = all.map(col => ({
            key:     col,
            label:   col,
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

/** PM trend row: Huawei charts use ``Date`` when present (grid “Date” column), else ``timestamp``. */
function trendXRaw(row) {
    if (!row) return null;
    const v = row.Date ?? row.date ?? row.timestamp;
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

    // Clusters (numeric)
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
        kpi_keys: [...kpiSelectedKeys],
        hours: (document.getElementById('filter-hours')?.value || '168').trim(),
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

async function _applyReportConfig(cfg) {
    const setVal = (id, val) => {
        const el = document.getElementById(id);
        if (!el || val == null) return;
        el.value = String(val);
    };
    setVal('filter-vendor', cfg.vendor || '');
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
    }
    setVal('filter-hours', cfg.hours || '168');
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
            o.textContent = `${g.name} (${g.vendor || 'N/A'} · ${n})`;
            sel.appendChild(o);
        });
        if (prev && [...sel.options].some(o => o.value === prev)) sel.value = prev;
    } catch (_) {
        // Keep UI usable even if group DB is not ready.
    }
}

function onSelectionTypeChange() {
    const type = (document.getElementById('filter-selection-type')?.value || 'cell').trim();
    const groupWrap = document.getElementById('group-picker-wrap');
    const cellsBody = document.getElementById('perf-cells-body');
    if (groupWrap) groupWrap.style.display = type === 'group' ? 'flex' : 'none';
    if (cellsBody) cellsBody.style.display = type === 'group' ? 'none' : '';
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
    }
    const areaSel = document.getElementById('filter-area');
    const clusterSel = document.getElementById('filter-cluster');
    if (areaSel && areaSel.tagName === 'SELECT') areaSel.value = '';
    if (clusterSel && clusterSel.tagName === 'SELECT') clusterSel.value = '';

    await loadKpiColumns();
    await loadCellGroups();
    await maybeAutoReloadCells();
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

    if (KPI_DEFS.length && kpiSelectedKeys.size === 0) {
        _perfQueryUserMessage('Select at least one KPI to chart.');
        return;
    }

    let keys = [];
    if (selectionType === 'group') {
        const groupId = (document.getElementById('filter-group')?.value || '').trim();
        if (!groupId) {
            _perfQueryUserMessage('Select a cell group first, then click Query.');
            return;
        }
        const params = new URLSearchParams();
        if (v) params.set('vendor', v);
        if (t) params.set('technology', t);
        try {
            const res = await fetch(`/api/performance/groups/${encodeURIComponent(groupId)}/cell_keys?${params.toString()}`);
            const data = await res.json();
            if (!data.success) {
                _perfQueryUserMessage(data.error || 'Could not load group cells.');
                return;
            }
            keys = (data.cell_keys || []).map(r =>
                [r.vendor || '', r.technology || '', r.site_id || '', r.cell_name || ''].join('||')
            );
        } catch (e) {
            _perfQueryUserMessage('Could not load group cells: ' + (e.message || String(e)));
            return;
        }
    } else {
        const mode = document.querySelector('input[name="perf-sel-mode"]:checked')?.value || 'single';
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
        _perfQueryUserMessage(mode === 'multiple'
            ? 'Check one or more cells in the tree, then click Query.'
            : 'Click a cell in the tree to select it, then click Query.');
        return;
    }

    for (const k of keys) {
        await loadCellCharts(k);
    }
}

async function onPerfTimeWindowChange() {
    if (!chartTabs.length) return;
    const keys = [...new Set(chartTabs.map(t => t.treeKey).filter(Boolean))];
    if (!keys.length) return;
    for (const k of keys) {
        await loadCellCharts(k);
    }
}

/** PM data is hourly only; API always uses this granularity. */
const PERF_TREND_GRANULARITY = 'hour';

/**
 * @param {{ skipAutoChart?: boolean, skipKpiColumns?: boolean }} opts
 *  skipAutoChart: do not jump straight to chart when filter-cell is set (scope refresh from UI).
 *  skipKpiColumns: avoid duplicate KPI column fetch when caller just ran loadKpiColumns.
 */
async function applyFilters(opts = {}) {
    if (!opts.skipKpiColumns) await loadKpiColumns();

    const vendor  = document.getElementById('filter-vendor').value;
    const tech    = document.getElementById('filter-tech').value;
    const cluster = document.getElementById('filter-cluster').value;
    const area    = document.getElementById('filter-area').value;
    const site    = document.getElementById('filter-site').value;
    const cell    = document.getElementById('filter-cell').value;

    if (cell && !opts.skipAutoChart) {
        _resetPerfChartStateForNewScope();
        await loadCellCharts(cell);
        return;
    }

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

/** Metadata on-air flag from performance /cells API */
function cellPmOnAir(c) {
    const v = c.activity_status != null ? c.activity_status : c.status;
    return String(v || '').trim().toLowerCase() === 'active';
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
                const active = key === activeCellId ? ' active' : '';
                const tech = c.technology || '';
                const ds = (c.cell_name + ' ' + site.site_name + ' ' + (c.cluster || '') + ' ' + (c.area || '') + ' ' + tech).toLowerCase();
                return `<div class="hw-tree-leaf${active}" role="treeitem" data-cell-key="${escAttr(key)}" data-search="${escAttr(ds)}">
            <input type="checkbox" class="hw-tree-cb" onclick="event.stopPropagation()" aria-label="Select cell">
            <span class="hw-tree-status hw-tree-status--${onAir ? 'on' : 'off'}" title="${onAir ? 'On-air' : 'Offline / inactive'}"></span>
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
        const key = leaf.getAttribute('data-cell-key');
        if (!key) return;
        const mode = document.querySelector('input[name="perf-sel-mode"]:checked')?.value || 'single';
        if (mode === 'multiple') {
            const cb = leaf.querySelector('.hw-tree-cb');
            if (cb) cb.checked = !cb.checked;
            return;
        }
        activeCellId = String(key);
        document.querySelectorAll('#cell-list .hw-tree-leaf').forEach(el => {
            const match = (el.getAttribute('data-cell-key') || '') === String(key);
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
    badge.textContent = visible === total
        ? `${total} cells`
        : `${visible} / ${total} cells`;
}

// ============================================================
// Chart sessions — tabs by query (cell + timeframe + identity); same query updates one tab
// ============================================================

let chartTabs = [];
let activeChartTabId = null;
let _perfChartTabSeq = 1;

function _perfHoursLabel(hoursVal) {
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
function upsertPerfChartTab(apiData, hoursVal, treeCellId) {
    const cell = apiData.cell || {};
    const rawName = cell.cell_name ? String(cell.cell_name) : 'Cell';
    const title = `${rawName} · ${_perfHoursLabel(hoursVal)}`;
    const treeKey = treeCellId != null && String(treeCellId).trim() !== '' ? String(treeCellId) : null;
    const querySig = _perfChartQuerySig(apiData, hoursVal, treeCellId);

    const existing = chartTabs.find(t => t.querySig === querySig);
    if (existing) {
        existing.payload = apiData;
        existing.title = title;
        if (treeKey) existing.treeKey = treeKey;
        activeChartTabId = existing.id;
        lastTrendData = apiData;
        renderPerfChartTabs();
        _scrollPerfActiveTabIntoView();
        return;
    }

    const id = 'ct' + _perfChartTabSeq++;
    chartTabs.push({ id, title, payload: apiData, treeKey, querySig });
    activeChartTabId = id;
    lastTrendData = apiData;
    renderPerfChartTabs();
    const strip = document.getElementById('perf-chart-tabs-strip');
    if (strip) strip.scrollLeft = strip.scrollWidth;
}

function renderPerfChartTabs() {
    const bar = document.getElementById('perf-chart-tabs-bar');
    const strip = document.getElementById('perf-chart-tabs-strip');
    if (!bar || !strip) return;

    const tView = document.getElementById('pm-table-view');
    if (tView && tView.style.display !== 'none') {
        bar.style.display = 'none';
        return;
    }

    if (!chartTabs.length) {
        bar.style.display = 'none';
        strip.innerHTML = '';
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
    const cell = tab.payload.cell || {};
    const key = tab.treeKey
        || (cell.cell_key != null ? String(cell.cell_key) : '')
        || (cell.cell_id != null ? String(cell.cell_id) : '');
    if (key) {
        activeCellId = key;
        document.querySelectorAll('.hw-tree-leaf').forEach(el => {
            const match = (el.getAttribute('data-cell-key') || '') === key;
            el.classList.toggle('active', match);
        });
    }

    document.getElementById('charts-title').textContent = cell.cell_name || 'KPI trends';
    renderPerfChartTabs();

    document.getElementById('no-selection').style.display = 'none';
    document.getElementById('charts-wrap').style.display = 'grid';
    document.getElementById('loading-charts').style.display = 'none';

    renderAllCharts(tab.payload.trend || []);

    const trend = tab.payload.trend;
    if (trend && trend.length) {
        document.getElementById('btn-export').style.display = 'inline-flex';
    } else {
        document.getElementById('btn-export').style.display = 'none';
    }
}

function closePerfChartTab(tabId) {
    const idx = chartTabs.findIndex(t => t.id === tabId);
    if (idx < 0) return;

    chartTabs.splice(idx, 1);

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
    lastTrendData = null;
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
    activeCellId = String(cellId);
    const selected = allCells.find(c => String(c.cell_key || c.cell_id) === String(cellId));

    document.querySelectorAll('.hw-tree-leaf').forEach(el => {
        const match = (el.getAttribute('data-cell-key') || '') === String(cellId);
        el.classList.toggle('active', match);
    });

    document.getElementById('no-selection').style.display   = 'none';
    document.getElementById('charts-wrap').style.display    = 'none';
    document.getElementById('loading-charts').style.display = 'flex';
    document.getElementById('btn-export').style.display     = 'none';
    document.getElementById('btn-refresh').style.display    = 'inline-flex';

    const hours = document.getElementById('filter-hours').value;

    try {
        const params = new URLSearchParams({
            hours: String(hours),
            granularity: PERF_TREND_GRANULARITY,
        });
        if (selected) {
            params.set('cell_name', String(selected.cell_name || ''));
            params.set('technology', String(selected.technology || ''));
            params.set('site_id', String(selected.site_id || ''));
            params.set('vendor', String(selected.vendor || ''));
        } else {
            // Backward-compatible fallback
            params.set('cell_name', String(cellId));
        }
        if (KPI_DEFS.length && kpiSelectedKeys.size > 0) {
            params.set('kpi', [...kpiSelectedKeys].join(','));
        }
        const res  = await fetch(`/api/performance/cell/trend?${params.toString()}`);
        const data = await res.json();
        if (!data.success) throw new Error(data.error);

        const cell  = data.cell;
        const trend = data.trend;

        upsertPerfChartTab(data, hours, cellId);
        document.getElementById('charts-title').textContent = cell.cell_name || 'KPI trends';

        renderAllCharts(trend);

        // Show export button only when we have trend data
        if (trend.length) {
            document.getElementById('btn-export').style.display = 'inline-flex';
        }

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

const CHART_X_SKIP = new Set(['id', 'cell_name', 'timestamp', 'Date', 'date']);

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

function renderAllCharts(trend) {
    Object.values(charts).forEach(c => c.destroy());
    Object.keys(charts).forEach(k => delete charts[k]);

    const wrap = document.getElementById('charts-wrap');
    wrap.innerHTML = '';

    let defs = KPI_DEFS;
    if (!defs.length && trend.length) {
        defs = Object.keys(trend[0])
            .filter(k => !CHART_X_SKIP.has(k))
            .map(col => ({ key: col, label: col, unit: '', good: null, warn: null, inverse: false, color: _colorFor(col) }));
    }

    defs = (defs || []).filter(d => d && !CHART_X_SKIP.has(d.key));

    // Filter out columns that have no numeric values after coercion.
    // Huawei PM rows are often strings because sheet tables are TEXT-typed.
    if (trend.length) {
        defs = defs.filter(def => {
            return trend.some(r => {
                const n = _toNumericOrNull(r[def.key]);
                return n !== null;
            });
        });
    }

    const scopeFromApi = KPI_DEFS.length > 0;
    if (scopeFromApi) {
        defs = defs.filter(def => kpiSelectedKeys.has(def.key));
    }

    if (!defs.length) {
        const msg = scopeFromApi && kpiSelectedKeys.size === 0
            ? 'Select one or more KPIs in the list under the cell tree.'
            : 'No KPI data available yet.';
        wrap.innerHTML = `<p style="padding:1rem;color:#888">${msg}</p>`;
        document.getElementById('loading-charts').style.display = 'none';
        wrap.style.display = 'grid';
        return;
    }

    const labels = trend.map(r => formatTrendXLabel(trendXRaw(r)));

    defs.forEach(def => {
        const values   = trend.map(r => _toNumericOrNull(r[def.key]));
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
                            title: items => {
                                if (!items.length) return '';
                                const i = items[0].dataIndex;
                                return formatTrendXLabel(trendXRaw(trend[i]));
                            },
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

    const skip = new Set(['id']);
    const rowKeys = Object.keys(trend[0]).filter(k => !skip.has(k));
    const cols = rowKeys.filter(k => CHART_X_SKIP.has(k) || kpiSelectedKeys.has(k));

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
        if (tabBar) tabBar.style.display = 'none';
        if (noSel)     noSel.style.display     = 'none';
        if (cWrap)     cWrap.style.display     = 'none';
        if (cLoad)     cLoad.style.display     = 'none';
        if (exportBtn) exportBtn.style.display = 'none';
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
            loadPmTable(vendor, tech, '', 1);
        } else {
            document.getElementById('hw-table-container').innerHTML =
                '<p class="hw-empty-msg" style="color:#e74c3c">Select a vendor and technology first.</p>';
        }
    } else {
        tView.style.display = 'none';
        btnC && btnC.classList.add('active');
        btnT && btnT.classList.remove('active');

        renderPerfChartTabs();
        if (chartTabs.length && activeChartTabId) {
            switchPerfChartTab(activeChartTabId);
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
async function loadPmTable(vendor, technology, search, page) {
    hwCurrentVendor = vendor;
    hwCurrentTech   = technology;
    hwCurrentSearch = search;
    hwCurrentPage   = page;

    const container = document.getElementById('hw-table-container');
    container.innerHTML = '<div style="padding:20px;color:#999">Loading…</div>';

    const params = new URLSearchParams({ vendor, technology, page, page_size: HW_PAGE_SIZE });
    if (search) params.set('search', search);

    try {
        const res  = await fetch('/api/performance/pm-table?' + params);
        const data = await res.json();
        if (!data.success) throw new Error(data.error || 'Server error');
        renderPmTable(data);
    } catch (e) {
        container.innerHTML =
            `<div style="padding:20px;color:#e74c3c">Error: ${_esc(e.message)}</div>`;
    }
}

/**
 * Render the PM data table from an API response object.
 */
function renderPmTable(data) {
    const container  = document.getElementById('hw-table-container');
    const pagination = document.getElementById('hw-pagination');
    const countEl    = document.getElementById('hw-row-count');

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
        return;
    }

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
});
