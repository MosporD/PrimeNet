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
        cellFilter: '',
        selectedCell: null,
        cells: [],
        tableByKpi: null,
        tableLoading: false,
        kpiLoading: null,
        charts: { daily: null, hourly: null },
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

    function showPrecalcStaleBanner(stale, vendorKey, ratKey) {
        let el = document.getElementById('nh-precalc-stale-banner');
        if (!stale) {
            if (el) el.remove();
            return;
        }
        if (!el) {
            el = document.createElement('div');
            el.id = 'nh-precalc-stale-banner';
            el.className = 'nh-precalc-stale-banner';
            const header = document.querySelector('.nh-header');
            if (header && header.nextSibling) {
                header.parentNode.insertBefore(el, header.nextSibling);
            } else {
                body.insertBefore(el, body.firstChild);
            }
        }
        el.textContent =
            'PM data changed since last precalc — showing cached tables. ' +
            'Rebuild: python scripts/build_network_health_precalc.py --vendor ' +
            vendorKey + ' --rat ' + ratKey;
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
                tbody.innerHTML = '<tr><td colspan="4" class="nh-empty">Loading KPI…</td></tr>';
            }
            await ensureKpiLoaded(kpi);
            refreshTable(true);
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

    function filterTableRows(rows) {
        const q = (state.cellFilter || '').trim().toLowerCase();
        return (rows || []).filter(function (r) {
            if (state.area && String(r.area || '') !== state.area) return false;
            if (state.cluster != null && r.cluster !== state.cluster) return false;
            if (q && String(r.cell_name || '').toLowerCase().indexOf(q) < 0) return false;
            return true;
        });
    }

    function refreshTable(resetSelection) {
        if (!state.kpi) return;
        const tbody = document.getElementById('nh-tbody');
        if (!state.tableByKpi) {
            if (tbody && !state.tableLoading) {
                tbody.innerHTML = '<tr><td colspan="4" class="nh-empty">Loading table…</td></tr>';
            }
            return;
        }
        if (!state.tableByKpi[state.kpi] && state.kpiLoading === state.kpi) {
            if (tbody) tbody.innerHTML = '<tr><td colspan="4" class="nh-empty">Loading KPI…</td></tr>';
            return;
        }
        if (resetSelection) state.selectedCell = null;
        const rows = filterTableRows(state.tableByKpi[state.kpi] || []);
        state.cells = rows;
        renderTable(sortCells(rows, state.sort), { keepSelection: !resetSelection });
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
                if (tbody) tbody.innerHTML = '<tr><td colspan="4" class="nh-empty">' + esc(data.error || 'Failed') + '</td></tr>';
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
                    tbody.innerHTML = '<tr><td colspan="4" class="nh-empty">' + esc(hint) +
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
            showPrecalcStaleBanner(data.precalc_stale, vendor, rat);
            if (loading) loading.hidden = true;
            if (!state.kpi) {
                const pre = data.precomputed_kpis || [];
                state.kpi = pre.length ? pre[0] : (state.kpis[0] || '');
            }
            renderKpiTabs({ skipReload: true });
            if (tbody) tbody.innerHTML = '<tr><td colspan="4" class="nh-empty">Loading KPI…</td></tr>';
            await ensureKpiLoaded(state.kpi);
            refreshTable(true);
        } catch (e) {
            if (tbody) tbody.innerHTML = '<tr><td colspan="4" class="nh-empty">Load failed.</td></tr>';
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
        const rnc = cell.rnc || '';
        const ven = cell.vendor || '';
        box.textContent = rnc ? (rnc + (ven ? '-' + ven : '')) : (ven || '—');
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

    function sortCells(rows, mode) {
        const list = (rows || []).slice();
        const m = (mode || 'increased').toLowerCase();
        if (m === 'decreased') {
            list.sort(function (a, b) {
                const d = Number(a.delta || 0) - Number(b.delta || 0);
                return d !== 0 ? d : String(a.cell_name || '').localeCompare(String(b.cell_name || ''));
            });
        } else if (m === 'no_change') {
            list.sort(function (a, b) {
                const aNc = isNoChangeRow(a) ? 0 : 1;
                const bNc = isNoChangeRow(b) ? 0 : 1;
                if (aNc !== bNc) return aNc - bNc;
                const d = Math.abs(Number(a.delta || 0)) - Math.abs(Number(b.delta || 0));
                return d !== 0 ? d : String(a.cell_name || '').localeCompare(String(b.cell_name || ''));
            });
        } else {
            list.sort(function (a, b) {
                const d = Number(b.delta || 0) - Number(a.delta || 0);
                return d !== 0 ? d : String(a.cell_name || '').localeCompare(String(b.cell_name || ''));
            });
        }
        return list;
    }

    function renderTable(rows, options) {
        const tbody = document.getElementById('nh-tbody');
        const title = document.getElementById('nh-table-title');
        if (!tbody) return;

        if (title) title.textContent = state.kpi || '—';

        if (!rows.length) {
            tbody.innerHTML = '<tr><td colspan="4" class="nh-empty">No cells match filters.</td></tr>';
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
            const deltaCls = Number(r.delta) > 0 ? 'delta-up' : (Number(r.delta) < 0 ? 'delta-down' : '');
            const noChange = isNoChangeRow(r);
            return '<tr data-cell="' + cellDataAttr(r.cell_name) + '" class="' + sel.trim() + (noChange ? ' no-change' : '') + '" title="Click to view trend">' +
                '<td class="cell-name">' + esc(r.cell_name) + '</td>' +
                '<td class="num">' + fmtNum(r.pre != null ? r.pre : r.week_avg) + '</td>' +
                '<td class="num">' + fmtNum(r.post != null ? r.post : r.today_value) + '</td>' +
                '<td class="num ' + deltaCls + '">' + fmtNum(r.delta) + '</td>' +
                '</tr>';
        }).join('');

        if (!(options && options.skipCharts)) {
            selectCell(state.selectedCell, { scroll: false });
        }
    }

    async function loadCells() {
        refreshTable(true);
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

    function buildChart(canvasId, key, labels, avgValues, linearValues, yLabel, seriesLabel) {
        destroyChart(key);
        setChartEmpty(canvasId, canvasId + '-empty', false);
        const canvas = document.getElementById(canvasId);
        if (!canvas || typeof Chart === 'undefined') return;

        const prefix = seriesLabel || (key === 'hourly' ? 'Hourly' : 'Daily');
        const ctx = canvas.getContext('2d');
        state.charts[key] = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: prefix + ' · ' + yLabel,
                        data: avgValues,
                        borderColor: '#7fa6c2',
                        backgroundColor: 'rgba(127, 166, 194, 0.08)',
                        borderWidth: 2,
                        pointRadius: 0,
                        tension: 0.25,
                    },
                    {
                        label: prefix + ' trend',
                        data: linearValues,
                        borderColor: '#6d95b3',
                        backgroundColor: 'transparent',
                        borderWidth: 1.5,
                        borderDash: [4, 3],
                        pointRadius: 0,
                        tension: 0,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: true,
                aspectRatio: 2.2,
                layout: { padding: { top: 4, right: 8, bottom: 0, left: 0 } },
                plugins: {
                    legend: {
                        display: true,
                        labels: { color: '#2c3e50', boxWidth: 14, font: { size: 11 } },
                    },
                },
                scales: {
                    x: {
                        ticks: { color: '#6d95b3', maxTicksLimit: 8, font: { size: 10 } },
                        grid: { color: '#e3edf5' },
                    },
                    y: {
                        ticks: { color: '#6d95b3', font: { size: 10 } },
                        grid: { color: '#e3edf5' },
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
                const step = Math.max(1, Math.ceil(data.hourly.length / 10));
                const labels = data.hourly.map(function (p, i) {
                    if (i % step !== 0) return '';
                    return formatHourlyTick(p.timestamp);
                });
                buildChart(
                    'nh-chart-hourly',
                    'hourly',
                    labels,
                    data.hourly.map(function (p) { return p.value; }),
                    data.hourly.map(function (p) { return p.linear; }),
                    kpiLabel,
                    'Hourly'
                );
            } else {
                destroyChart('hourly');
                setChartEmpty('nh-chart-hourly', 'nh-chart-hourly-empty', true, 'No hourly data for this cell');
            }
        } catch (e) { /* ignore */ }
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
            const rows = sortCells(filterTableRows(state.tableByKpi[state.kpi] || []), state.sort);
            if (rows.length) {
                selectCell(rows[0].cell_name, { scroll: true });
            }
        });

        document.getElementById('nh-area-list')?.addEventListener('click', function (ev) {
            const btn = ev.target.closest('.nh-area-btn');
            if (!btn) return;
            state.area = btn.dataset.area || '';
            state.cluster = null;
            document.querySelectorAll('.nh-area-btn').forEach(function (b) {
                b.classList.toggle('active', b === btn);
            });
            loadClusters().then(function () { refreshTable(true); });
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
        });

        document.querySelectorAll('.nh-change-btn').forEach(function (btn) {
            btn.addEventListener('click', function () {
                state.sort = btn.dataset.change || 'increased';
                document.querySelectorAll('.nh-change-btn').forEach(function (b) {
                    b.classList.toggle('active', b === btn);
                });
                refreshTable(false);
            });
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
        loadAreas().then(function () {
            loadClusters().then(loadKpis);
        });
    });
})();
