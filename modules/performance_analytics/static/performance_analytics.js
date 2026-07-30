/**
 * Performance Analytics — Huawei PM API bridge.
 * Reuses the Performance module shell (performance.css + performance.js) and overrides
 * data loading to call MAE Open API §5.4 instead of local SQLite PM databases.
 */
(function () {
    'use strict';

    if (!window.PA_HUAWEI_API) return;

    const PAGE_SIZE = 20;
    let paLastQueryPayload = null;
    let paLastTablePayload = null;
    let paCatalogCounters = [];
    let paCounterMeta = {};
    let paCatalogTotal = 0;
    let paCatalogNeType = '';
    let paSearchTimer = null;
    let paTablePage = 1;
    let paTableSearch = '';

    function escHtml(str) {
        return String(str || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function paConfigured() {
        return window.PA_API_CONFIGURED === true;
    }

    function paTimeWindow() {
        return {
            startTime: (document.getElementById('pa-start')?.value || '').trim(),
            endTime: (document.getElementById('pa-end')?.value || '').trim(),
            period: parseInt(document.getElementById('pa-period')?.value || '60', 10) || 60,
        };
    }

    function paTechnology() {
        return (document.getElementById('filter-tech')?.value || '').trim();
    }

    function paSelectedCounterIds() {
        const ids = [];
        if (typeof kpiSelectedKeys !== 'undefined') {
            kpiSelectedKeys.forEach(function (k) {
                const n = parseInt(String(k), 10);
                if (!Number.isNaN(n)) ids.push(n);
            });
        }
        return ids;
    }

    function paCounterLabel(id) {
        const meta = paCounterMeta[String(id)] || {};
        return meta.name || meta.label || ('Counter ' + id);
    }

    function paCollectCellKeys() {
        const keys = [];
        const mode = document.querySelector('input[name="perf-sel-mode"]:checked')?.value || 'single';
        if (mode === 'multiple') {
            document.querySelectorAll('#cell-list .hw-tree-leaf').forEach(function (leaf) {
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
        const fallback = (document.getElementById('filter-cell')?.value || '').trim();
        if (!keys.length && fallback) keys.push(fallback);
        return keys;
    }

    function paCellsFromKeys(keys) {
        if (typeof allCells === 'undefined' || !Array.isArray(allCells)) return [];
        return keys.map(function (key) {
            return allCells.find(function (c) {
                return String(c.cell_key || c.cell_id) === String(key);
            }) || null;
        }).filter(Boolean);
    }

    function paSiteIdsFromKeys(keys) {
        const ids = new Set();
        paCellsFromKeys(keys).forEach(function (c) {
            if (c.site_id != null && String(c.site_id).trim()) {
                ids.add(String(c.site_id).trim());
            }
        });
        return [...ids];
    }

    function paTransformToTablePayload(queryPayload) {
        const counterIds = (queryPayload && queryPayload.counterIds) || [];
        const rows = (queryPayload && queryPayload.result) || [];
        const staticCols = ['startTime', 'neName', 'objectName'];
        const columns = staticCols.concat(counterIds.map(String));
        const columnLabels = {
            startTime: 'Start time',
            neName: 'NE',
            objectName: 'Object',
        };
        counterIds.forEach(function (cid) {
            columnLabels[String(cid)] = paCounterLabel(cid);
        });

        const tableRows = rows.map(function (row) {
            const out = {
                startTime: row.startTime || '',
                neName: row.neName || '',
                objectName: row.objectName || '',
            };
            const vals = row.counterValues || [];
            counterIds.forEach(function (cid, i) {
                out[String(cid)] = vals[i] != null ? vals[i] : '';
            });
            return out;
        });

        return {
            success: true,
            columns: columns,
            static_cols: staticCols,
            column_labels: columnLabels,
            rows: tableRows,
            total: tableRows.length,
            page: 1,
            page_size: PAGE_SIZE,
            cell_label: 'object',
            _raw: queryPayload,
        };
    }

    function paFilterTableRows(payload, search) {
        if (!payload || !Array.isArray(payload.rows)) return payload;
        const q = String(search || '').trim().toLowerCase();
        if (!q) return payload;
        const filtered = payload.rows.filter(function (row) {
            return (
                String(row.objectName || '').toLowerCase().includes(q) ||
                String(row.neName || '').toLowerCase().includes(q) ||
                String(row.startTime || '').toLowerCase().includes(q)
            );
        });
        return Object.assign({}, payload, {
            rows: filtered,
            total: filtered.length,
            page: 1,
        });
    }

    function paPaginatePayload(payload, page) {
        const p = Math.max(1, page || 1);
        const start = (p - 1) * PAGE_SIZE;
        const slice = (payload.rows || []).slice(start, start + PAGE_SIZE);
        return Object.assign({}, payload, {
            rows: slice,
            page: p,
            page_size: PAGE_SIZE,
        });
    }

    function paRenderTablePage() {
        if (!paLastTablePayload) return;
        let payload = paFilterTableRows(paLastTablePayload, paTableSearch);
        payload = paPaginatePayload(payload, paTablePage);
        if (typeof renderPmTable === 'function') {
            renderPmTable(payload);
        }
    }

    function paTrendFromQuery(cellKey) {
        if (!paLastQueryPayload || !Array.isArray(paLastQueryPayload.result)) return [];
        const cell = paCellsFromKeys([cellKey])[0];
        const cellName = cell ? String(cell.cell_name || '').trim() : '';
        const counterIds = paLastQueryPayload.counterIds || [];
        const rows = paLastQueryPayload.result.filter(function (row) {
            const obj = String(row.objectName || '');
            if (cellName && obj.includes(cellName)) return true;
            if (cell && cell.site_id && String(row.neName || '').includes(String(cell.site_id))) return true;
            return false;
        });
        return rows.map(function (row) {
            const point = { timestamp: row.startTime, Date: row.startTime };
            counterIds.forEach(function (cid, i) {
                const val = row.counterValues && row.counterValues[i];
                const num = val === 'NIL' || val == null || val === '' ? null : Number(val);
                point[String(cid)] = Number.isFinite(num) ? num : null;
            });
            return point;
        });
    }

    function paRegisterCounterMeta(counter) {
        const id = String(counter.id);
        paCounterMeta[id] = counter;
    }

    function paUpdateKpiDefsFromSelection() {
        const selected = paSelectedCounterIds().map(String);
        if (typeof KPI_DEFS !== 'undefined') {
            KPI_DEFS = selected.map(function (id) {
                const meta = paCounterMeta[id] || {};
                return {
                    key: id,
                    label: meta.name || meta.label || ('Counter ' + id),
                    unit: meta.unit || '',
                    good: null,
                    warn: null,
                    inverse: false,
                    color: typeof _colorFor === 'function' ? _colorFor(id) : '#3498db',
                };
            });
        }
    }

    function paSyncCounterUi() {
        const listEl = document.getElementById('kpi-scope-list');
        const titleEl = document.getElementById('kpi-scope-title');
        const countEl = document.getElementById('kpi-scope-count');
        const metaEl = document.getElementById('pa-counter-meta');
        const tech = paTechnology() || 'all technologies';
        if (titleEl) titleEl.textContent = 'Counters — Huawei · ' + tech;

        paCatalogCounters.forEach(paRegisterCounterMeta);

        if (listEl) {
            if (!tech) {
                listEl.innerHTML = '<p class="kpi-scope-empty">Select a technology to load the counter catalog.</p>';
            } else if (!paCatalogCounters.length) {
                listEl.innerHTML = '<p class="kpi-scope-empty">Pick a function subset or search for counters (e.g. RRC, ERAB).</p>';
            } else {
                let html = '';
                let lastSubset = null;
                paCatalogCounters.forEach(function (c, i) {
                    const sid = c.function_subset_id;
                    if (sid !== lastSubset) {
                        lastSubset = sid;
                        html += '<div class="pa-counter-group-title">' +
                            escHtml((c.function_subset_name || 'Subset') + ' (' + sid + ')') +
                            '</div>';
                    }
                    const id = String(c.id);
                    const checked = (typeof kpiSelectedKeys !== 'undefined' && kpiSelectedKeys.has(id)) ? ' checked' : '';
                    const agg = [c.time_aggregation, c.object_aggregation].filter(Boolean).join(' · ');
                    html += '<label class="kpi-scope-item" title="' + escHtml(id + ' — ' + (c.name || '')) + '">' +
                        '<input type="checkbox" class="kpi-scope-cb" id="kpi-cb-' + i + '" data-kpi-key="' + escHtml(id) + '"' + checked + '>' +
                        '<span class="kpi-scope-item-label">' + escHtml(c.name || c.label || id) +
                        '<small>' + escHtml(id + (agg ? ' · ' + agg : '')) + '</small></span></label>';
                });
                listEl.innerHTML = html;
                listEl.querySelectorAll('.kpi-scope-cb').forEach(function (cb) {
                    cb.addEventListener('change', function () {
                        const key = cb.getAttribute('data-kpi-key');
                        if (!key || typeof kpiSelectedKeys === 'undefined') return;
                        if (cb.checked) kpiSelectedKeys.add(key);
                        else kpiSelectedKeys.delete(key);
                        paUpdateKpiDefsFromSelection();
                        paSyncCounterUi();
                        if (typeof onKpiSelectionChange === 'function') onKpiSelectionChange();
                    });
                });
            }
        }

        const selectedCount = paSelectedCounterIds().length;
        if (countEl) {
            countEl.textContent = selectedCount
                ? (selectedCount + ' selected · ' + paCatalogCounters.length + ' shown')
                : (paCatalogCounters.length ? paCatalogCounters.length + ' shown' : '');
        }
        if (metaEl) {
            const parts = [];
            if (paCatalogNeType) parts.push('MAE NE type: ' + paCatalogNeType);
            if (paCatalogTotal) parts.push(paCatalogTotal.toLocaleString() + ' counters in catalog');
            parts.push('Max 150 counters · ≤10 function subsets per query');
            metaEl.textContent = parts.join(' · ');
        }
        paUpdateKpiDefsFromSelection();
        if (typeof updateKpiSelectAllState === 'function') updateKpiSelectAllState();
    }

    async function paLoadSubsets() {
        const tech = paTechnology();
        const select = document.getElementById('pa-subset-select');
        if (!select) return;
        select.innerHTML = '<option value="">All function subsets…</option>';
        if (!tech) return;

        try {
            const res = await fetch('/api/performance-analytics/counter-subsets?technology=' + encodeURIComponent(tech), {
                credentials: 'same-origin',
            });
            const data = await res.json();
            if (!data.success) return;
            paCatalogNeType = data.ne_type || '';
            (data.subsets || []).forEach(function (s) {
                const opt = document.createElement('option');
                opt.value = String(s.id);
                opt.textContent = (s.name || ('Subset ' + s.id)) + ' (' + (s.counter_count || 0) + ')';
                select.appendChild(opt);
            });
        } catch (_) { /* ignore */ }
    }

    async function paLoadCounters() {
        const tech = paTechnology();
        if (!tech) {
            paCatalogCounters = [];
            paCatalogTotal = 0;
            paSyncCounterUi();
            return;
        }

        const subset = (document.getElementById('pa-subset-select')?.value || '').trim();
        const q = (document.getElementById('pa-counter-search')?.value || '').trim();
        const params = new URLSearchParams({ technology: tech, limit: '300' });
        if (subset) params.set('subset_id', subset);
        if (q) params.set('q', q);
        else if (!subset) {
            paCatalogCounters = [];
            paCatalogTotal = 0;
            paSyncCounterUi();
            return;
        }

        try {
            const res = await fetch('/api/performance-analytics/counters?' + params.toString(), {
                credentials: 'same-origin',
            });
            const data = await res.json();
            if (!data.success) {
                paCatalogCounters = [];
                paCatalogTotal = 0;
            } else {
                paCatalogCounters = data.counters || [];
                paCatalogTotal = data.total || paCatalogCounters.length;
                paCatalogNeType = data.ne_type || paCatalogNeType;
            }
        } catch (_) {
            paCatalogCounters = [];
            paCatalogTotal = 0;
        }
        paSyncCounterUi();
    }

    async function paSelectSubsetCounters() {
        const subset = (document.getElementById('pa-subset-select')?.value || '').trim();
        const tech = paTechnology();
        if (!subset || !tech) {
            if (typeof _perfQueryUserMessage === 'function') {
                _perfQueryUserMessage('Choose a function subset first.');
            }
            return;
        }
        const params = new URLSearchParams({
            technology: tech,
            subset_id: subset,
            limit: '150',
        });
        try {
            const res = await fetch('/api/performance-analytics/counters?' + params.toString(), {
                credentials: 'same-origin',
            });
            const data = await res.json();
            if (!data.success) throw new Error(data.error || 'Failed to load subset counters');
            if (typeof kpiSelectedKeys !== 'undefined') {
                kpiSelectedKeys.clear();
                (data.counters || []).forEach(function (c) {
                    paRegisterCounterMeta(c);
                    kpiSelectedKeys.add(String(c.id));
                });
            }
            paCatalogCounters = data.counters || [];
            paCatalogTotal = data.total || paCatalogCounters.length;
            paSyncCounterUi();
            if (typeof _perfQueryUserMessage === 'function') {
                _perfQueryUserMessage('Selected ' + (data.counters || []).length + ' counter(s) from subset.');
            }
        } catch (err) {
            if (typeof _perfQueryUserMessage === 'function') {
                _perfQueryUserMessage(String(err.message || err));
            }
        }
    }

    async function paLoadDefaultCounters() {
        if (typeof kpiSelectedKeys !== 'undefined') kpiSelectedKeys.clear();
        await paLoadSubsets();
        await paLoadCounters();
    }

    async function paRunQuery() {
        if (!paConfigured()) {
            if (typeof _perfQueryUserMessage === 'function') {
                _perfQueryUserMessage('Configure HUAWEI_CM_* in .env (port 31127).');
            }
            return;
        }

        const tech = paTechnology();
        if (!tech) {
            if (typeof _perfQueryUserMessage === 'function') {
                _perfQueryUserMessage('Select a technology.');
            }
            return;
        }

        const counterIds = paSelectedCounterIds();
        if (!counterIds.length) {
            if (typeof _perfQueryUserMessage === 'function') {
                _perfQueryUserMessage('Select at least one counter (subset or search).');
            }
            return;
        }
        if (counterIds.length > 150) {
            if (typeof _perfQueryUserMessage === 'function') {
                _perfQueryUserMessage('Select at most 150 counters per query.');
            }
            return;
        }

        const keys = paCollectCellKeys();
        if (!keys.length) {
            if (typeof _perfQueryUserMessage === 'function') {
                _perfQueryUserMessage('Select one or more cells in the tree.');
            }
            return;
        }

        const tw = paTimeWindow();
        const loading = document.getElementById('loading-charts');
        const queryBtn = document.getElementById('btn-perf-query');
        const chartsHost = document.querySelector('.charts-area');
        if (typeof setButtonLoading === 'function') setButtonLoading(queryBtn, true, 'Querying…');
        if (loading) loading.style.display = 'flex';
        if (typeof showPanelLoading === 'function') showPanelLoading(chartsHost, 'Querying MAE…');

        try {
            const res = await fetch('/api/performance-analytics/query', {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    technology: tech,
                    startTime: tw.startTime,
                    endTime: tw.endTime,
                    period: tw.period,
                    counterIds: counterIds,
                    cellKeys: keys,
                    siteIds: paSiteIdsFromKeys(keys),
                }),
            });
            const data = await res.json();
            if (!res.ok || !data.success) {
                throw new Error(data.error || 'Query failed');
            }

            paLastQueryPayload = data.query || {};
            paLastTablePayload = paTransformToTablePayload(paLastQueryPayload);
            paTablePage = 1;
            paTableSearch = '';
            const searchInput = document.getElementById('hw-search');
            if (searchInput) searchInput.value = '';

            if (typeof lastQueryCellKeys !== 'undefined') lastQueryCellKeys = [...keys];
            if (typeof hwCurrentScopedCellNames !== 'undefined') {
                hwCurrentScopedCellNames = paCellsFromKeys(keys).map(function (c) { return c.cell_name; });
            }

            const addBtn = document.getElementById('btn-add-charts');
            if (addBtn) addBtn.style.display = 'inline-flex';
            const exportBtn = document.getElementById('btn-export');
            if (exportBtn) exportBtn.style.display = 'inline-flex';
            const viewToggle = document.getElementById('view-toggle');
            if (viewToggle) viewToggle.style.display = 'flex';

            if (typeof switchViewMode === 'function') switchViewMode('table');
            paRenderTablePage();

            const title = document.getElementById('charts-title');
            if (title) {
                title.textContent = (paLastQueryPayload.recordCount || 0) + ' PM row(s) from MAE · ' + tech;
            }
            const noSel = document.getElementById('no-selection');
            if (noSel) noSel.style.display = 'none';

            if (typeof _perfQueryUserMessage === 'function') {
                _perfQueryUserMessage(paLastQueryPayload.retMessage || 'Query complete.');
            }
        } catch (err) {
            if (typeof _perfQueryUserMessage === 'function') {
                _perfQueryUserMessage(String(err.message || err));
            }
        } finally {
            if (loading) loading.style.display = 'none';
            if (typeof setButtonLoading === 'function') setButtonLoading(queryBtn, false);
            if (typeof hidePanelLoading === 'function') hidePanelLoading(chartsHost);
        }
    }

    window.paExportCsv = function paExportCsv() {
        if (!paLastTablePayload || !paLastTablePayload.rows || !paLastTablePayload.rows.length) return;
        const cols = paLastTablePayload.columns || [];
        const labels = paLastTablePayload.column_labels || {};
        const header = cols.map(function (c) { return labels[c] || c; }).join(',');
        const lines = paLastTablePayload.rows.map(function (row) {
            return cols.map(function (c) {
                const v = row[c] == null ? '' : String(row[c]);
                return v.includes(',') || v.includes('"') ? '"' + v.replace(/"/g, '""') + '"' : v;
            }).join(',');
        });
        const blob = new Blob([header + '\n' + lines.join('\n')], { type: 'text/csv;charset=utf-8' });
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = 'huawei_pm_api_' + new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-') + '.csv';
        a.click();
        URL.revokeObjectURL(a.href);
    };

    // ── Override performance.js hooks ─────────────────────────────
    window.runPerformanceQuery = paRunQuery;

    window.loadKpiColumns = async function () {
        await paLoadDefaultCounters();
    };

    window.loadPmTable = async function (_vendor, _technology, search, page) {
        paTableSearch = search || '';
        paTablePage = page || 1;
        if (!paLastTablePayload) {
            const container = document.getElementById('hw-table-container');
            if (container) {
                container.innerHTML = '<p class="hw-empty-msg">Run <strong>Query</strong> to fetch live PM data from MAE.</p>';
            }
            return;
        }
        paRenderTablePage();
    };

    window.fetchCellTrendData = async function (cellKey) {
        const cell = paCellsFromKeys([cellKey])[0] || { cell_name: cellKey, cell_key: cellKey };
        const trend = paTrendFromQuery(cellKey);
        return { success: true, cell: cell, trend: trend };
    };

    window.onDataScopeChange = function () { /* hourly-only for live API */ };

    window.onFilterTechChange = async function () {
        if (typeof onVendorChange === 'function') await onVendorChange();
        await paLoadDefaultCounters();
    };

    // ── Boot ──────────────────────────────────────────────────────
    document.addEventListener('DOMContentLoaded', async function () {
        const vendorEl = document.getElementById('filter-vendor');
        if (vendorEl) vendorEl.value = 'Huawei';

        document.getElementById('pa-subset-select')?.addEventListener('change', function () {
            paLoadCounters();
        });

        document.getElementById('pa-subset-all-btn')?.addEventListener('click', function () {
            paSelectSubsetCounters();
        });

        document.getElementById('pa-counter-search')?.addEventListener('input', function () {
            clearTimeout(paSearchTimer);
            paSearchTimer = setTimeout(function () { paLoadCounters(); }, 250);
        });

        document.getElementById('kpi-select-all')?.addEventListener('change', function (e) {
            const checked = e.target.checked;
            if (typeof kpiSelectedKeys !== 'undefined') {
                if (checked) {
                    paCatalogCounters.forEach(function (c) { kpiSelectedKeys.add(String(c.id)); });
                } else {
                    paCatalogCounters.forEach(function (c) { kpiSelectedKeys.delete(String(c.id)); });
                }
            }
            paSyncCounterUi();
            if (typeof onKpiSelectionChange === 'function') onKpiSelectionChange();
        });

        document.getElementById('pa-test-btn')?.addEventListener('click', async function () {
            try {
                const res = await fetch('/api/performance-analytics/test-connection', {
                    method: 'POST',
                    credentials: 'same-origin',
                });
                const data = await res.json();
                const msg = data.success ? (data.message || 'Connection OK') : (data.error || 'Failed');
                if (typeof _perfQueryUserMessage === 'function') _perfQueryUserMessage(msg);
            } catch (err) {
                if (typeof _perfQueryUserMessage === 'function') _perfQueryUserMessage(String(err));
            }
        });

        if (typeof loadFilters === 'function') await loadFilters();
        if (typeof onVendorChange === 'function') await onVendorChange();
        await paLoadDefaultCounters();
    });
})();
