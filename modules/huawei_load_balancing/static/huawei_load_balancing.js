(function () {
    'use strict';

    let previewToken = null;
    let loadedSectors = [];

    const cmStatus = document.getElementById('cm-status');
    const balanceStatus = document.getElementById('balance-status');
    const balanceDate = document.getElementById('balance-date');
    const reloadBtn = document.getElementById('reload-sectors-btn');
    const syncBalanceBtn = document.getElementById('sync-balance-btn');
    const loadStatus = document.getElementById('load-status');
    const sourceFile = document.getElementById('source-file');
    const sectorList = document.getElementById('sector-list');
    const sectorTableBody = document.getElementById('sector-table-body');
    const sectorCheckAll = document.getElementById('sector-check-all');
    const sectorFilter = document.getElementById('sector-filter');
    const sectorCount = document.getElementById('sector-count');
    const manualSectors = document.getElementById('manual-sectors');
    const analyzeBtn = document.getElementById('analyze-btn');
    const analyzeStatus = document.getElementById('analyze-status');
    const resultsPanel = document.getElementById('results-panel');
    const resultsBody = document.querySelector('#results-table tbody');
    const warningsBox = document.getElementById('warnings-box');
    const downloadExcelBtn = document.getElementById('download-excel-btn');
    const downloadMmlBtn = document.getElementById('download-mml-btn');
    const selectVisibleBtn = document.getElementById('select-visible-btn');
    const clearAllBtn = document.getElementById('clear-all-btn');

    function todayIso() {
        return new Date().toISOString().slice(0, 10);
    }

    function escapeHtml(value) {
        return String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function setPill(el, text, state) {
        el.textContent = text;
        el.className = 'connection-pill' + (state ? ' ' + state : '');
    }

    function formatTp(value) {
        const num = Number(value);
        if (!Number.isFinite(num)) return '—';
        return num.toFixed(1);
    }

    function visibleSectorRows() {
        return Array.from(sectorTableBody.querySelectorAll('tr:not(.hidden-by-filter)'));
    }

    function selectedSectorIds() {
        const fromChecks = Array.from(sectorTableBody.querySelectorAll('input.sector-check:checked')).map((el) => el.value);
        const manual = (manualSectors.value || '').split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
        return [...new Set([...fromChecks, ...manual])];
    }

    function updateAnalyzeButton() {
        const balOk = document.body.dataset.balanceConfigured === 'true';
        analyzeBtn.disabled = !balOk || selectedSectorIds().length === 0;
        selectVisibleBtn.disabled = loadedSectors.length === 0;
        clearAllBtn.disabled = loadedSectors.length === 0;
    }

    function updateSectorMeta() {
        const query = (sectorFilter.value || '').trim().toLowerCase();
        const visible = visibleSectorRows().length;
        const selected = sectorTableBody.querySelectorAll('input.sector-check:checked').length;
        sectorCount.textContent = query
            ? `${visible} of ${loadedSectors.length} shown · ${selected} selected`
            : `${loadedSectors.length} NOK sector(s) · ${selected} selected`;
        updateAnalyzeButton();
    }

    function renderSectorList(sectors) {
        sectorTableBody.innerHTML = '';
        loadedSectors = sectors || [];
        if (!loadedSectors.length) {
            sectorList.hidden = true;
            updateSectorMeta();
            return;
        }
        sectorList.hidden = false;
        loadedSectors.forEach((sector) => {
            const tp = sector.throughput || {};
            const tr = document.createElement('tr');
            tr.dataset.search = `${sector.sector_id} ${sector.highest_layer || ''} ${sector.lowest_layer || ''}`;
            tr.innerHTML = `
                <td class="col-check"><input type="checkbox" class="sector-check" value="${escapeHtml(sector.sector_id)}"></td>
                <td>${escapeHtml(sector.sector_id)}</td>
                <td>${escapeHtml(sector.highest_layer || '—')}</td>
                <td>${escapeHtml(sector.lowest_layer || '—')}</td>
                <td>${formatTp(tp.L18)}</td>
                <td>${formatTp(tp.L21)}</td>
                <td>${formatTp(tp.L9)}</td>
                <td>${formatTp(tp['L18+'])}</td>
            `;
            sectorTableBody.appendChild(tr);
        });
        sectorTableBody.querySelectorAll('.sector-check').forEach((cb) => {
            cb.addEventListener('change', updateSectorMeta);
        });
        updateSectorMeta();
    }

    async function loadSectors() {
        loadStatus.textContent = 'Loading Huawei NOK sectors…';
        const date = balanceDate.value ? `?date=${encodeURIComponent(balanceDate.value)}` : '';
        try {
            const resp = await fetch(`/api/huawei-load-balancing/nok-sectors${date}`);
            const data = await resp.json();
            if (!resp.ok || !data.success) {
                loadStatus.textContent = (data.errors && data.errors[0]) || data.error || 'Failed to load sectors';
                renderSectorList([]);
                return;
            }
            renderSectorList(data.sectors || []);
            sourceFile.textContent = data.source_file || data.source_date
                ? `Source: ${data.source_file || data.source_date} (${data.data_source || data.source || ''})`
                : '';
            loadStatus.textContent = `${(data.sectors || []).length} NOK sector(s)`;
        } catch (err) {
            loadStatus.textContent = err.message || String(err);
        }
    }

    async function syncBalance() {
        loadStatus.textContent = 'Syncing Huawei Network Balance CSV…';
        try {
            const resp = await fetch('/api/huawei-load-balancing/ingest', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ force: false }),
            });
            const data = await resp.json();
            loadStatus.textContent = data.success ? 'Huawei ingest finished' : (data.error || 'Ingest failed');
            await loadSectors();
        } catch (err) {
            loadStatus.textContent = err.message || String(err);
        }
    }

    async function analyze() {
        const sectors = selectedSectorIds();
        analyzeBtn.disabled = true;
        analyzeStatus.textContent = 'Computing CellMLB proposals…';
        try {
            const resp = await fetch('/api/huawei-load-balancing/analyze', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ sectors, date: balanceDate.value }),
            });
            const data = await resp.json();
            if (!resp.ok || !data.success) {
                analyzeStatus.textContent = (data.errors && data.errors[0]) || data.error || 'Analyze failed';
                return;
            }
            previewToken = data.token;
            resultsBody.innerHTML = (data.rows || []).map((row) => `
                <tr>
                    <td>${escapeHtml(row.sector_id)}</td>
                    <td>${escapeHtml(row.source)}</td>
                    <td>${escapeHtml(row.target)}</td>
                    <td>${escapeHtml(row.action)}</td>
                    <td>${escapeHtml(row.parameter)}</td>
                    <td>${escapeHtml(row.current)}</td>
                    <td>${escapeHtml(row.proposed)}</td>
                    <td>${escapeHtml(row.delta)}</td>
                    <td title="${escapeHtml((row.ml_treatment && row.ml_treatment.note) || '')}">${escapeHtml(row.ml_treatment && row.ml_treatment.predicted_util_delta != null ? row.ml_treatment.predicted_util_delta : '—')}</td>
                    <td>${escapeHtml(row.ml_treatment && row.ml_treatment.predicted_mobility_delta != null ? row.ml_treatment.predicted_mobility_delta : '—')}</td>
                </tr>
            `).join('');
            const warnings = data.warnings || [];
            warningsBox.hidden = !warnings.length;
            warningsBox.innerHTML = warnings.map((w) => `<p>${escapeHtml(w)}</p>`).join('');
            resultsPanel.hidden = false;
            downloadExcelBtn.disabled = !((data.review_row_count || 0) > 0);
            downloadMmlBtn.disabled = !((data.change_count || 0) > 0);
            analyzeStatus.textContent = `${data.change_count || 0} CellMLB change(s) · ${data.sector_count || 0} sector(s)`;
        } catch (err) {
            analyzeStatus.textContent = err.message || String(err);
        } finally {
            updateAnalyzeButton();
        }
    }

    async function downloadFile(endpoint, filename) {
        if (!previewToken) return;
        const resp = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ token: previewToken }),
        });
        if (!resp.ok) {
            const data = await resp.json().catch(() => ({}));
            alert(data.error || 'Download failed');
            return;
        }
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        a.click();
        URL.revokeObjectURL(url);
    }

    setPill(
        cmStatus,
        document.body.dataset.huaweiConfigured === 'true' ? 'U2020 CM configured (export only)' : 'U2020 CM not required for proposals',
        document.body.dataset.huaweiConfigured === 'true' ? 'ok' : 'muted'
    );
    setPill(
        balanceStatus,
        document.body.dataset.balanceConfigured === 'true' ? 'Network Balance reachable' : 'Network Balance unreachable',
        document.body.dataset.balanceConfigured === 'true' ? 'ok' : 'error'
    );

    sectorFilter.addEventListener('input', () => {
        const query = (sectorFilter.value || '').trim().toLowerCase();
        sectorTableBody.querySelectorAll('tr').forEach((row) => {
            row.classList.toggle('hidden-by-filter', !!(query && !(row.dataset.search || '').toLowerCase().includes(query)));
        });
        updateSectorMeta();
    });
    sectorCheckAll.addEventListener('change', () => {
        visibleSectorRows().forEach((row) => {
            const cb = row.querySelector('.sector-check');
            if (cb) cb.checked = sectorCheckAll.checked;
        });
        updateSectorMeta();
    });
    selectVisibleBtn.addEventListener('click', () => {
        visibleSectorRows().forEach((row) => {
            const cb = row.querySelector('.sector-check');
            if (cb) cb.checked = true;
        });
        updateSectorMeta();
    });
    clearAllBtn.addEventListener('click', () => {
        sectorTableBody.querySelectorAll('.sector-check').forEach((el) => { el.checked = false; });
        updateSectorMeta();
    });
    reloadBtn.addEventListener('click', loadSectors);
    syncBalanceBtn.addEventListener('click', syncBalance);
    manualSectors.addEventListener('input', updateAnalyzeButton);
    analyzeBtn.addEventListener('click', analyze);
    downloadExcelBtn.addEventListener('click', () =>
        downloadFile('/api/huawei-load-balancing/download-excel', `huawei_lb_${previewToken.slice(0, 8)}.xlsx`)
    );
    downloadMmlBtn.addEventListener('click', () =>
        downloadFile('/api/huawei-load-balancing/download-mml', `huawei_lb_${previewToken.slice(0, 8)}.txt`)
    );

    balanceDate.value = todayIso();
    updateAnalyzeButton();
    if (document.body.dataset.balanceConfigured === 'true') {
        loadSectors();
    }
})();
