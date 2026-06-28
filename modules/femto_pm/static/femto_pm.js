let femtoCharts = [];
let femtoCatalog = { kpis: [], counters: {} };
let femtoDevices = [];
let femtoSelectionMode = 'single';
let femtoAggregation = 'hourly';
const selectedObjects = new Set();
const selectedComputedKpis = new Set();
const selectedCounters = new Set();
const kpiExpanded = new Set();
const counterExpanded = new Set();
let femtoChartTabs = [];
let activeFemtoTabId = '';

function escHtml(s) {
    return String(s ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function compactFemtoTimeLabel(raw) {
    const value = String(raw || '').trim();
    if (!value) return '';
    const match = value.match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/);
    if (match) return `${match[2]}-${match[3]} ${match[4]}:${match[5]}`;
    return value.replace(/:\d{2}(?:\.\d+)?$/, '');
}

function uniqueSelectedSeries() {
    return [...new Set([...selectedComputedKpis, ...selectedCounters])].slice(0, 20);
}

function selectedObjectIds() {
    return [...selectedObjects].filter(Boolean);
}

function updateFemtoEmptyState(hasCharts) {
    const empty = document.getElementById('no-selection');
    const wrap = document.querySelector('.femto-chart-wrap');
    if (empty) empty.style.display = hasCharts ? 'none' : 'flex';
    if (wrap) wrap.style.display = hasCharts ? 'block' : 'none';
}

function toggleFemtoLeftPanel() {
    const body = document.querySelector('.femto-body');
    const btn = document.getElementById('perf-left-panel-toggle');
    if (!body) return;
    const collapsed = body.classList.toggle('left-collapsed');
    if (btn) {
        btn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
        btn.textContent = collapsed ? '▶' : '◀';
        btn.title = collapsed ? 'Expand filters' : 'Collapse filters';
    }
}

async function refreshFemtoData() {
    const status = document.getElementById('femto-status');
    if (status) status.textContent = 'Refreshing Femto devices and catalog...';
    await Promise.all([loadFemtoDevices(), loadFemtoCatalog()]);
    renderObjectList();
}

async function loadFemtoDevices() {
    const list = document.getElementById('femto-object-list');
    const count = document.getElementById('femto-object-count');
    const status = document.getElementById('femto-status');
    if (!list) return;
    list.innerHTML = '<div class="femto-chart-empty">Loading objects...</div>';
    const res = await fetch('/api/femto-pm/devices');
    const data = await res.json();
    femtoDevices = Array.isArray(data.devices) ? data.devices : [];
    if (!femtoDevices.length) {
        list.innerHTML = '<div class="femto-chart-empty">No objects found.</div>';
        if (status) status.textContent = 'Femto DB has no devices yet.';
        return;
    }
    if (count) count.textContent = `${femtoDevices.length} objects`;
    if (!selectedObjects.size && femtoDevices[0]?.unique_id) {
        selectedObjects.add(String(femtoDevices[0].unique_id));
    }
    renderObjectList();
}

function setSelectorBlockOpen(blockId, open) {
    const block = document.getElementById(blockId);
    const toggle = document.querySelector(`[data-target="${blockId}"]`);
    const section = toggle?.closest('.femto-selector-block');
    if (!block || !toggle) return;
    block.style.display = open ? 'block' : 'none';
    toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    if (section) section.classList.toggle('is-open', open);
    const arrow = toggle.querySelector('.femto-selector-arrow');
    if (arrow) arrow.textContent = open ? '▼' : '▶';
}

function expandSelectorBlock(blockId) {
    setSelectorBlockOpen(blockId, true);
}

function totalCounterLeafCount(tree) {
    let total = 0;
    Object.values(tree || {}).forEach(l2Map => {
        Object.values(l2Map || {}).forEach(l3Map => {
            Object.values(l3Map || {}).forEach(counters => {
                total += (counters || []).length;
            });
        });
    });
    return total;
}

async function loadFemtoCatalog() {
    const status = document.getElementById('femto-status');
    if (status) status.textContent = 'Loading KPI catalog...';
    const res = await fetch('/api/femto-pm/catalog');
    const data = await res.json();
    femtoCatalog = {
        kpis: Array.isArray(data.kpis) ? data.kpis : [],
        counters: data.counters && typeof data.counters === 'object' ? data.counters : {},
    };
    seedExpandedState();
    renderComputedKpis();
    renderCounterList();
    const hasKpis = femtoCatalog.kpis.length > 0;
    const hasCounters = Object.keys(femtoCatalog.counters).length > 0;
    if (hasKpis) {
        expandSelectorBlock('femto-kpi-block');
    } else if (hasCounters) {
        expandSelectorBlock('femto-counter-block');
    }
    if (status) {
        if (!hasKpis && !hasCounters) {
            status.textContent = 'No KPI catalog in database yet. Run scripts/import_femto_catalogs.py or load PM data.';
        } else {
            status.textContent = 'Select device and KPI(s), then click Load Chart.';
        }
    }
}

function seedExpandedState() {
    kpiExpanded.clear();
    counterExpanded.clear();
}

function matchesSearch(text, query) {
    return !query || String(text || '').toLowerCase().includes(query);
}

function renderTreeFolder({ key, name, count, childrenHtml, expanded, checkboxHtml = '' }) {
    return `
        <div class="femto-tree-node">
            <div class="femto-tree-folder-row">
                <button type="button" class="femto-tree-twisty" data-tree-toggle="${escHtml(key)}">${expanded ? '−' : '+'}</button>
                ${checkboxHtml}
                <span class="femto-tree-folder-name">${escHtml(name)}</span>
                <span class="femto-tree-folder-meta">${count}</span>
            </div>
            <div class="femto-tree-children ${expanded ? '' : 'is-collapsed'}">${childrenHtml}</div>
        </div>
    `;
}

function visibleKpiRows() {
    const query = String(document.getElementById('femto-kpi-search')?.value || '').trim().toLowerCase();
    return femtoCatalog.kpis.filter(row =>
        matchesSearch(row.kpi_name, query) ||
        matchesSearch(row.category_l1, query) ||
        matchesSearch(row.description, query)
    );
}

function renderComputedKpis() {
    const list = document.getElementById('femto-kpi-list');
    const count = document.getElementById('femto-kpi-count');
    if (!list) return;
    const rows = visibleKpiRows();
    if (count) count.textContent = `${rows.length} / ${femtoCatalog.kpis.length}`;
    if (!femtoCatalog.kpis.length) {
        list.innerHTML = '<p class="femto-list-empty">No computed KPIs in catalog.</p>';
        syncSelectAll('femto-kpi-cb', 'femto-kpi-select-all');
        return;
    }
    if (!rows.length) {
        list.innerHTML = '<p class="femto-list-empty">No KPI matches.</p>';
        syncSelectAll('femto-kpi-cb', 'femto-kpi-select-all');
        return;
    }
    const grouped = new Map();
    rows.forEach(row => {
        const cat = String(row.category_l1 || 'Other');
        if (!grouped.has(cat)) grouped.set(cat, []);
        grouped.get(cat).push(row);
    });
    const categories = [...grouped.keys()].sort((a, b) => a.localeCompare(b));
    list.innerHTML = `<div class="femto-tree">${
        categories.map(cat => {
            const key = cat;
            const expanded = kpiExpanded.has(key);
            const childrenHtml = grouped.get(cat).map(row => `
                <label class="femto-kpi-item" title="${escHtml(row.description || row.formula || '')}">
                    <input type="checkbox" class="femto-kpi-cb" data-name="${escHtml(row.kpi_name)}" ${selectedComputedKpis.has(row.kpi_name) ? 'checked' : ''}>
                    <span>${escHtml(row.kpi_name)}${row.unit ? ` <em class="femto-unit">(${escHtml(row.unit)})</em>` : ''}</span>
                </label>
            `).join('');
            return renderTreeFolder({
                key,
                name: cat,
                count: grouped.get(cat).length,
                childrenHtml,
                expanded,
            });
        }).join('')
    }</div>`;
    syncSelectAll('femto-kpi-cb', 'femto-kpi-select-all');
}

function renderObjectList() {
    const list = document.getElementById('femto-object-list');
    const count = document.getElementById('femto-object-count');
    const q = String(document.getElementById('femto-object-search')?.value || '').trim().toLowerCase();
    if (!list) return;
    const rows = femtoDevices.filter(d => {
        const name = String(d.bsr_name || d.unique_id || '');
        const id = String(d.unique_id || '');
        return !q || name.toLowerCase().includes(q) || id.toLowerCase().includes(q);
    });
    if (count) count.textContent = `${rows.length} / ${femtoDevices.length} objects`;
    if (!rows.length) {
        list.innerHTML = '<div class="femto-chart-empty">No matching objects.</div>';
        return;
    }
    list.innerHTML = rows.map(d => {
        const id = String(d.unique_id || '');
        const label = String(d.bsr_name || d.unique_id || '');
        const checked = selectedObjects.has(id);
        const inputType = femtoSelectionMode === 'multiple' ? 'checkbox' : 'radio';
        return `
            <label class="femto-object-item ${checked ? 'active' : ''}">
                <input type="${inputType}" class="femto-object-cb" name="femto-object-single" data-id="${escHtml(id)}" ${checked ? 'checked' : ''}>
                <span class="femto-object-label">${escHtml(label)}</span>
            </label>
        `;
    }).join('');
}

function visibleCounters() {
    const tree = femtoCatalog.counters || {};
    const q = String(document.getElementById('femto-counter-search')?.value || '').trim().toLowerCase();
    const out = [];
    Object.entries(tree).forEach(([l1, l2Map]) => {
        Object.entries(l2Map || {}).forEach(([l2, l3Map]) => {
            Object.entries(l3Map || {}).forEach(([l3, counters]) => {
                const filtered = (counters || []).filter(name =>
                    matchesSearch(name, q) || matchesSearch(l1, q) || matchesSearch(l2, q) || matchesSearch(l3, q)
                );
                if (filtered.length) out.push({ l1, l2, l3, counters: filtered });
            });
        });
    });
    return out;
}

function renderCounterList() {
    const list = document.getElementById('femto-counter-list');
    const count = document.getElementById('femto-counter-count');
    if (!list) return;
    const branches = visibleCounters();
    const visibleLeafCount = branches.reduce((sum, b) => sum + b.counters.length, 0);
    const totalCounters = totalCounterLeafCount(femtoCatalog.counters);
    if (count) count.textContent = `${visibleLeafCount} / ${totalCounters}`;
    if (!branches.length) {
        list.innerHTML = '<p>No counters match this selection.</p>';
        syncSelectAll('femto-counter-cb', 'femto-counter-select-all');
        return;
    }
    const tree = {};
    branches.forEach(({ l1, l2, l3, counters }) => {
        tree[l1] = tree[l1] || {};
        tree[l1][l2] = tree[l1][l2] || {};
        tree[l1][l2][l3] = counters;
    });
    const renderL3 = (l1, l2, l3, counters) => {
        const key = `L3:${l1}|${l2}|${l3}`;
        const expanded = counterExpanded.has(key);
        const childrenHtml = counters.map(name => `
            <label class="femto-kpi-item">
                <input type="checkbox" class="femto-counter-cb" data-name="${escHtml(name)}" ${selectedCounters.has(name) ? 'checked' : ''}>
                <span>${escHtml(name)}</span>
            </label>
        `).join('');
        return renderTreeFolder({ key, name: l3, count: counters.length, childrenHtml, expanded });
    };
    const renderL2 = (l1, l2, l3Map) => {
        const key = `L2:${l1}|${l2}`;
        const expanded = counterExpanded.has(key);
        const childrenHtml = Object.keys(l3Map).sort((a, b) => a.localeCompare(b)).map(l3 => renderL3(l1, l2, l3, l3Map[l3])).join('');
        const count = Object.values(l3Map).reduce((sum, arr) => sum + arr.length, 0);
        return renderTreeFolder({ key, name: l2, count, childrenHtml, expanded });
    };
    const renderL1 = (l1, l2Map) => {
        const key = `L1:${l1}`;
        const expanded = counterExpanded.has(key);
        const childrenHtml = Object.keys(l2Map).sort((a, b) => a.localeCompare(b)).map(l2 => renderL2(l1, l2, l2Map[l2])).join('');
        const count = Object.values(l2Map).reduce((sum, l3Map) => sum + Object.values(l3Map).reduce((s, arr) => s + arr.length, 0), 0);
        return renderTreeFolder({ key, name: l1, count, childrenHtml, expanded });
    };
    list.innerHTML = `<div class="femto-tree">${
        Object.keys(tree).sort((a, b) => a.localeCompare(b)).map(l1 => renderL1(l1, tree[l1])).join('')
    }</div>`;
    syncSelectAll('femto-counter-cb', 'femto-counter-select-all');
}

function syncSelectAll(itemClass, selectAllId) {
    const all = [...document.querySelectorAll(`.${itemClass}`)];
    const selAll = document.getElementById(selectAllId);
    if (!selAll) return;
    if (!all.length) {
        selAll.checked = false;
        selAll.indeterminate = false;
        return;
    }
    const checked = all.filter(cb => cb.checked).length;
    selAll.checked = checked > 0 && checked === all.length;
    selAll.indeterminate = checked > 0 && checked < all.length;
}

async function loadFemtoTrendChart() {
    const status = document.getElementById('femto-status');
    const objectIds = selectedObjectIds();
    if (!objectIds.length) {
        if (status) status.textContent = 'Select at least one object.';
        return;
    }
    const series = uniqueSelectedSeries();
    if (!series.length) {
        if (status) status.textContent = 'Select at least one KPI or counter.';
        return;
    }
    if (status) status.textContent = `Loading ${femtoAggregation} ${series.length} series for ${objectIds.length} object(s)...`;
    const requests = await Promise.all(objectIds.map(async uniqueId => {
        const params = new URLSearchParams({
            unique_id: uniqueId,
            kpi: series.join(','),
            granularity: femtoAggregation,
            limit: femtoAggregation === 'daily' ? '90' : '300',
        });
        const res = await fetch('/api/femto-pm/trend?' + params.toString());
        const data = await res.json();
        return { uniqueId, data };
    }));
    femtoChartTabs = requests
        .map(({ uniqueId, data }) => {
            const rows = Array.isArray(data.rows) ? data.rows : [];
            const device = femtoDevices.find(d => String(d.unique_id || '') === uniqueId) || {};
            return {
                id: `obj:${uniqueId}`,
                uniqueId,
                title: String(device.bsr_name || uniqueId || ''),
                rows,
                series,
            };
        })
        .filter(tab => tab.rows.length);
    if (!femtoChartTabs.length) {
        renderFemtoTabs();
        renderFemtoChartsForActiveTab();
        updateFemtoEmptyState(false);
        if (status) status.textContent = 'No trend rows found for this selection.';
        return;
    }
    activeFemtoTabId = femtoChartTabs[0].id;
    renderFemtoTabs();
    renderFemtoChartsForActiveTab();
    updateFemtoEmptyState(true);
    if (status) status.textContent = `Loaded ${femtoAggregation} trends for ${femtoChartTabs.length} object tab(s).`;
}

function renderFemtoTabs() {
    const bar = document.getElementById('femto-chart-tabs-bar');
    const strip = document.getElementById('femto-chart-tabs-strip');
    if (!bar || !strip) return;
    if (!femtoChartTabs.length) {
        bar.style.display = 'none';
        strip.innerHTML = '';
        return;
    }
    bar.style.display = 'flex';
    strip.innerHTML = femtoChartTabs.map(tab => `
        <div class="femto-chart-tab ${tab.id === activeFemtoTabId ? 'active' : ''}">
            <button type="button" class="femto-chart-tab-activate" data-tab-id="${escHtml(tab.id)}">${escHtml(tab.title)}</button>
        </div>
    `).join('');
}

function renderFemtoChartsForActiveTab() {
    const grid = document.getElementById('femto-chart-grid');
    if (!grid) return;
    femtoCharts.forEach(chart => {
        try { chart.destroy(); } catch (_) { /* noop */ }
    });
    femtoCharts = [];
    const tab = femtoChartTabs.find(t => t.id === activeFemtoTabId);
    if (!tab) {
        grid.innerHTML = '<div class="femto-chart-empty">Select object(s) and KPI(s), then click Query.</div>';
        return;
    }
    const labels = tab.rows.map(r => String(r.timestamp || ''));
    const palette = ['#3498db', '#27ae60', '#e74c3c', '#8e44ad', '#f39c12', '#16a085', '#d35400', '#2c3e50', '#7f8c8d', '#c0392b'];
    grid.innerHTML = tab.series.map((name, idx) => `
        <div class="femto-chart-card">
            <div class="femto-chart-title">${escHtml(name)}</div>
            <div class="femto-chart-canvas-wrap">
                <canvas id="femto-chart-${idx}" class="femto-chart-canvas"></canvas>
            </div>
        </div>
    `).join('');
    tab.series.forEach((name, idx) => {
        const canvas = document.getElementById(`femto-chart-${idx}`);
        if (!canvas) return;
        const chartWidth = canvas.parentElement?.clientWidth || 480;
        const maxXAxisTicks = Math.max(3, Math.min(6, Math.floor(chartWidth / 95)));
        const chart = new Chart(canvas.getContext('2d'), {
            type: 'line',
            data: {
                labels,
                datasets: [{
                    label: name,
                    data: tab.rows.map(r => {
                        const v = r[name];
                        if (v === null || v === undefined || v === '') return null;
                        const n = Number(v);
                        return Number.isFinite(n) ? n : null;
                    }),
                    borderColor: palette[idx % palette.length],
                    backgroundColor: palette[idx % palette.length] + '22',
                    borderWidth: 2,
                    pointRadius: 1.5,
                    spanGaps: true,
                    tension: 0.25,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'nearest', intersect: false },
                plugins: { legend: { display: false } },
                scales: {
                    x: {
                        ticks: {
                            autoSkip: true,
                            maxTicksLimit: maxXAxisTicks,
                            minRotation: 35,
                            maxRotation: 35,
                            callback: function(value) {
                                return compactFemtoTimeLabel(this.getLabelForValue(value));
                            },
                        },
                    },
                },
            },
        });
        femtoCharts.push(chart);
    });
}

function setupToggles() {
    document.querySelectorAll('.femto-selector-toggle').forEach(btn => {
        const targetId = btn.getAttribute('data-target');
        if (targetId) {
            const expanded = btn.getAttribute('aria-expanded') === 'true';
            setSelectorBlockOpen(targetId, expanded);
        }
        btn.addEventListener('click', () => {
            const id = btn.getAttribute('data-target');
            if (!id) return;
            const expanded = btn.getAttribute('aria-expanded') === 'true';
            setSelectorBlockOpen(id, !expanded);
        });
    });
}

document.addEventListener('DOMContentLoaded', async () => {
    setupToggles();
    updateFemtoEmptyState(false);
    const btn = document.getElementById('femto-load-btn');
    if (btn) btn.addEventListener('click', loadFemtoTrendChart);

    document.getElementById('femto-kpi-search')?.addEventListener('input', renderComputedKpis);
    document.getElementById('femto-counter-search')?.addEventListener('input', renderCounterList);
    document.getElementById('femto-object-search')?.addEventListener('input', renderObjectList);
    document.querySelectorAll('input[name="femto-sel-mode"]').forEach(el => {
        el.addEventListener('change', e => {
            femtoSelectionMode = String(e.target.value || 'single');
            const first = selectedObjectIds()[0] || String(femtoDevices[0]?.unique_id || '');
            selectedObjects.clear();
            if (first) selectedObjects.add(first);
            renderObjectList();
        });
    });
    document.querySelectorAll('input[name="femto-aggregation"]').forEach(el => {
        el.addEventListener('change', e => {
            femtoAggregation = e.target.value === 'daily' ? 'daily' : 'hourly';
        });
    });

    document.getElementById('femto-kpi-select-all')?.addEventListener('change', e => {
        const checked = !!e.target.checked;
        document.querySelectorAll('.femto-kpi-cb').forEach(cb => {
            const name = String(cb.getAttribute('data-name') || '');
            cb.checked = checked;
            if (!name) return;
            if (checked) selectedComputedKpis.add(name); else selectedComputedKpis.delete(name);
        });
        syncSelectAll('femto-kpi-cb', 'femto-kpi-select-all');
    });

    document.getElementById('femto-counter-select-all')?.addEventListener('change', e => {
        const checked = !!e.target.checked;
        document.querySelectorAll('.femto-counter-cb').forEach(cb => {
            const name = String(cb.getAttribute('data-name') || '');
            cb.checked = checked;
            if (!name) return;
            if (checked) selectedCounters.add(name); else selectedCounters.delete(name);
        });
        syncSelectAll('femto-counter-cb', 'femto-counter-select-all');
    });

    document.getElementById('femto-kpi-list')?.addEventListener('change', e => {
        const target = e.target;
        if (!(target instanceof HTMLInputElement) || !target.classList.contains('femto-kpi-cb')) return;
        const name = String(target.getAttribute('data-name') || '');
        if (!name) return;
        if (target.checked) selectedComputedKpis.add(name); else selectedComputedKpis.delete(name);
        syncSelectAll('femto-kpi-cb', 'femto-kpi-select-all');
    });

    document.getElementById('femto-counter-list')?.addEventListener('change', e => {
        const target = e.target;
        if (!(target instanceof HTMLInputElement) || !target.classList.contains('femto-counter-cb')) return;
        const name = String(target.getAttribute('data-name') || '');
        if (!name) return;
        if (target.checked) selectedCounters.add(name); else selectedCounters.delete(name);
        syncSelectAll('femto-counter-cb', 'femto-counter-select-all');
    });

    document.getElementById('femto-kpi-list')?.addEventListener('click', e => {
        const target = e.target;
        if (!(target instanceof HTMLElement)) return;
        const btn = target.closest('[data-tree-toggle]');
        if (!btn) return;
        const key = String(btn.getAttribute('data-tree-toggle') || '');
        if (!key) return;
        if (kpiExpanded.has(key)) kpiExpanded.delete(key); else kpiExpanded.add(key);
        renderComputedKpis();
    });

    document.getElementById('femto-counter-list')?.addEventListener('click', e => {
        const target = e.target;
        if (!(target instanceof HTMLElement)) return;
        const btn = target.closest('[data-tree-toggle]');
        if (!btn) return;
        const key = String(btn.getAttribute('data-tree-toggle') || '');
        if (!key) return;
        if (counterExpanded.has(key)) counterExpanded.delete(key); else counterExpanded.add(key);
        renderCounterList();
    });

    document.getElementById('femto-object-list')?.addEventListener('change', e => {
        const target = e.target;
        if (!(target instanceof HTMLInputElement) || !target.classList.contains('femto-object-cb')) return;
        const id = String(target.getAttribute('data-id') || '');
        if (!id) return;
        if (femtoSelectionMode === 'single') {
            selectedObjects.clear();
            if (target.checked) selectedObjects.add(id);
        } else {
            if (target.checked) selectedObjects.add(id); else selectedObjects.delete(id);
        }
        renderObjectList();
    });

    document.getElementById('femto-chart-tabs-strip')?.addEventListener('click', e => {
        const target = e.target;
        if (!(target instanceof HTMLElement)) return;
        const btn = target.closest('[data-tab-id]');
        if (!btn) return;
        activeFemtoTabId = String(btn.getAttribute('data-tab-id') || '');
        renderFemtoTabs();
        renderFemtoChartsForActiveTab();
    });

    await loadFemtoDevices();
    await loadFemtoCatalog();
});

