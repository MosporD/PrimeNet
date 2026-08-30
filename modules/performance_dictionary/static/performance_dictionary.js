/**
 * Performance Dictionary — Nokia measurements, counters, KPIs
 */

let perfColumns = {};
let perfMeasurementIndex = [];
let perfKpiIndex = [];
let perfMeta = {};
let perfLoaded = false;
let perfActiveEntity = 'measurements';
let perfActiveId = '';
let perfActiveRows = [];
let perfSidebarTimer = null;
let perfTableTimer = null;
let perfFetchToken = 0;
let perfVendor = 'nokia';
let hwTechs = [];
let hwRows = [];

document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.entity-tab').forEach((btn) => {
        btn.addEventListener('click', () => switchEntity(btn.dataset.entity));
    });

    const sidebarSearch = document.getElementById('perf-sidebar-search');
    const tableSearch = document.getElementById('perf-table-search');
    const techFilter = document.getElementById('perf-tech-filter');
    const detailClose = document.getElementById('perf-detail-close');
    const detailBackdrop = document.getElementById('perf-detail-backdrop');

    if (sidebarSearch) {
        sidebarSearch.addEventListener('input', () => {
            clearTimeout(perfSidebarTimer);
            perfSidebarTimer = setTimeout(renderSidebarList, 180);
        });
    }
    if (tableSearch) {
        tableSearch.addEventListener('input', () => {
            clearTimeout(perfTableTimer);
            perfTableTimer = setTimeout(() => fetchAndRenderTable(), 280);
        });
    }
    if (techFilter) techFilter.addEventListener('change', () => {
        renderSidebarList();
        if (perfVendor === 'huawei' || perfActiveEntity === 'kpis') fetchAndRenderTable();
    });
    if (detailClose) detailClose.addEventListener('click', closeDetailModal);
    if (detailBackdrop) detailBackdrop.addEventListener('click', closeDetailModal);

    document.querySelectorAll('.vendor-tab').forEach((btn) => {
        btn.addEventListener('click', () => setPerfVendor(btn.dataset.vendor));
    });

    loadPerfData();
});

async function loadPerfData() {
    const countEl = document.getElementById('perf-sidebar-count');
    if (countEl) countEl.textContent = 'Loading performance reference…';
    try {
        const response = await fetch('/api/performance-dictionary/list');
        const data = await response.json();
        if (!data.success) throw new Error(data.error || 'Failed to load performance dictionary');

        perfColumns = data.columns || {};
        perfMeasurementIndex = Array.isArray(data.measurement_index) ? data.measurement_index : [];
        perfKpiIndex = Array.isArray(data.kpi_index) ? data.kpi_index : [];
        perfMeta = data.meta || {};
        perfLoaded = true;

        populateTechFilter();
        updateStats();
        updateSourceLabel();
        renderSidebarList();
        if (perfMeasurementIndex.length) {
            selectSidebarItem(perfMeasurementIndex[0].id);
        }
        applyPerfDeepLink();
    } catch (err) {
        if (countEl) countEl.textContent = `Error: ${err.message}`;
    }
}

function populateTechFilter() {
    const select = document.getElementById('perf-tech-filter');
    if (!select) return;
    const techs = Array.isArray(perfMeta.technologies) ? perfMeta.technologies : [];
    select.innerHTML = '<option value="">All Technologies</option>';
    techs.forEach((tech) => {
        const opt = document.createElement('option');
        opt.value = tech;
        opt.textContent = tech;
        select.appendChild(opt);
    });
}

function updateStats() {
    setText('stat-measurements', perfMeta.measurement_count || 0);
    setText('stat-counters', perfMeta.counter_count || 0);
    setText('stat-kpis', perfMeta.kpi_count || 0);
}

function updateSourceLabel() {
    const el = document.getElementById('perf-source-label');
    if (!el) return;
    const sources = Array.isArray(perfMeta.source) ? perfMeta.source : [];
    el.textContent = sources.length ? `Source: ${sources.join(', ')}` : '';
}

function switchEntity(entity) {
    if (!entity || entity === perfActiveEntity) return;
    perfActiveEntity = entity;
    perfActiveId = '';
    perfActiveRows = [];

    document.querySelectorAll('.entity-tab').forEach((btn) => {
        const active = btn.dataset.entity === entity;
        btn.classList.toggle('active', active);
        btn.setAttribute('aria-selected', active ? 'true' : 'false');
    });

    const tableSearch = document.getElementById('perf-table-search');
    if (tableSearch) tableSearch.value = '';

    renderSidebarList();
    if (entity === 'kpis') {
        fetchAndRenderTable();
    } else {
        const items = getSidebarItems();
        if (items.length) selectSidebarItem(items[0].id);
        else clearMainPanel('No items found for this view.');
    }
}

function itemMatchesTech(item, tech) {
    if (!tech) return true;
    const tokens = Array.isArray(item.technologies) && item.technologies.length
        ? item.technologies
        : String(item.technology || '').split(',').map((s) => s.trim()).filter(Boolean);
    return tokens.includes(tech);
}

function getSidebarItems() {
    const term = (document.getElementById('perf-sidebar-search')?.value || '').trim().toLowerCase();
    const tech = document.getElementById('perf-tech-filter')?.value || '';

    if (perfActiveEntity === 'kpis') {
        return perfKpiIndex.filter((item) => {
            if (!itemMatchesTech(item, tech)) return false;
            if (!term) return true;
            const blob = `${item.id} ${item.abbr} ${item.name} ${item.description}`.toLowerCase();
            return blob.includes(term);
        });
    }

    return perfMeasurementIndex.filter((item) => {
        if (!itemMatchesTech(item, tech)) return false;
        if (!term) return true;
        const blob = `${item.id} ${item.abbr} ${item.name} ${item.description}`.toLowerCase();
        return blob.includes(term);
    });
}

function renderSidebarList() {
    if (perfVendor === 'huawei') {
        renderHuaweiSidebar();
        return;
    }
    const listEl = document.getElementById('perf-sidebar-list');
    const countEl = document.getElementById('perf-sidebar-count');
    if (!listEl) return;

    const items = getSidebarItems();
    if (countEl) {
        const label = perfActiveEntity === 'kpis' ? 'KPIs' : 'Measurements';
        countEl.textContent = `${items.length} ${label}`;
    }

    if (perfActiveEntity === 'kpis') {
        listEl.innerHTML = '<div class="perf-sidebar-hint">Use the table to browse KPIs. Filter by technology above.</div>';
        return;
    }

    listEl.innerHTML = '';
    items.forEach((item) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'perf-sidebar-item' + (item.id === perfActiveId ? ' active' : '');
        btn.dataset.id = item.id;
        const counterNote = perfActiveEntity === 'counters' && item.counter_count
            ? `<span class="perf-item-meta">${item.counter_count} counters</span>`
            : '';
        const rawId = item.raw_id ? ` · ID ${item.raw_id}` : '';
        btn.innerHTML = `
            <span class="perf-item-title">${escapeHtml(item.abbr || item.name || item.raw_id || item.id)}</span>
            <span class="perf-item-sub">${escapeHtml(item.name || item.raw_id || item.id)}</span>
            <span class="perf-item-tech">${escapeHtml(item.technology || '')}${escapeHtml(rawId)}</span>
            ${counterNote}
        `;
        btn.addEventListener('click', () => selectSidebarItem(item.id));
        listEl.appendChild(btn);
    });
}

function selectSidebarItem(id) {
    perfActiveId = id;
    renderSidebarList();
    fetchAndRenderTable();
}

async function fetchAndRenderTable() {
    if (perfVendor === 'huawei') {
        await fetchHuaweiTable();
        return;
    }
    const token = ++perfFetchToken;
    const host = document.getElementById('perf-table-host');
    if (host) host.innerHTML = '<div class="perf-loading">Loading…</div>';

    const term = (document.getElementById('perf-table-search')?.value || '').trim();
    try {
        let rows = [];
        let title = '';
        let meta = '';

        if (term.length >= 2) {
            const resp = await fetch(
                `/api/performance-dictionary/nokia/search?q=${encodeURIComponent(term)}&entity=${encodeURIComponent(perfActiveEntity === 'kpis' ? 'kpis' : perfActiveEntity)}&limit=500`
            );
            const data = await resp.json();
            if (token !== perfFetchToken) return;
            if (!data.success) throw new Error(data.error || 'Search failed');
            rows = (data.results || []).map((r) => r.row);
            title = `Search results (${data.total}${data.capped ? '+' : ''})`;
            meta = term ? `Matching "${term}"` : '';
        } else if (perfActiveEntity === 'measurements' && perfActiveId) {
            const resp = await fetch(`/api/performance-dictionary/nokia/measurement?id=${encodeURIComponent(perfActiveId)}`);
            const data = await resp.json();
            if (token !== perfFetchToken) return;
            if (!data.success) throw new Error(data.error || 'Failed to load measurement');
            rows = data.row ? [data.row] : [];
            const idx = perfMeasurementIndex.find((m) => m.id === perfActiveId);
            title = idx?.abbr || idx?.name || perfActiveId;
            meta = `${idx?.technology || ''} · Measurement ID ${perfActiveId} · ${data.counter_count || 0} counters`;
        } else if (perfActiveEntity === 'counters' && perfActiveId) {
            const resp = await fetch(`/api/performance-dictionary/nokia/counters?measurement_id=${encodeURIComponent(perfActiveId)}`);
            const data = await resp.json();
            if (token !== perfFetchToken) return;
            if (!data.success) throw new Error(data.error || 'Failed to load counters');
            rows = data.rows || [];
            const idx = perfMeasurementIndex.find((m) => m.id === perfActiveId);
            title = idx?.abbr || idx?.name || perfActiveId;
            meta = `${idx?.technology || ''} · ${rows.length} counters`;
        } else if (perfActiveEntity === 'kpis') {
            const tech = document.getElementById('perf-tech-filter')?.value || '';
            rows = perfKpiIndex
                .filter((k) => itemMatchesTech(k, tech))
                .map((k) => ({ ...k, _isIndex: true }));
            title = 'KPI List';
            meta = `${rows.length} KPIs`;
            renderKpiIndexTable(rows);
            setText('perf-selected-title', title);
            setText('perf-selected-meta', meta);
            return;
        }

        perfActiveRows = rows;
        setText('perf-selected-title', title);
        setText('perf-selected-meta', meta);
        renderEntityTable(rows);
    } catch (err) {
        if (token !== perfFetchToken) return;
        if (host) host.innerHTML = `<div class="perf-error">${escapeHtml(err.message)}</div>`;
    }
}

function renderKpiIndexTable(indexRows) {
    const host = document.getElementById('perf-table-host');
    if (!host) return;
    const term = (document.getElementById('perf-table-search')?.value || '').trim().toLowerCase();

    let filtered = indexRows;
    if (term) {
        filtered = indexRows.filter((row) => {
            const blob = `${row.id} ${row.abbr} ${row.name} ${row.description} ${row.technology}`.toLowerCase();
            return blob.includes(term);
        });
    }

    if (!filtered.length) {
        host.innerHTML = '<div class="perf-empty">No KPIs match the current filters.</div>';
        return;
    }

    const html = ['<table class="perf-table"><thead><tr>'];
    ['Technology', 'KPI ID', 'Abbreviation', 'Name', 'Description'].forEach((col) => {
        html.push(`<th>${escapeHtml(col)}</th>`);
    });
    html.push('</tr></thead><tbody>');

    filtered.forEach((row) => {
        html.push('<tr class="perf-row-clickable" tabindex="0" role="button">');
        html.push(`<td>${escapeHtml(row.technology)}</td>`);
        html.push(`<td>${escapeHtml(row.id)}</td>`);
        html.push(`<td>${escapeHtml(row.abbr)}</td>`);
        html.push(`<td>${escapeHtml(row.name)}</td>`);
        html.push(`<td>${escapeHtml(truncate(row.description, 120))}</td>`);
        html.push('</tr>');
        const lastRow = html.length - 1;
        // attach via data attribute — we'll bind after insert
    });
    html.push('</tbody></table>');
    host.innerHTML = html.join('');

    host.querySelectorAll('.perf-row-clickable').forEach((tr, i) => {
        const row = filtered[i];
        tr.addEventListener('click', () => openKpiDetail(row.id));
        tr.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                openKpiDetail(row.id);
            }
        });
    });
}

function renderEntityTable(rows) {
    const host = document.getElementById('perf-table-host');
    if (!host) return;

    const entity = perfActiveEntity === 'kpis' ? 'kpis' : perfActiveEntity;
    const columns = (perfColumns[entity] || []).filter((col) => !col.startsWith('_'));
    const term = (document.getElementById('perf-table-search')?.value || '').trim().toLowerCase();

    let filtered = rows;
    if (term && term.length < 2) {
        filtered = rows.filter((row) => {
            const blob = columns.map((col) => row[col] || '').join(' ').toLowerCase();
            return blob.includes(term);
        });
    }

    if (!filtered.length) {
        host.innerHTML = '<div class="perf-empty">No rows to display.</div>';
        return;
    }

    const displayCols = columns.slice(0, 8);
    const html = ['<table class="perf-table"><thead><tr>'];
    displayCols.forEach((col) => html.push(`<th>${escapeHtml(col)}</th>`));
    html.push('<th></th></tr></thead><tbody>');

    filtered.forEach((row) => {
        html.push('<tr>');
        displayCols.forEach((col) => {
            html.push(`<td>${escapeHtml(truncate(row[col] || '', 80))}</td>`);
        });
        html.push('<td><button type="button" class="perf-view-btn">Details</button></td>');
        html.push('</tr>');
    });
    html.push('</tbody></table>');
    host.innerHTML = html.join('');

    host.querySelectorAll('tbody tr').forEach((tr, i) => {
        const row = filtered[i];
        tr.querySelector('.perf-view-btn')?.addEventListener('click', (e) => {
            e.stopPropagation();
            openRowDetail(entity, row);
        });
        tr.addEventListener('click', () => openRowDetail(entity, row));
    });
}

async function openKpiDetail(kpiId) {
    try {
        const resp = await fetch(`/api/performance-dictionary/nokia/kpi?id=${encodeURIComponent(kpiId)}`);
        const data = await resp.json();
        if (!data.success || !data.row) throw new Error(data.error || 'KPI not found');
        openRowDetail('kpis', data.row);
    } catch (err) {
        alert(err.message);
    }
}

function openRowDetail(entity, row) {
    const modal = document.getElementById('perf-detail-modal');
    const body = document.getElementById('perf-detail-body');
    const title = document.getElementById('perf-detail-title');
    if (!modal || !body || !title) return;

    const columns = (perfColumns[entity] || Object.keys(row)).filter((col) => !col.startsWith('_'));
    title.textContent = detailTitle(entity, row);

    const parts = ['<dl class="perf-detail-grid">'];
    columns.forEach((col) => {
        const val = row[col];
        if (!val) return;
        parts.push(`<dt>${escapeHtml(col)}</dt><dd>${escapeHtml(val)}</dd>`);
    });
    parts.push('</dl>');
    body.innerHTML = parts.join('');
    modal.hidden = false;
}

function detailTitle(entity, row) {
    if (entity === 'measurements') {
        return row['Measurement Abbreviated Name'] || row['Measurement Name'] || row['Measurement ID'] || 'Measurement';
    }
    if (entity === 'counters') {
        return row['NetAct Name'] || row['Network Element Name'] || row['Counter ID'] || 'Counter';
    }
    return row['KPI Abbreviation'] || row['KPI Name'] || row['KPI ID'] || 'KPI';
}

function closeDetailModal() {
    const modal = document.getElementById('perf-detail-modal');
    if (modal) modal.hidden = true;
}

function clearMainPanel(message) {
    setText('perf-selected-title', 'No selection');
    setText('perf-selected-meta', message);
    const host = document.getElementById('perf-table-host');
    if (host) host.innerHTML = `<div class="perf-empty">${escapeHtml(message)}</div>`;
}

function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
}

function truncate(text, max) {
    const s = String(text || '');
    return s.length <= max ? s : `${s.slice(0, max - 1)}…`;
}

function escapeHtml(text) {
    return String(text || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

async function setPerfVendor(vendor) {
    perfVendor = vendor === 'huawei' ? 'huawei' : 'nokia';
    document.querySelectorAll('.vendor-tab').forEach((btn) => {
        btn.classList.toggle('active', btn.dataset.vendor === perfVendor);
    });
    const entityTabs = document.getElementById('nokia-entity-tabs');
    if (entityTabs) entityTabs.style.display = perfVendor === 'nokia' ? '' : 'none';
    if (perfVendor === 'huawei') {
        await loadHuaweiCatalog();
        return;
    }
    populateTechFilter();
    updateStats();
    updateSourceLabel();
    renderSidebarList();
    if (perfMeasurementIndex.length) selectSidebarItem(perfMeasurementIndex[0].id);
}

async function applyPerfDeepLink() {
    const params = new URLSearchParams(window.location.search);
    const vendor = (params.get('vendor') || '').toLowerCase();
    const entity = (params.get('entity') || '').toLowerCase();
    const q = (params.get('q') || '').trim();
    if (vendor === 'huawei') {
        const tableSearch = document.getElementById('perf-table-search');
        if (q && tableSearch) tableSearch.value = q;
        await setPerfVendor('huawei');
        return;
    }
    if (entity === 'kpis' || entity === 'counters' || entity === 'measurements') {
        switchEntity(entity);
    }
    if (q) {
        const tableSearch = document.getElementById('perf-table-search');
        if (tableSearch) tableSearch.value = q;
        await fetchAndRenderTable();
    }
}

async function loadHuaweiCatalog() {
    const countEl = document.getElementById('perf-sidebar-count');
    if (countEl) countEl.textContent = 'Loading Huawei counters…';
    try {
        const resp = await fetch('/api/performance-dictionary/huawei/catalog');
        const data = await resp.json();
        if (!data.success) throw new Error(data.error || 'Failed to load Huawei catalog');
        hwTechs = Array.isArray(data.technologies) ? data.technologies : [];
        const select = document.getElementById('perf-tech-filter');
        if (select) {
            select.innerHTML = '';
            hwTechs.forEach((tech) => {
                const opt = document.createElement('option');
                opt.value = tech.technology;
                opt.textContent = `${tech.technology} (${tech.total_counters || 0})`;
                select.appendChild(opt);
            });
            if (!select.value && hwTechs[0]) select.value = hwTechs[0].technology;
        }
        const configured = hwTechs.filter((t) => t.configured && t.total_counters);
        setText('stat-measurements', configured.length);
        setText('stat-counters', configured.reduce((sum, t) => sum + (t.total_counters || 0), 0));
        setText('stat-kpis', 0);
        setText('perf-source-label', configured.length
            ? 'Source: Huawei MAE counter catalog'
            : 'Huawei CSVs not installed under data/huawei_pm_counters');
        perfActiveId = '';
        await fetchHuaweiTable();
    } catch (err) {
        if (countEl) countEl.textContent = `Error: ${err.message}`;
    }
}

function renderHuaweiSidebar() {
    const listEl = document.getElementById('perf-sidebar-list');
    const countEl = document.getElementById('perf-sidebar-count');
    if (!listEl) return;
    const tech = document.getElementById('perf-tech-filter')?.value || '';
    const selected = hwTechs.find((t) => t.technology === tech);
    if (countEl) countEl.textContent = selected ? `${selected.total_counters || 0} counters` : 'Select a RAT';
    listEl.innerHTML = `<div class="perf-sidebar-hint">Huawei MAE system counters for ${escapeHtml(tech || 'the selected RAT')}. Search the table to filter by name or ID.</div>`;
}

async function fetchHuaweiTable() {
    const host = document.getElementById('perf-table-host');
    const tech = document.getElementById('perf-tech-filter')?.value || '';
    const q = (document.getElementById('perf-table-search')?.value || '').trim();
    if (!tech) {
        clearMainPanel('Select a Huawei RAT.');
        return;
    }
    if (host) host.innerHTML = '<div class="perf-loading">Loading…</div>';
    try {
        const qs = new URLSearchParams({ technology: tech, q, limit: '300' });
        const resp = await fetch(`/api/performance-dictionary/huawei/catalog?${qs.toString()}`);
        const data = await resp.json();
        if (!data.success) throw new Error(data.error || 'Failed');
        hwRows = data.counters || [];
        setText('perf-selected-title', `${tech} counters`);
        setText('perf-selected-meta', `${data.total || 0} matching · ${data.ne_type || ''} · ${data.configured ? 'catalog loaded' : 'CSV missing'}`);
        renderHuaweiSidebar();
        if (!hwRows.length) {
            if (host) host.innerHTML = `<div class="perf-empty">${data.configured ? 'No counters match.' : 'Place MAE counter CSVs in data/huawei_pm_counters (2GBSC.csv, 3GRNC.csv, 4GBTS.csv).'}</div>`;
            return;
        }
        const cols = ['id', 'name', 'unit', 'function_subset_name', 'time_aggregation', 'object_aggregation'];
        const header = cols.map((c) => `<th>${escapeHtml(c)}</th>`).join('');
        const body = hwRows.map((row) => {
            const cells = cols.map((c) => `<td>${escapeHtml(row[c] || '')}</td>`).join('');
            return `<tr>${cells}</tr>`;
        }).join('');
        if (host) {
            host.innerHTML = `<div class="param-table-wrap"><table class="param-table"><thead><tr>${header}</tr></thead><tbody>${body}</tbody></table></div>`;
        }
    } catch (err) {
        if (host) host.innerHTML = `<div class="perf-empty">${escapeHtml(err.message)}</div>`;
    }
}

