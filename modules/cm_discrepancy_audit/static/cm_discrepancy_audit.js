/* CM Discrepancy Audit — workbook-style viewer over stored daily runs. */
(function () {
    'use strict';

    const state = {
        vendor: 'huawei',
        runs: [],
        runDate: '',
        summary: [],
        master: [],
        detail: { mo: '', flag: '', page: 1, pages: 0 },
        trendChart: null,
        pollTimer: null,
    };

    const $ = (id) => document.getElementById(id);

    async function fetchJson(url, options) {
        const res = await fetch(url, options);
        const data = await res.json().catch(() => ({}));
        if (!res.ok || data.success === false) {
            throw new Error(data.error || `Request failed (${res.status})`);
        }
        return data;
    }

    function setStatus(text, isError) {
        const el = $('cda-status');
        el.textContent = text || '';
        el.style.color = isError ? '#a12626' : '';
    }

    function esc(value) {
        const div = document.createElement('div');
        div.textContent = value == null ? '' : String(value);
        return div.innerHTML;
    }

    /* ---------------- runs ---------------- */

    async function loadRuns(keepSelection) {
        const data = await fetchJson(`/api/cm-discrepancy-audit/runs?vendor=${state.vendor}`);
        state.runs = data.items || [];
        const select = $('cda-run');
        const previous = keepSelection ? state.runDate : '';
        select.innerHTML = '';
        if (!state.runs.length) {
            select.innerHTML = '<option value="">No runs yet</option>';
            state.runDate = '';
        } else {
            for (const run of state.runs) {
                const opt = document.createElement('option');
                opt.value = run.run_date;
                opt.textContent = `${run.date_label} — ${run.status}`;
                select.appendChild(opt);
            }
            state.runDate = previous && state.runs.some(r => r.run_date === previous)
                ? previous
                : state.runs[0].run_date;
            select.value = state.runDate;
        }
        renderRunMeta();
        maybePollState(data.state);
    }

    function renderRunMeta() {
        const el = $('cda-run-meta');
        const run = state.runs.find(r => r.run_date === state.runDate);
        if (!run) {
            el.innerHTML = '<span class="cda-chip warn">No stored run for this vendor — trigger one with "Run audit now".</span>';
            return;
        }
        const stats = run.stats || {};
        const chips = [
            `<span class="cda-chip">Status: ${esc(run.status)}</span>`,
            `<span class="cda-chip">MOs: ${esc(stats.mo_count ?? '-')}</span>`,
            `<span class="cda-chip">Objects: ${esc(stats.objects ?? '-')}</span>`,
            `<span class="cda-chip warn">Mismatches: ${esc(stats.total_mismatches ?? '-')}</span>`,
            `<span class="cda-chip">Added: ${esc(stats.added ?? 0)}</span>`,
            `<span class="cda-chip">Removed: ${esc(stats.removed ?? 0)}</span>`,
        ];
        const warnings = stats.warnings || [];
        if (warnings.length) {
            chips.push(`<span class="cda-chip bad" title="${esc(warnings.slice(0, 10).join('\n'))}">Warnings: ${warnings.length}</span>`);
        }
        el.innerHTML = chips.join('');
    }

    /* ---------------- summary ---------------- */

    async function loadSummary() {
        const body = $('cda-summary-table').querySelector('tbody');
        if (!state.runDate) { body.innerHTML = emptyRow(3); return; }
        const data = await fetchJson(
            `/api/cm-discrepancy-audit/runs/${state.runDate}/summary?vendor=${state.vendor}`
        );
        state.summary = data.items || [];
        renderSummary();
    }

    function renderSummary() {
        const term = ($('cda-summary-search').value || '').toLowerCase();
        const rows = state.summary.filter(r =>
            !term || `${r.mo} ${r.parameter}`.toLowerCase().includes(term));
        const body = $('cda-summary-table').querySelector('tbody');
        body.innerHTML = rows.length
            ? rows.map(r => `<tr><td>${esc(r.mo)}</td><td>${esc(r.parameter)}</td><td>${esc(r.mismatch_count)}</td></tr>`).join('')
            : emptyRow(3);
    }

    /* ---------------- master ---------------- */

    async function loadMaster() {
        const body = $('cda-master-table').querySelector('tbody');
        if (!state.runDate) { body.innerHTML = emptyRow(6); return; }
        const data = await fetchJson(
            `/api/cm-discrepancy-audit/runs/${state.runDate}/master?vendor=${state.vendor}`
        );
        state.master = data.items || [];
        renderMaster();
    }

    function renderMaster() {
        const term = ($('cda-master-search').value || '').toLowerCase();
        const rows = state.master.filter(r =>
            !term || `${r.mo} ${r.parameter}`.toLowerCase().includes(term));
        const body = $('cda-master-table').querySelector('tbody');
        body.innerHTML = rows.length
            ? rows.map(r => `
                <tr>
                    <td>${esc(r.mo)}</td>
                    <td>${esc(r.parameter)}</td>
                    <td title="${esc(r.distribution)}">${esc(r.distribution)}</td>
                    <td>${esc(r.common_setting)}</td>
                    <td>${esc(r.unique_count)}</td>
                    <td>${esc(r.mismatch_count)}</td>
                </tr>`).join('')
            : emptyRow(6);
    }

    /* ---------------- trend ---------------- */

    async function loadTrend() {
        const data = await fetchJson(`/api/cm-discrepancy-audit/trend?vendor=${state.vendor}`);
        const items = data.items || [];
        const body = $('cda-trend-table').querySelector('tbody');
        body.innerHTML = items.length
            ? items.slice().reverse().map(r =>
                `<tr><td>${esc(r.run_date)}</td><td>${esc(r.total_mismatches)}</td></tr>`).join('')
            : emptyRow(2);
        if (typeof Chart === 'undefined') return;
        const ctx = $('cda-trend-chart').getContext('2d');
        if (state.trendChart) state.trendChart.destroy();
        state.trendChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: items.map(r => r.run_date),
                datasets: [{
                    label: `Total mismatches (${state.vendor})`,
                    data: items.map(r => r.total_mismatches),
                    borderColor: '#2463eb',
                    backgroundColor: 'rgba(36, 99, 235, 0.12)',
                    fill: true,
                    tension: 0.25,
                }],
            },
            options: {
                responsive: true,
                plugins: { legend: { display: true } },
                scales: { y: { beginAtZero: true } },
            },
        });
    }

    /* ---------------- detail ---------------- */

    async function loadDetail() {
        const table = $('cda-detail-table');
        if (!state.runDate) {
            table.querySelector('thead').innerHTML = '';
            table.querySelector('tbody').innerHTML = emptyRow(1);
            return;
        }
        const params = new URLSearchParams({
            vendor: state.vendor,
            page: String(state.detail.page),
            page_size: '100',
        });
        if (state.detail.mo) params.set('mo', state.detail.mo);
        if (state.detail.flag) params.set('flag', state.detail.flag);
        const data = await fetchJson(
            `/api/cm-discrepancy-audit/runs/${state.runDate}/detail?${params}`
        );
        state.detail.pages = data.pages || 0;
        renderDetailMoOptions(data.mos || []);
        renderDetail(data.items || []);
        $('cda-detail-page').textContent = data.total
            ? `page ${data.page}/${data.pages} — ${data.total} object(s)`
            : 'no flagged objects';
    }

    function renderDetailMoOptions(mos) {
        const select = $('cda-detail-mo');
        const current = state.detail.mo;
        select.innerHTML = '<option value="">All MOs</option>' + mos.map(m =>
            `<option value="${esc(m.mo)}">${esc(m.mo)} (${esc(m.total)})</option>`).join('');
        if (current && mos.some(m => m.mo === current)) select.value = current;
    }

    function renderDetail(items) {
        const table = $('cda-detail-table');
        const thead = table.querySelector('thead');
        const tbody = table.querySelector('tbody');
        if (!items.length) {
            thead.innerHTML = '';
            tbody.innerHTML = emptyRow(1);
            return;
        }
        thead.innerHTML = '<tr><th>MO</th><th>Object</th><th>NE</th><th>Mismatched Parameters</th><th>Flag</th><th>Date</th></tr>';
        tbody.innerHTML = items.map(item => {
            const mismatches = (item.mismatches || []).map(m =>
                `${m.parameter}=${m.value} (common ${m.common})`).join('; ');
            return `<tr>
                <td>${esc(item.mo)}</td>
                <td title="${esc(item.object_key)}">${esc(item.object_key)}</td>
                <td>${esc(item.ne_name)}</td>
                <td title="${esc(mismatches)}">${esc(mismatches)}</td>
                <td><span class="cda-flag ${esc(item.flag)}">${esc(item.flag)}</span></td>
                <td>${esc(item.detected_date)}</td>
            </tr>`;
        }).join('');
    }

    /* ---------------- trigger + polling ---------------- */

    async function triggerRun() {
        if (!window.confirm(`Start a full-network ${state.vendor} discrepancy audit now? This pulls CM for every NE and may take a while.`)) {
            return;
        }
        try {
            await fetchJson('/api/cm-discrepancy-audit/run', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ vendor: state.vendor }),
            });
            setStatus('Audit started — progress refreshes automatically.');
            maybePollState({ running: true });
        } catch (err) {
            setStatus(err.message, true);
        }
    }

    function maybePollState(runState) {
        if (runState && runState.running) {
            setStatus(`Running: ${runState.message || 'audit in progress'}`);
            if (!state.pollTimer) {
                state.pollTimer = setInterval(pollState, 5000);
            }
        }
    }

    async function pollState() {
        try {
            const data = await fetchJson('/api/cm-discrepancy-audit/status');
            const runState = data.state || {};
            if (runState.running) {
                setStatus(`Running: ${runState.message || 'audit in progress'}`);
            } else {
                clearInterval(state.pollTimer);
                state.pollTimer = null;
                setStatus('Audit finished — refreshing runs.');
                await refreshAll(true);
            }
        } catch (err) {
            clearInterval(state.pollTimer);
            state.pollTimer = null;
            setStatus(err.message, true);
        }
    }

    /* ---------------- helpers + wiring ---------------- */

    function emptyRow(cols) {
        return `<tr><td colspan="${cols}"><div class="cda-empty">No data</div></td></tr>`;
    }

    function activeTab() {
        const btn = document.querySelector('.cda-tab.active');
        return btn ? btn.dataset.tab : 'summary';
    }

    async function loadActiveTab() {
        const tab = activeTab();
        try {
            if (tab === 'summary') await loadSummary();
            else if (tab === 'master') await loadMaster();
            else if (tab === 'trend') await loadTrend();
            else if (tab === 'detail') await loadDetail();
        } catch (err) {
            setStatus(err.message, true);
        }
    }

    async function refreshAll(keepSelection) {
        try {
            await loadRuns(keepSelection);
            renderRunMeta();
            await loadActiveTab();
        } catch (err) {
            setStatus(err.message, true);
        }
    }

    document.addEventListener('DOMContentLoaded', () => {
        $('cda-vendor').addEventListener('change', async (event) => {
            state.vendor = event.target.value;
            state.detail = { mo: '', flag: '', page: 1, pages: 0 };
            await refreshAll(false);
        });
        $('cda-run').addEventListener('change', async (event) => {
            state.runDate = event.target.value;
            state.detail.page = 1;
            renderRunMeta();
            await loadActiveTab();
        });
        document.querySelectorAll('.cda-tab').forEach((btn) => {
            btn.addEventListener('click', async () => {
                document.querySelectorAll('.cda-tab').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                document.querySelectorAll('.cda-panel').forEach(p => { p.hidden = true; });
                $(`cda-panel-${btn.dataset.tab}`).hidden = false;
                await loadActiveTab();
            });
        });
        $('cda-summary-search').addEventListener('input', renderSummary);
        $('cda-master-search').addEventListener('input', renderMaster);
        $('cda-detail-mo').addEventListener('change', async (event) => {
            state.detail.mo = event.target.value;
            state.detail.page = 1;
            await loadDetail();
        });
        $('cda-detail-flag').addEventListener('change', async (event) => {
            state.detail.flag = event.target.value;
            state.detail.page = 1;
            await loadDetail();
        });
        $('cda-detail-prev').addEventListener('click', async () => {
            if (state.detail.page > 1) { state.detail.page -= 1; await loadDetail(); }
        });
        $('cda-detail-next').addEventListener('click', async () => {
            if (state.detail.page < state.detail.pages) { state.detail.page += 1; await loadDetail(); }
        });
        $('cda-download-btn').addEventListener('click', () => {
            if (!state.runDate) { setStatus('No run selected.', true); return; }
            window.location.href =
                `/api/cm-discrepancy-audit/runs/${state.runDate}/download?vendor=${state.vendor}`;
        });
        $('cda-trigger-btn').addEventListener('click', triggerRun);

        refreshAll(false);
    });
})();
