(function () {
    'use strict';

    const body = document.body;
    const vendor = body.dataset.vendor || 'nokia';
    const rat = body.dataset.rat || '3G';

    const state = {
        kpi: '',
        kpis: [],
        precomputedKpis: {},
        totalKpiCount: 0,
        kpiFilter: '',
        area: '',
        cluster: null,
        sort: 'increased',
        columnSort: { field: 'delta', dir: 'desc' },
        cellFilter: '',
        selectedCell: null,
        cells: [],
        tableByKpi: null,
        tableLoading: false,
        kpiLoading: null,
        charts: { daily: null, hourly: null },
        categories: {},
        kpiCategories: {},
        scorecard: [],
    };

    function esc(s) {
        if (window.escapeHtml) return window.escapeHtml(s);
        const d = document.createElement('div');
        d.textContent = s == null ? '' : String(s);
        return d.innerHTML;
    }

    function fmtNum(v) {
        if (v == null || v === '') return '—';
        const n = Number(v);
        if (Number.isNaN(n)) return esc(v);
        return n.toFixed(2);
    }

    function currentPreset() {
        const cat = state.kpiCategories[state.kpi];
        if (cat && state.categories[cat]) {
            return Object.assign({ name: cat }, state.categories[cat]);
        }
        return null;
    }

    function isWorseDelta(delta, preset) {
        const n = Number(delta);
        if (Number.isNaN(n) || n === 0) return false;
        if (preset && preset.direction === 'lower_worse') return n < 0;
        return n > 0;
    }

    function fmtThreshold(v) {
        if (v == null || v === '') return '';
        const n = Number(v);
        if (Number.isNaN(n)) return String(v);
        return (Math.abs(n) >= 10 ? n.toFixed(0) : n.toFixed(1));
    }

    function showPrecalcStaleBanner() {
        const el = document.getElementById('nh-precalc-stale-banner');
        if (el) el.remove();
    }

    function shortKpiLabel(name, maxLen) {
        const s = String(name || '');
        if (s.length <= (maxLen || 14)) return s;
        return s.slice(0, (maxLen || 14) - 1) + '…';
    }

    function params(extra) {
        const p = new URLSearchParams();
        p.set('vendor', vendor);
        p.set('rat', rat);
        if (state.kpi) p.set('kpi', state.kpi);
        if (state.area) p.set('area', state.area);
        if (state.cluster != null) p.set('cluster', String(state.cluster));
        if (extra) {
            Object.keys(extra).forEach(function (k) {
                p.set(k, extra[k]);
            });
        }
        return p.toString();
    }

    async function loadAreas() {
        const list = document.getElementById('nh-area-list');
        if (!list) return;
        try {
            const res = await fetch('/api/network-health/areas', { credentials: 'same-origin' });
            const data = await res.json();
            if (!data.success) return;

            const allBtn = document.createElement('button');
            allBtn.type = 'button';
            allBtn.className = 'nh-area-btn active';
            allBtn.dataset.area = '';
            allBtn.textContent = 'All';
            list.appendChild(allBtn);

            (data.areas || []).forEach(function (a) {
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'nh-area-btn';
                btn.dataset.area = a;
                btn.textContent = a;
                list.appendChild(btn);
            });
        } catch (e) { /* ignore */ }
    }

    async function loadClusters() {
        const grid = document.getElementById('nh-cluster-grid');
        if (!grid) return;
        grid.innerHTML = '';
        try {
            const q = state.area ? '?area=' + encodeURIComponent(state.area) : '';
            const res = await fetch('/api/network-health/clusters' + q, { credentials: 'same-origin' });
            const data = await res.json();
            if (!data.success) return;

            const allBtn = document.createElement('button');
            allBtn.type = 'button';
            allBtn.className = 'nh-cluster-btn' + (state.cluster == null ? ' active' : '');
            allBtn.dataset.cluster = '';
            allBtn.textContent = 'All';
            grid.appendChild(allBtn);

            (data.clusters || []).forEach(function (c) {
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'nh-cluster-btn' + (state.cluster === c ? ' active' : '');
                btn.dataset.cluster = String(c);
                btn.textContent = String(c);
                grid.appendChild(btn);
            });
        } catch (e) { /* ignore */ }
    }

    function filteredKpis() {
        const q = (state.kpiFilter || '').trim().toLowerCase();
        if (!q) return state.kpis.slice();
        return state.kpis.filter(function (k) {
            return String(k).toLowerCase().indexOf(q) >= 0;
        });
    }

    function orderedKpis() {
        const list = filteredKpis();
        const pre = state.precomputedKpis || {};
        const ready = [];
        const rest = [];
        list.forEach(function (k) {
            if (pre[k]) ready.push(k);
            else rest.push(k);
        });
        return ready.concat(rest);
    }

    function precomputedCount() {
        return Object.keys(state.precomputedKpis || {}).filter(function (k) {
            return state.kpis.indexOf(k) >= 0;
        }).length;
    }

    function isKpiReady(kpi) {
        return !!(state.tableByKpi && state.tableByKpi[kpi]);
    }

    async function ensureKpiLoaded(kpi) {
        if (!kpi) return false;
        if (!state.tableByKpi) state.tableByKpi = {};
        if (state.tableByKpi[kpi]) return true;
        if (state.kpiLoading === kpi) return false;

        state.kpiLoading = kpi;
        try {
            const res = await fetch(
                '/api/network-health/cells?vendor=' + encodeURIComponent(vendor) +
                '&rat=' + encodeURIComponent(rat) +
                '&kpi=' + encodeURIComponent(kpi) +
                '&all=1',
                { credentials: 'same-origin' }
            );
            const data = await res.json();
            if (!data.success) return false;
            state.tableByKpi[kpi] = data.cells || [];
            return true;
        } catch (e) {
            return false;
        } finally {
            if (state.kpiLoading === kpi) state.kpiLoading = null;
        }
    }

    function updateKpiSelect() {
        const sel = document.getElementById('nh-kpi-select');
        if (!sel) return;
        const list = orderedKpis();
        const prev = state.kpi;
        sel.innerHTML = '';
        if (!list.length) {
            const opt = document.createElement('option');
            opt.value = '';
            opt.textContent = state.kpis.length ? 'No KPI match' : 'No KPIs found';
            sel.appendChild(opt);
            return;
        }
        list.forEach(function (kpi) {
            const opt = document.createElement('option');
            opt.value = kpi;
            opt.textContent = kpi;
            if (kpi === prev) opt.selected = true;
            sel.appendChild(opt);
        });
        if (!list.includes(prev)) {
            state.kpi = list[0];
            sel.value = list[0];
        }
    }

    function updateKpiCount(total) {
        const el = document.getElementById('nh-kpi-count');
        if (!el) return;
        const shown = filteredKpis().length;
        const totalN = total != null ? total : (state.totalKpiCount || state.kpis.length);
        const ready = precomputedCount();
        el.textContent = shown + ' / ' + totalN + ' KPIs · ' + ready + ' ready · ' + rat;
    }

    function scrollActiveKpiTab() {
        const nav = document.getElementById('nh-tabs');
        if (!nav) return;
        const active = nav.querySelector('.nh-tab.active');
        if (active && active.scrollIntoView) {
            active.scrollIntoView({ block: 'nearest', inline: 'center', behavior: 'smooth' });
        }
    }

    function renderKpiTabs(options) {
        const nav = document.getElementById('nh-tabs');
        const loading = document.getElementById('nh-tabs-loading');
        if (!nav) return;
        const prevKpi = state.kpi;
        nav.innerHTML = '';

        const list = orderedKpis();
        if (!state.kpis.length) {
            nav.innerHTML = '<span class="nh-tabs-empty">No KPIs found for this RAT</span>';
            if (loading) loading.hidden = true;
            updateKpiCount(0);
            return;
        }
        if (!list.length) {
            nav.innerHTML = '<span class="nh-tabs-empty">No KPI matches filter</span>';
            if (loading) loading.hidden = true;
            updateKpiCount(state.totalKpiCount || state.kpis.length);
            return;
        }

        if (loading) loading.hidden = true;

        list.forEach(function (kpi) {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'nh-tab' + (state.kpi === kpi ? ' active' : '');
            if (!state.precomputedKpis[kpi]) btn.classList.add('nh-tab-on-demand');
            btn.dataset.kpi = kpi;
            btn.title = kpi + (state.precomputedKpis[kpi] ? '' : ' (loads on select)');
            btn.textContent = shortKpiLabel(kpi, 28);
            btn.setAttribute('role', 'tab');
            btn.setAttribute('aria-selected', state.kpi === kpi ? 'true' : 'false');
            nav.appendChild(btn);
        });

        let kpiChanged = false;
        if (!state.kpi || state.kpis.indexOf(state.kpi) < 0) {
            state.kpi = list[0] || '';
            kpiChanged = true;
        } else if (list.indexOf(state.kpi) < 0) {
            state.kpi = list[0] || '';
            kpiChanged = true;
        }
        updateKpiSelect();
        updateKpiCount(state.totalKpiCount || state.kpis.length);
        scrollActiveKpiTab();

        if (kpiChanged && prevKpi !== state.kpi && !(options && options.skipReload)) {
            setKpi(state.kpi, true);
        }
    }

    async function setKpi(kpi, reload) {
        if (!kpi || state.kpis.indexOf(kpi) < 0) return;
        state.kpi = kpi;
        document.querySelectorAll('.nh-tab').forEach(function (btn) {
            const active = btn.dataset.kpi === kpi;
            btn.classList.toggle('active', active);
            btn.setAttribute('aria-selected', active ? 'true' : 'false');
        });
        const sel = document.getElementById('nh-kpi-select');
        if (sel && sel.value !== kpi) sel.value = kpi;
        if (reload !== false) {
            const tbody = document.getElementById('nh-tbody');
            if (!isKpiReady(kpi) && tbody) {
                tbody.innerHTML = '<tr><td colspan="5" class="nh-empty">Loading KPI…</td></tr>';
            }
            await ensureKpiLoaded(kpi);
            refreshTable(true);
            renderScorecard();
            scrollActiveKpiTab();
        }
    }

    function cellDataAttr(name) {
        return encodeURIComponent(String(name || ''));
    }

    function cellFromRow(tr) {
        if (!tr) return '';
        return decodeURIComponent(tr.getAttribute('data-cell') || '');
    }

    function selectCell(cellName, options) {
        if (!cellName) {
            state.selectedCell = null;
            document.querySelectorAll('#nh-tbody tr[data-cell]').forEach(function (tr) {
                tr.classList.remove('selected');
            });
            updateRncDisplay();
            loadCellTrend(null);
            return;
        }
        state.selectedCell = cellName;
        document.querySelectorAll('#nh-tbody tr[data-cell]').forEach(function (tr) {
            tr.classList.toggle('selected', cellFromRow(tr) === cellName);
        });
        updateRncDisplay();
        loadCellTrend(cellName);
        if (options && options.scroll) {
            const row = document.querySelector('#nh-tbody tr.selected');
            if (row) row.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
        }
    }

    function rowCluster(r) {
        const n = Number(r && r.cluster);
        if (Number.isFinite(n)) return n;
        const m = String((r && r.cell_name) || '').match(/^(\d{3,6})/);
        if (!m) return null;
        return Math.floor(parseInt(m[1], 10) / 100);
    }

    function filterTableRows(rows) {
        const q = (state.cellFilter || '').trim().toLowerCase();
        const preset = currentPreset();
        return (rows || []).filter(function (r) {
            if (state.area && String(r.area || '') !== state.area) return false;
            if (state.cluster != null && rowCluster(r) !== state.cluster) return false;
            if (q && String(r.cell_name || '').toLowerCase().indexOf(q) < 0) return false;
            if (state.sort === 'breached') {
                if (r.breached === true) return true;
                if (r.breached === false) return false;
                const post = r.post != null ? Number(r.post) : NaN;
                const thr = preset && preset.threshold_bad;
                if (preset && !Number.isNaN(post) && thr != null) {
                    return preset.direction === 'lower_worse' ? post < Number(thr) : post > Number(thr);
                }
                return false;
            }
            return true;
        });
    }

    function refreshTable(resetSelection) {
        if (!state.kpi) return;
        const tbody = document.getElementById('nh-tbody');
        if (!state.tableByKpi) {
            if (tbody && !state.tableLoading) {
                tbody.innerHTML = '<tr><td colspan="5" class="nh-empty">Loading table…</td></tr>';
            }
            return;
        }
        if (!state.tableByKpi[state.kpi] && state.kpiLoading === state.kpi) {
            if (tbody) tbody.innerHTML = '<tr><td colspan="5" class="nh-empty">Loading KPI…</td></tr>';
            return;
        }
        if (resetSelection) state.selectedCell = null;
        const rows = filterTableRows(state.tableByKpi[state.kpi] || []);
        state.cells = rows;
        renderTable(sortRows(rows), { keepSelection: !resetSelection });
    }

    async function loadPrecalcStatus() {
        const tbody = document.getElementById('nh-tbody');
        const loading = document.getElementById('nh-tabs-loading');
        state.tableLoading = true;
        state.tableByKpi = {};
        state.selectedCell = null;

        try {
            const res = await fetch(
                '/api/network-health/table?vendor=' + encodeURIComponent(vendor) +
                '&rat=' + encodeURIComponent(rat),
                { credentials: 'same-origin' }
            );
            const data = await res.json();
            if (!data.success) {
                if (tbody) tbody.innerHTML = '<tr><td colspan="5" class="nh-empty">' + esc(data.error || 'Failed') + '</td></tr>';
                if (loading) loading.textContent = data.error || 'Failed to load table';
                return;
            }
            if (!data.precalc_ready) {
                let hint = 'Precomputed data not built yet.';
                if (data.precalc_stale) {
                    hint = 'Precomputed data is stale (PM files changed). Rebuild required.';
                } else if (data.precalc_empty) {
                    hint = 'Precomputed store is empty (no cells matched PM). Rebuild after PM/cell-column fix.';
                }
                if (tbody) {
                    tbody.innerHTML = '<tr><td colspan="5" class="nh-empty">' + esc(hint) +
                        ' Run: python scripts/build_network_health_precalc.py --vendor ' +
                        vendor + ' --rat ' + rat + '</td></tr>';
                }
                if (loading) loading.textContent = hint;
                return;
            }
            state.precomputedKpis = {};
            (data.precomputed_kpis || []).forEach(function (k) {
                state.precomputedKpis[k] = true;
            });
            state.totalKpiCount = data.total_kpi_count || state.kpis.length;
            showPrecalcStaleBanner();
            if (loading) loading.hidden = true;
            if (!state.kpi) {
                const pre = data.precomputed_kpis || [];
                state.kpi = pre.length ? pre[0] : (state.kpis[0] || '');
            }
            renderKpiTabs({ skipReload: true });
            if (tbody) tbody.innerHTML = '<tr><td colspan="5" class="nh-empty">Loading KPI…</td></tr>';
            await ensureKpiLoaded(state.kpi);
            refreshTable(true);
        } catch (e) {
            if (tbody) tbody.innerHTML = '<tr><td colspan="5" class="nh-empty">Load failed.</td></tr>';
            if (loading) loading.textContent = 'Failed to load table';
        } finally {
            state.tableLoading = false;
        }
    }

    async function loadKpis() {
        const loading = document.getElementById('nh-tabs-loading');
        try {
            const res = await fetch(
                '/api/network-health/kpis?vendor=' + encodeURIComponent(vendor) +
                '&rat=' + encodeURIComponent(rat),
                { credentials: 'same-origin' }
            );
            const data = await res.json();
            if (!data.success) {
                if (loading) loading.textContent = data.error || 'Failed to load KPIs';
                return;
            }
            if (data.vendor && data.vendor !== vendor) {
                if (loading) loading.textContent = 'Vendor mismatch — reload the page';
                return;
            }
            if (data.rat && data.rat !== rat) {
                if (loading) loading.textContent = 'RAT mismatch — reload the page';
                return;
            }
            state.kpis = data.columns || [];
            state.precomputedKpis = {};
            (data.precomputed_kpis || []).forEach(function (k) {
                state.precomputedKpis[k] = true;
            });
            state.totalKpiCount = data.count || state.kpis.length;
            state.categories = data.categories || {};
            state.kpiCategories = data.kpi_categories || {};
            if (!state.kpis.length) {
                if (loading) {
                    loading.textContent = 'No KPIs for ' + vendor + ' / ' + rat;
                    loading.hidden = false;
                }
                renderKpiTabs({ skipReload: true });
                return;
            }
            if (loading) loading.hidden = true;
            const urlKpi = new URLSearchParams(window.location.search).get('kpi');
            if (urlKpi && state.kpis.indexOf(urlKpi) >= 0) {
                state.kpi = urlKpi;
            } else if (data.precomputed_kpis && data.precomputed_kpis.length) {
                state.kpi = data.precomputed_kpis[0];
            }
            renderKpiTabs();
            await loadPrecalcStatus();
        } catch (e) {
            if (loading) loading.textContent = 'Failed to load KPIs';
        }
    }

    function updateRncDisplay() {
        const box = document.getElementById('nh-rnc-box');
        if (!box) return;
        const cell = state.cells.find(function (c) {
            return c.cell_name === state.selectedCell;
        }) || state.cells[0];
        if (!cell) {
            box.textContent = '—';
            return;
        }
        const rnc = String(cell.rnc || '').trim();
        box.textContent = rnc || '—';
    }

    function prePostValues(row) {
        const pre = row.pre != null ? row.pre : row.week_avg;
        const post = row.post != null ? row.post : row.today_value;
        const preN = pre == null || pre === '' ? null : Number(pre);
        const postN = post == null || post === '' ? null : Number(post);
        return {
            pre: Number.isNaN(preN) ? null : preN,
            post: Number.isNaN(postN) ? null : postN,
        };
    }

    function isNoChangeRow(row) {
        const vals = prePostValues(row);
        if (vals.pre == null || vals.post == null) return false;
        return vals.pre.toFixed(2) === vals.post.toFixed(2);
    }

    function rowNumericField(row, field) {
        if (field === 'pre') return prePostValues(row).pre;
        if (field === 'post') return prePostValues(row).post;
        if (field === 'delta') {
            const n = Number(row.delta);
            return Number.isNaN(n) ? null : n;
        }
        if (field === 'vs_threshold' || field === 'score') {
            const n = Number(row.vs_threshold != null ? row.vs_threshold : row.score);
            return Number.isNaN(n) ? null : n;
        }
        return null;
    }

    function updateSortHeaderUi() {
        const field = state.columnSort.field || 'delta';
        const dir = state.columnSort.dir || 'desc';
        document.querySelectorAll('.nh-sort-th').forEach(function (btn) {
            const active = btn.dataset.sort === field;
            btn.classList.toggle('active', active);
            const icon = btn.querySelector('.nh-sort-icon');
            if (icon) icon.textContent = active ? (dir === 'asc' ? '▲' : '▼') : '';
        });
    }

    function sortRows(rows) {
        const list = (rows || []).slice();
        const field = state.columnSort.field || 'delta';
        const asc = state.columnSort.dir === 'asc';

        if (state.sort === 'breached') {
            list.sort(function (a, b) {
                const as = Number(a.score != null ? a.score : a.vs_threshold);
                const bs = Number(b.score != null ? b.score : b.vs_threshold);
                const av = Number.isNaN(as) ? -1 : as;
                const bv = Number.isNaN(bs) ? -1 : bs;
                if (av !== bv) return bv - av;
                return String(a.cell_name || '').localeCompare(String(b.cell_name || ''));
            });
            return list;
        }

        if (state.sort === 'no_change' && field === 'delta') {
            list.sort(function (a, b) {
                const aNc = isNoChangeRow(a) ? 0 : 1;
                const bNc = isNoChangeRow(b) ? 0 : 1;
                if (aNc !== bNc) return aNc - bNc;
                const d = Math.abs(Number(a.delta || 0)) - Math.abs(Number(b.delta || 0));
                return d !== 0 ? d : String(a.cell_name || '').localeCompare(String(b.cell_name || ''));
            });
            return list;
        }

        if (field === 'cell_name') {
            list.sort(function (a, b) {
                const c = String(a.cell_name || '').localeCompare(String(b.cell_name || ''));
                return asc ? c : -c;
            });
            return list;
        }

        list.sort(function (a, b) {
            const av = rowNumericField(a, field);
            const bv = rowNumericField(b, field);
            if (av == null && bv == null) {
                return String(a.cell_name || '').localeCompare(String(b.cell_name || ''));
            }
            if (av == null) return 1;
            if (bv == null) return -1;
            if (av !== bv) return asc ? av - bv : bv - av;
            return String(a.cell_name || '').localeCompare(String(b.cell_name || ''));
        });
        return list;
    }

    function renderTable(rows, options) {
        const tbody = document.getElementById('nh-tbody');
        const title = document.getElementById('nh-table-title');
        if (!tbody) return;

        const preset = currentPreset();
        if (title) {
            let label = state.kpi || '—';
            if (preset) {
                const gte = preset.direction === 'lower_worse';
                label += ' · ' + preset.name + ' target ' + (gte ? '≥' : '≤') + fmtThreshold(preset.threshold_bad);
            }
            title.textContent = label;
        }

        if (!rows.length) {
            tbody.innerHTML = '<tr><td colspan="5" class="nh-empty">No cells match filters.</td></tr>';
            selectCell(null);
            return;
        }

        const rowNames = rows.map(function (r) { return r.cell_name; });
        const keepSelection = options && options.keepSelection;
        if (!keepSelection || !state.selectedCell || rowNames.indexOf(state.selectedCell) < 0) {
            state.selectedCell = rows[0].cell_name;
        }

        tbody.innerHTML = rows.map(function (r) {
            const sel = r.cell_name === state.selectedCell ? ' selected' : '';
            const worse = isWorseDelta(r.delta, preset);
            const better = Number(r.delta) !== 0 && !worse && r.delta != null;
            const deltaCls = worse ? 'delta-worse' : (better ? 'delta-better' : '');
            const noChange = isNoChangeRow(r);
            const breached = r.breached === true;
            const vs = r.vs_threshold != null ? r.vs_threshold : '';
            return '<tr data-cell="' + cellDataAttr(r.cell_name) + '" class="' +
                (sel.trim() + (noChange ? ' no-change' : '') + (breached ? ' nh-breached' : '')).trim() +
                '" title="Click to view trend">' +
                '<td class="cell-name">' + esc(r.cell_name) + '</td>' +
                '<td class="num">' + fmtNum(r.pre != null ? r.pre : r.week_avg) + '</td>' +
                '<td class="num">' + fmtNum(r.post != null ? r.post : r.today_value) + '</td>' +
                '<td class="num ' + deltaCls + '">' + fmtNum(r.delta) + '</td>' +
                '<td class="num ' + (breached ? 'delta-worse' : '') + '">' +
                    (vs === '' ? '—' : fmtNum(vs)) + '</td>' +
                '</tr>';
        }).join('');

        if (!(options && options.skipCharts)) {
            selectCell(state.selectedCell, { scroll: false });
        }
    }

    async function loadCells() {
        refreshTable(true);
    }

    function exportTableCsv() {
        if (!state.kpi) {
            showNotification('Select a KPI first', 'info');
            return;
        }
        const rows = sortRows(filterTableRows(state.tableByKpi[state.kpi] || []));
        if (!rows.length) {
            showNotification('No rows to export', 'info');
            return;
        }
        const escCsv = function (v) {
            const s = v == null ? '' : String(v);
            if (/[",\n\r]/.test(s)) return '"' + s.replace(/"/g, '""') + '"';
            return s;
        };
        const lines = [
            ['KPI', 'Cell Name', 'Pre', 'Post', 'Delta', 'vs target', 'Breached', 'Area', 'Cluster', 'RNC', 'Vendor'].map(escCsv).join(','),
        ];
        rows.forEach(function (r) {
            const vals = prePostValues(r);
            lines.push([
                state.kpi,
                r.cell_name,
                vals.pre != null ? vals.pre : (r.week_avg != null ? r.week_avg : ''),
                vals.post != null ? vals.post : (r.today_value != null ? r.today_value : ''),
                r.delta,
                r.vs_threshold != null ? r.vs_threshold : '',
                r.breached ? 'yes' : '',
                r.area || '',
                r.cluster != null ? r.cluster : '',
                r.rnc || '',
                r.vendor || '',
            ].map(escCsv).join(','));
        });
        const blob = new Blob([lines.join('\r\n')], { type: 'text/csv;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        const safeKpi = String(state.kpi).replace(/[^\w.-]+/g, '_').slice(0, 40);
        a.href = url;
        a.download = 'network_health_' + vendor + '_' + rat + '_' + safeKpi + '.csv';
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
    }

    function destroyChart(key) {
        if (state.charts[key]) {
            state.charts[key].destroy();
            state.charts[key] = null;
        }
    }

    function setChartEmpty(canvasId, emptyId, isEmpty, message) {
        const canvas = document.getElementById(canvasId);
        const empty = document.getElementById(emptyId);
        const wrap = canvas ? canvas.closest('.nh-chart-canvas-wrap') : null;
        const block = canvas ? canvas.closest('.nh-chart-block') : null;
        if (block) block.hidden = false;
        if (canvas) canvas.hidden = !!isEmpty;
        if (wrap) wrap.hidden = !!isEmpty;
        if (empty) {
            empty.hidden = !isEmpty;
            if (isEmpty && message) empty.textContent = message;
        }
    }

    function chartTheme() {
        const dark = document.body?.classList?.contains('dark-mode');
        return dark
            ? { tick: '#a9b7c9', grid: 'rgba(148, 163, 184, 0.12)', legend: '#d8e2ef' }
            : { tick: '#6d7f92', grid: 'rgba(127, 166, 194, 0.16)', legend: '#2c3e50' };
    }

    function buildChart(canvasId, key, labels, avgValues, linearValues, yLabel, seriesLabel) {
        destroyChart(key);
        setChartEmpty(canvasId, canvasId + '-empty', false);
        const canvas = document.getElementById(canvasId);
        if (!canvas || typeof Chart === 'undefined') return;

        const prefix = seriesLabel || (key === 'hourly' ? 'Hourly' : 'Daily');
        const ctx = canvas.getContext('2d');
        const theme = chartTheme();
        const isHourly = key === 'hourly';
        const datasets = [
            {
                label: prefix + ' · ' + yLabel,
                data: avgValues,
                borderColor: '#7fa6c2',
                backgroundColor: 'rgba(127, 166, 194, 0.12)',
                borderWidth: 2.5,
                pointRadius: 0,
                pointHoverRadius: 3,
                tension: 0.28,
                fill: true,
            },
            {
                label: prefix + ' trend',
                data: linearValues,
                borderColor: '#6d95b3',
                backgroundColor: 'transparent',
                borderWidth: 1.5,
                borderDash: [5, 4],
                pointRadius: 0,
                tension: 0,
            },
        ];
        const preset = currentPreset();
        if (preset && preset.threshold_bad != null && labels.length) {
            const thr = Number(preset.threshold_bad);
            if (!Number.isNaN(thr)) {
                datasets.push({
                    label: 'Target ' + fmtThreshold(thr),
                    data: labels.map(function () { return thr; }),
                    borderColor: '#e67e22',
                    backgroundColor: 'transparent',
                    borderWidth: 1.5,
                    borderDash: [6, 4],
                    pointRadius: 0,
                    tension: 0,
                });
            }
        }
        state.charts[key] = new Chart(ctx, {
            type: 'line',
            data: { labels: labels, datasets: datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                layout: { padding: { top: 6, right: 10, bottom: 2, left: 4 } },
                plugins: {
                    legend: {
                        display: true,
                        position: 'top',
                        align: 'start',
                        labels: {
                            color: theme.legend,
                            boxWidth: 10,
                            font: { size: 11, weight: '600' },
                            padding: 6,
                        },
                    },
                    tooltip: {
                        callbacks: {
                            title: function (items) {
                                if (!items.length) return '';
                                const idx = items[0].dataIndex;
                                return String(labels[idx] || '');
                            },
                        },
                    },
                },
                scales: {
                    x: {
                        ticks: {
                            color: theme.tick,
                            maxTicksLimit: isHourly ? 8 : 10,
                            maxRotation: 0,
                            autoSkip: true,
                            font: { size: 11 },
                        },
                        grid: { color: theme.grid },
                    },
                    y: {
                        ticks: { color: theme.tick, font: { size: 11 } },
                        grid: { color: theme.grid },
                    },
                },
            },
        });
        requestAnimationFrame(function () {
            if (state.charts[key]) state.charts[key].resize();
        });
    }

    function shortLabel(text, max) {
        const s = String(text || '');
        if (s.length <= max) return s;
        return s.slice(0, max - 3) + '…';
    }

    function formatHourlyTick(ts) {
        const s = String(ts || '').trim();
        if (!s) return '';
        const m = s.match(/(\d{4})-(\d{2})-(\d{2})[ T](\d{2})/);
        if (m) return m[2] + '-' + m[3] + ' ' + m[4] + 'h';
        return shortLabel(s, 11);
    }

    async function loadCellTrend(cellName) {
        const head = document.getElementById('nh-chart-title');
        if (head) head.textContent = cellName || 'Select a cell';
        if (!cellName || !state.kpi) {
            destroyChart('daily');
            destroyChart('hourly');
            setChartEmpty('nh-chart-daily', 'nh-chart-daily-empty', true, 'Select a cell');
            setChartEmpty('nh-chart-hourly', 'nh-chart-hourly-empty', true, 'Select a cell');
            return;
        }

        try {
            const res = await fetch(
                '/api/network-health/cell-trend?' + params({ cell_name: cellName }),
                { credentials: 'same-origin' }
            );
            const data = await res.json();
            if (!data.success) return;

            const kpiLabel = shortKpiLabel(data.kpi_label || state.kpi, 24);

            if (data.daily && data.daily.length) {
                const labels = data.daily.map(function (p) {
                    const d = String(p.day || '');
                    return d.length >= 10 ? d.slice(5) : d;
                });
                buildChart(
                    'nh-chart-daily',
                    'daily',
                    labels,
                    data.daily.map(function (p) { return p.value; }),
                    data.daily.map(function (p) { return p.linear; }),
                    kpiLabel,
                    'Daily'
                );
            } else {
                destroyChart('daily');
                setChartEmpty('nh-chart-daily', 'nh-chart-daily-empty', true, 'No daily data for this cell');
            }

            if (data.hourly && data.hourly.length) {
                const hourly = data.hourly;
                const labels = hourly.map(function (p) {
                    return formatHourlyTick(p.timestamp);
                });
                buildChart(
                    'nh-chart-hourly',
                    'hourly',
                    labels,
                    hourly.map(function (p) { return p.value; }),
                    hourly.map(function (p) { return p.linear; }),
                    kpiLabel,
                    'Hourly'
                );
            } else {
                destroyChart('hourly');
                setChartEmpty('nh-chart-hourly', 'nh-chart-hourly-empty', true, 'No hourly data for this cell');
            }
            requestAnimationFrame(function () {
                ['daily', 'hourly'].forEach(function (key) {
                    if (state.charts[key]) state.charts[key].resize();
                });
            });
        }         catch (e) { /* ignore */ }
    }

    async function loadScorecard() {
        const wrap = document.getElementById('nh-scorecard');
        if (!wrap) return;
        wrap.innerHTML = '<div class="nh-scorecard-empty">Loading categories…</div>';
        try {
            const q = new URLSearchParams({ vendor: vendor, rat: rat, top_n: '5' });
            if (state.area) q.set('area', state.area);
            if (state.cluster != null) q.set('cluster', String(state.cluster));
            const res = await fetch('/api/network-health/summary?' + q.toString(), { credentials: 'same-origin' });
            const data = await res.json();
            if (!data.success) {
                wrap.innerHTML = '<div class="nh-scorecard-empty">Scorecard unavailable</div>';
                return;
            }
            if (data.presets) state.categories = Object.assign(state.categories || {}, data.presets);
            state.scorecard = data.categories || [];
            (state.scorecard || []).forEach(function (c) {
                if (c.kpi) state.kpiCategories[c.kpi] = c.category;
            });
            renderScorecard();
        } catch (e) {
            wrap.innerHTML = '<div class="nh-scorecard-empty">Scorecard failed</div>';
        }
    }

    function renderScorecard() {
        const wrap = document.getElementById('nh-scorecard');
        if (!wrap) return;
        const cards = state.scorecard || [];
        if (!cards.length) return;
        wrap.innerHTML = cards.map(function (c) {
            const active = state.kpi && c.kpi && c.kpi === state.kpi ? ' active' : '';
            const tone = (c.count || 0) > 0 ? ' bad' : ' ok';
            const missing = c.kpi ? '' : ' missing';
            const kpiHint = c.kpi ? c.kpi : 'KPI not in this RAT';
            return '<button type="button" class="nh-score-card' + active + tone + missing +
                '" data-kpi="' + esc(c.kpi || '') + '" data-category="' + esc(c.category) +
                '" title="' + esc(kpiHint) + '">' +
                '<span class="nh-score-name">' + esc(c.tab_label || c.category) + '</span>' +
                '<span class="nh-score-count">' + (c.count || 0) + '</span>' +
                '<span class="nh-score-target">target ' + fmtThreshold(c.threshold_bad) + '</span>' +
                '</button>';
        }).join('');
    }

    async function loadGroups() {
        const box = document.getElementById('nh-groups-list');
        if (!box) return;
        box.textContent = 'Loading…';
        try {
            const q = new URLSearchParams({ vendor: vendor, rat: rat, top_n: '8' });
            const res = await fetch('/api/network-health/groups?' + q.toString(), { credentials: 'same-origin' });
            const data = await res.json();
            if (!data.success) {
                box.textContent = '—';
                return;
            }
            const issues = data.issues || [];
            if (!issues.length) {
                const util = (state.categories && state.categories.Utilization) || {};
                box.innerHTML = '<div class="nh-groups-empty">No group pressure vs ' +
                    fmtThreshold(util.threshold_bad != null ? util.threshold_bad : 80) + '% util</div>';
                return;
            }
            box.innerHTML = issues.map(function (iss) {
                const name = esc(iss.site_id || iss.title || 'Group');
                const val = (iss.evidence && iss.evidence.value != null) ? fmtNum(iss.evidence.value) : fmtNum(iss.score);
                return '<div class="nh-group-row" title="' + esc(iss.summary || '') + '">' +
                    '<span class="nh-group-name">' + name + '</span>' +
                    '<span class="nh-group-val">' + val + '</span></div>';
            }).join('');
        } catch (e) {
            box.textContent = '—';
        }
    }

    function bindEvents() {
        document.getElementById('nh-tabs')?.addEventListener('click', function (ev) {
            const btn = ev.target.closest('.nh-tab');
            if (!btn || !btn.dataset.kpi) return;
            setKpi(btn.dataset.kpi);
        });

        document.getElementById('nh-kpi-select')?.addEventListener('change', function (ev) {
            const kpi = ev.target.value;
            if (kpi) setKpi(kpi);
        });

        document.getElementById('nh-kpi-search')?.addEventListener('input', function (ev) {
            state.kpiFilter = ev.target.value || '';
            renderKpiTabs();
        });

        document.getElementById('nh-cell-search')?.addEventListener('input', function (ev) {
            state.cellFilter = ev.target.value || '';
            refreshTable(false);
        });

        document.getElementById('nh-cell-search')?.addEventListener('keydown', function (ev) {
            if (ev.key !== 'Enter') return;
            ev.preventDefault();
            const rows = sortRows(filterTableRows(state.tableByKpi[state.kpi] || []));
            if (rows.length) {
                selectCell(rows[0].cell_name, { scroll: true });
            }
        });

        document.getElementById('nh-export-btn')?.addEventListener('click', exportTableCsv);

        document.querySelectorAll('.nh-sort-th').forEach(function (btn) {
            btn.addEventListener('click', function () {
                const field = btn.dataset.sort || 'delta';
                if (state.columnSort.field === field) {
                    state.columnSort.dir = state.columnSort.dir === 'asc' ? 'desc' : 'asc';
                } else {
                    state.columnSort.field = field;
                    state.columnSort.dir = field === 'cell_name' ? 'asc' : 'desc';
                }
                if (field === 'delta') {
                    state.sort = state.columnSort.dir === 'asc' ? 'decreased' : 'increased';
                    document.querySelectorAll('.nh-change-btn').forEach(function (b) {
                        b.classList.toggle('active', b.dataset.change === state.sort);
                    });
                } else {
                    document.querySelectorAll('.nh-change-btn').forEach(function (b) {
                        b.classList.remove('active');
                    });
                }
                updateSortHeaderUi();
                refreshTable(false);
            });
        });

        const contextBtn = document.getElementById('nh-context-switch-btn');
        const contextMenu = document.getElementById('nh-context-menu');
        if (contextBtn && contextMenu) {
            contextBtn.addEventListener('click', function (ev) {
                ev.stopPropagation();
                const open = !contextMenu.hidden;
                contextMenu.hidden = open;
                contextBtn.setAttribute('aria-expanded', open ? 'false' : 'true');
            });
            document.addEventListener('click', function () {
                contextMenu.hidden = true;
                contextBtn.setAttribute('aria-expanded', 'false');
            });
            contextMenu.addEventListener('click', function (ev) {
                ev.stopPropagation();
            });
        }

        document.getElementById('nh-area-list')?.addEventListener('click', function (ev) {
            const btn = ev.target.closest('.nh-area-btn');
            if (!btn) return;
            state.area = btn.dataset.area || '';
            state.cluster = null;
            document.querySelectorAll('.nh-area-btn').forEach(function (b) {
                b.classList.toggle('active', b === btn);
            });
            loadClusters().then(function () {
                refreshTable(true);
                loadScorecard();
            });
        });

        document.getElementById('nh-cluster-grid')?.addEventListener('click', function (ev) {
            const btn = ev.target.closest('.nh-cluster-btn');
            if (!btn) return;
            const raw = btn.dataset.cluster;
            state.cluster = raw ? parseInt(raw, 10) : null;
            document.querySelectorAll('.nh-cluster-btn').forEach(function (b) {
                b.classList.toggle('active', b === btn);
            });
            refreshTable(true);
            loadScorecard();
        });

        document.querySelectorAll('.nh-change-btn').forEach(function (btn) {
            btn.addEventListener('click', function () {
                state.sort = btn.dataset.change || 'increased';
                if (state.sort === 'decreased') {
                    state.columnSort = { field: 'delta', dir: 'asc' };
                } else if (state.sort === 'increased') {
                    state.columnSort = { field: 'delta', dir: 'desc' };
                } else if (state.sort === 'breached') {
                    state.columnSort = { field: 'vs_threshold', dir: 'desc' };
                } else {
                    state.columnSort = { field: 'delta', dir: 'desc' };
                }
                document.querySelectorAll('.nh-change-btn').forEach(function (b) {
                    b.classList.toggle('active', b === btn);
                });
                updateSortHeaderUi();
                refreshTable(false);
            });
        });

        document.getElementById('nh-scorecard')?.addEventListener('click', function (ev) {
            const card = ev.target.closest('.nh-score-card');
            if (!card || !card.dataset.kpi) return;
            setKpi(card.dataset.kpi);
            state.sort = 'breached';
            state.columnSort = { field: 'vs_threshold', dir: 'desc' };
            document.querySelectorAll('.nh-change-btn').forEach(function (b) {
                b.classList.toggle('active', b.dataset.change === 'breached');
            });
            updateSortHeaderUi();
            refreshTable(true);
        });

        document.addEventListener('primenet:theme-change', function () {
            if (state.selectedCell) loadCellTrend(state.selectedCell);
        });

        document.getElementById('nh-tbody')?.addEventListener('click', function (ev) {
            const row = ev.target.closest('tr[data-cell]');
            if (!row) return;
            selectCell(cellFromRow(row), { scroll: false });
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        document.getElementById('nh-home-panel')?.remove();
        document.querySelectorAll('.nh-select-lead').forEach(function (el) {
            el.remove();
        });
        bindEvents();
        updateSortHeaderUi();
        loadAreas().then(function () {
            loadClusters().then(function () {
                loadKpis();
                loadScorecard();
                loadGroups();
            });
        });
    });
})();
