(function () {
    'use strict';

    let previewToken = null;
    let loadedSectors = [];

    const cmStatus = document.getElementById('cm-status');
    const balanceStatus = document.getElementById('balance-status');
    const dbStatus = document.getElementById('db-status');
    const balanceDate = document.getElementById('balance-date');
    const reloadBtn = document.getElementById('reload-sectors-btn');
    const syncBalanceBtn = document.getElementById('sync-balance-btn');
    const refreshDbBtn = document.getElementById('refresh-db-btn');
    const ingestStart = document.getElementById('ingest-start');
    const ingestEnd = document.getElementById('ingest-end');
    const ingestForce = document.getElementById('ingest-force');
    const dbPath = document.getElementById('db-path');
    const dbInventory = document.getElementById('db-inventory');
    const snapshotTableBody = document.getElementById('snapshot-table-body');
    const trendStart = document.getElementById('trend-start');
    const trendEnd = document.getElementById('trend-end');
    const trendVendor = document.getElementById('trend-vendor');
    const trendStatus = document.getElementById('trend-status');
    const loadTrendBtn = document.getElementById('load-trend-btn');
    const trendStatusText = document.getElementById('trend-status-text');
    const dailySummaryBody = document.getElementById('daily-summary-body');
    const sectorTrendHead = document.getElementById('sector-trend-head');
    const sectorTrendBody = document.getElementById('sector-trend-body');
    const selectVisibleBtn = document.getElementById('select-visible-btn');
    const clearAllBtn = document.getElementById('clear-all-btn');
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
    const downloadXmlBtn = document.getElementById('download-xml-btn');
    const downloadBackupXmlBtn = document.getElementById('download-backup-xml-btn');
    const downloadExcelBtn = document.getElementById('download-excel-btn');
    const applyOssBtn = document.getElementById('apply-oss-btn');
    const applyConfirmation = document.body.dataset.applyConfirmation || '';
    const ossPushConfigured = document.body.dataset.ossPushConfigured === 'true';

    function todayIso() {
        return new Date().toISOString().slice(0, 10);
    }

    function daysAgoIso(days) {
        const d = new Date();
        d.setDate(d.getDate() - days);
        return d.toISOString().slice(0, 10);
    }

    function statusBadge(status) {
        if (!status) return '<span class="status-badge missing">—</span>';
        const token = String(status).toUpperCase();
        const cls = token === 'NOK' ? 'nok' : token === 'OK' ? 'ok' : 'other';
        return `<span class="status-badge ${cls}">${escapeHtml(token)}</span>`;
    }

    function renderSnapshotTable(snapshots) {
        snapshotTableBody.innerHTML = '';
        if (!snapshots || !snapshots.length) {
            snapshotTableBody.innerHTML = '<tr><td colspan="5">No snapshots in range — run Sync to database.</td></tr>';
            return;
        }
        snapshots.forEach((snap) => {
            const tr = document.createElement('tr');
            const source = snap.source_file || '';
            const sourceName = source.split(/[/\\]/).pop() || source;
            tr.innerHTML = `
                <td>${escapeHtml(snap.snapshot_date)}</td>
                <td>${escapeHtml(snap.vendor)}</td>
                <td>${escapeHtml(snap.row_count ?? '—')}</td>
                <td>${escapeHtml((snap.ingested_at || '').replace('T', ' '))}</td>
                <td class="source-file-cell" title="${escapeAttr(source)}">${escapeHtml(sourceName)}</td>
            `;
            snapshotTableBody.appendChild(tr);
        });
    }

    function renderDailySummary(rows) {
        dailySummaryBody.innerHTML = '';
        if (!rows || !rows.length) {
            dailySummaryBody.innerHTML = '<tr><td colspan="6">No daily summary for this range.</td></tr>';
            return;
        }
        rows.forEach((row) => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>${escapeHtml(row.snapshot_date)}</td>
                <td>${escapeHtml(row.vendor)}</td>
                <td>${escapeHtml(row.total)}</td>
                <td>${escapeHtml(row.nok)}</td>
                <td>${escapeHtml(row.ok)}</td>
                <td>${escapeHtml(row.other)}</td>
            `;
            dailySummaryBody.appendChild(tr);
        });
    }

    function renderSectorTrend(trend) {
        sectorTrendHead.innerHTML = '';
        sectorTrendBody.innerHTML = '';
        const dates = (trend && trend.dates) || [];
        const sectors = (trend && trend.sectors) || [];
        if (!dates.length || !sectors.length) {
            sectorTrendBody.innerHTML = '<tr><td>No sector trend data for this range.</td></tr>';
            return;
        }

        const headRow = document.createElement('tr');
        headRow.innerHTML = '<th>Sector</th>' + dates.map((d) => `<th>${escapeHtml(d.slice(5))}</th>`).join('');
        sectorTrendHead.appendChild(headRow);

        sectors.forEach((sector) => {
            const tr = document.createElement('tr');
            const cells = (sector.history || []).map((entry) => `<td>${statusBadge(entry.balancing_status)}</td>`).join('');
            tr.innerHTML = `<td class="sector-id-cell">${escapeHtml(sector.sector_id)}</td>${cells}`;
            sectorTrendBody.appendChild(tr);
        });
    }

    async function loadSnapshots() {
        const start = ingestStart.value || daysAgoIso(13);
        const end = ingestEnd.value || todayIso();
        try {
            const resp = await fetch(
                `/api/nokia-load-balancing/snapshots?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`
            );
            const data = await resp.json();
            if (!resp.ok || !data.success) return;
            renderSnapshotTable(data.snapshots || []);
        } catch (_err) {
            /* inventory still useful */
        }
    }

    function setPill(el, text, state) {
        el.textContent = text;
        el.className = 'connection-pill' + (state ? ' ' + state : '');
    }

    function setStatuses() {
        const cmOk = document.body.dataset.nokiaConfigured === 'true';
        setPill(cmStatus, cmOk ? 'Nokia CM configured' : 'Nokia CM not configured', cmOk ? 'ok' : 'error');

        const balOk = document.body.dataset.balanceConfigured === 'true';
        setPill(
            balanceStatus,
            balOk ? 'Network Balance reachable' : 'Network Balance unreachable',
            balOk ? 'ok' : 'error'
        );

        updateAnalyzeButton();
    }

    function visibleSectorRows() {
        return Array.from(sectorTableBody.querySelectorAll('tr:not(.hidden-by-filter)'));
    }

    function formatTp(value) {
        if (value === null || value === undefined || value === '') return '—';
        const num = Number(value);
        if (Number.isNaN(num)) return '—';
        return num.toFixed(1);
    }

    function updateSectorMeta() {
        const query = (sectorFilter.value || '').trim().toLowerCase();
        const visible = visibleSectorRows().length;
        const selected = sectorTableBody.querySelectorAll('input.sector-check:checked').length;
        sectorCount.textContent = query
            ? `${visible} of ${loadedSectors.length} shown · ${selected} selected`
            : `${loadedSectors.length} NOK sector(s) · ${selected} selected`;
    }

    function applySectorFilter() {
        const query = (sectorFilter.value || '').trim().toLowerCase();
        sectorTableBody.querySelectorAll('tr').forEach((row) => {
            const text = (row.dataset.search || '').toLowerCase();
            row.classList.toggle('hidden-by-filter', !!(query && !text.includes(query)));
        });
        updateSectorMeta();
        updateRowSelectionStyles();
    }

    function updateRowSelectionStyles() {
        sectorTableBody.querySelectorAll('tr').forEach((row) => {
            const cb = row.querySelector('.sector-check');
            row.classList.toggle('row-selected', !!(cb && cb.checked));
        });
    }

    function selectedSectorIds() {
        const fromChecks = Array.from(
            sectorTableBody.querySelectorAll('input.sector-check:checked')
        ).map((el) => el.value);

        const manual = manualSectors.value
            .split(/\r?\n/)
            .map((s) => s.trim())
            .filter(Boolean);

        return [...new Set([...fromChecks, ...manual])];
    }

    function updateAnalyzeButton() {
        const cmOk = document.body.dataset.nokiaConfigured === 'true';
        const balOk = document.body.dataset.balanceConfigured === 'true';
        const hasSectors = selectedSectorIds().length > 0;
        analyzeBtn.disabled = !cmOk || !balOk || !hasSectors;
        selectVisibleBtn.disabled = loadedSectors.length === 0;
        clearAllBtn.disabled = loadedSectors.length === 0;
    }

    function renderSectorList(sectors) {
        sectorTableBody.innerHTML = '';
        loadedSectors = sectors || [];
        sectorFilter.value = '';
        sectorCheckAll.checked = false;

        if (!loadedSectors.length) {
            sectorList.hidden = true;
            updateSectorMeta();
            updateAnalyzeButton();
            return;
        }

        loadedSectors.forEach((sec) => {
            const tr = document.createElement('tr');
            const tp = sec.throughput || {};
            const search = [
                sec.sector_id,
                sec.highest_layer,
                sec.lowest_layer,
            ].join(' ').toLowerCase();
            tr.dataset.search = search;

            tr.innerHTML = `
                <td class="col-check"><input type="checkbox" class="sector-check" value="${escapeAttr(sec.sector_id)}"></td>
                <td class="sector-id-cell">${escapeHtml(sec.sector_id)}</td>
                <td class="layer-high">${escapeHtml(sec.highest_layer || '—')}</td>
                <td class="layer-low">${escapeHtml(sec.lowest_layer || '—')}</td>
                <td class="tp-cell">${escapeHtml(formatTp(tp.L18))}</td>
                <td class="tp-cell">${escapeHtml(formatTp(tp.L21))}</td>
                <td class="tp-cell">${escapeHtml(formatTp(tp.L9))}</td>
                <td class="tp-cell">${escapeHtml(formatTp(tp['L18+']))}</td>
            `;

            const cb = tr.querySelector('.sector-check');
            cb.addEventListener('change', () => {
                updateRowSelectionStyles();
                updateSectorMeta();
                updateAnalyzeButton();
            });
            tr.addEventListener('click', (e) => {
                if (e.target.tagName === 'INPUT') return;
                cb.checked = !cb.checked;
                cb.dispatchEvent(new Event('change'));
            });

            sectorTableBody.appendChild(tr);
        });

        sectorList.hidden = false;
        applySectorFilter();
        updateAnalyzeButton();
    }

    function escapeHtml(value) {
        return String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    }

    function escapeAttr(value) {
        return escapeHtml(value).replace(/"/g, '&quot;');
    }

    function showWarnings(warnings) {
        if (!warnings || !warnings.length) {
            warningsBox.hidden = true;
            warningsBox.innerHTML = '';
            return;
        }
        const hasSummary = warnings[0] && String(warnings[0]).startsWith('Summary:');
        const summaryText = hasSummary ? warnings[0] : `${warnings.length} notice(s)`;
        const detailItems = hasSummary ? warnings.slice(1) : warnings;
        warningsBox.hidden = false;
        warningsBox.innerHTML = `
            <details class="warnings-details">
                <summary>${escapeHtml(summaryText)}</summary>
                ${detailItems.length ? `<ul class="warnings-list">${detailItems.map((w) => `<li>${escapeHtml(w)}</li>`).join('')}</ul>` : ''}
            </details>`;
    }

    function renderResults(rows) {
        resultsBody.innerHTML = '';
        rows.forEach((row) => {
            Object.entries(row.parameters || {}).forEach(([param, vals]) => {
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td>${escapeHtml(row.sector_id)}</td>
                    <td>${escapeHtml(row.source_layer)}</td>
                    <td>${escapeHtml(row.target_layer)}</td>
                    <td>${escapeHtml(row.action)}</td>
                    <td>${escapeHtml(param)}</td>
                    <td>${escapeHtml(vals.current)}</td>
                    <td>${escapeHtml(vals.proposed)}</td>
                    <td>${escapeHtml(vals.delta)}</td>
                `;
                resultsBody.appendChild(tr);
            });
        });
    }

    async function loadDbStatus() {
        try {
            const resp = await fetch('/api/nokia-load-balancing/ingest-status');
            const data = await resp.json();
            if (!resp.ok || !data.success) {
                setPill(dbStatus, 'Database unavailable', 'warn');
                return;
            }

            if (data.db_path) {
                dbPath.textContent = `Database: ${data.db_path}`;
            }

            const inventory = data.inventory || [];
            if (inventory.length) {
                dbInventory.textContent = inventory
                    .map((v) => `${v.vendor}: ${v.snapshot_count} day(s), ${v.first_date} → ${v.last_date}, ${v.total_rows} rows`)
                    .join(' · ');
            } else {
                dbInventory.textContent = 'Database empty — sync Nokia and Huawei CSVs for your date range.';
            }

            const smb = data.smb || {};
            if (smb.enabled) {
                const smbOk = Boolean(smb.mounted || data.db_has_data);
                const hostLabel = smb.host ? `${smb.host}/${smb.share || 'share'}` : 'SMB share';
                setPill(
                    balanceStatus,
                    smbOk ? `${hostLabel} mounted` : `SMB not mounted (${hostLabel})`,
                    smbOk ? 'ok' : 'error'
                );
            }

            const parts = [];
            if (data.nokia_in_db) parts.push('Nokia');
            if (data.huawei_in_db) parts.push('Huawei');
            const recent = (data.recent_snapshots || [])[0];
            if (recent) {
                parts.push(`latest ${recent.snapshot_date}`);
            }
            setPill(
                dbStatus,
                parts.length ? 'DB: ' + parts.join(' · ') : 'DB empty — sync recommended',
                parts.length ? 'ok' : 'warn'
            );

            document.body.dataset.balanceConfigured = 'true';
            setStatuses();
            renderSnapshotTable(data.recent_snapshots || []);
        } catch (_err) {
            setPill(dbStatus, 'Database status unknown', 'muted');
        }
    }

    async function syncBalance() {
        syncBalanceBtn.disabled = true;
        const start = ingestStart.value;
        const end = ingestEnd.value;
        const rangeLabel = start && end ? `${start} → ${end}` : 'default lookback';
        loadStatus.textContent = `Syncing Nokia + Huawei balance files (${rangeLabel})…`;
        loadStatus.classList.remove('error');
        try {
            const resp = await fetch('/api/nokia-load-balancing/ingest', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    start_date: start || undefined,
                    end_date: end || undefined,
                    force: ingestForce.checked,
                }),
            });
            const data = await resp.json();
            const ingested = (data.ingested || []).length;
            const skipped = (data.skipped || []).length;
            const errors = (data.errors || []).length;
            loadStatus.textContent = `Sync complete — ${ingested} ingested, ${skipped} skipped, ${errors} errors (${data.start_date} → ${data.end_date})`;
            if (errors) {
                loadStatus.classList.add('error');
                showWarnings((data.errors || []).map((e) => `${e.file || 'file'}: ${e.error}`));
            }
            await loadDbStatus();
            await loadSnapshots();
            await loadSectors();
        } catch (err) {
            loadStatus.textContent = 'Sync failed: ' + err.message;
            loadStatus.classList.add('error');
        } finally {
            syncBalanceBtn.disabled = false;
        }
    }

    async function loadTrend() {
        const start = trendStart.value;
        const end = trendEnd.value;
        if (!start || !end) {
            trendStatusText.textContent = 'Select start and end dates for the trend.';
            trendStatusText.classList.add('error');
            return;
        }
        loadTrendBtn.disabled = true;
        trendStatusText.textContent = 'Loading trend…';
        trendStatusText.classList.remove('error');
        try {
            const params = new URLSearchParams({
                start,
                end,
                vendor: trendVendor.value,
                status: trendStatus.value,
            });
            const resp = await fetch(`/api/nokia-load-balancing/trend?${params.toString()}`);
            const data = await resp.json();
            if (!resp.ok || !data.success) {
                trendStatusText.textContent = data.error || 'Could not load trend.';
                trendStatusText.classList.add('error');
                return;
            }
            renderDailySummary(data.daily_summary || []);
            renderSectorTrend(data.trend || {});
            const sectorCount = ((data.trend || {}).sectors || []).length;
            trendStatusText.textContent =
                `Trend ${data.start_date} → ${data.end_date} · ${sectorCount} sector(s) · ${data.vendor}`;
        } catch (err) {
            trendStatusText.textContent = 'Trend load failed: ' + err.message;
            trendStatusText.classList.add('error');
        } finally {
            loadTrendBtn.disabled = false;
        }
    }

    async function loadSectors() {
        loadStatus.textContent = 'Loading NOK sectors…';
        loadStatus.classList.remove('error');
        sourceFile.textContent = '';
        const date = balanceDate.value || todayIso();
        try {
            const resp = await fetch(`/api/nokia-load-balancing/nok-sectors?date=${encodeURIComponent(date)}`);
            const data = await resp.json();
            if (!resp.ok || !data.success) {
                loadStatus.textContent = (data.errors || ['Could not load sectors']).join('; ');
                loadStatus.classList.add('error');
                renderSectorList([]);
                return;
            }
            renderSectorList(data.sectors || []);
            loadStatus.textContent = `Loaded ${(data.sectors || []).length} NOK sector(s) from ${data.data_source || 'source'}`;
            if (data.source_file) {
                sourceFile.textContent = `Source file: ${data.source_file}`;
            } else if (data.data_source === 'sqlite' && data.source_date) {
                sourceFile.textContent = `Source: SQLite snapshot ${data.source_date}`;
            }
            if (data.warnings && data.warnings.length) {
                showWarnings(data.warnings);
            }
        } catch (err) {
            loadStatus.textContent = 'Load failed: ' + err.message;
            loadStatus.classList.add('error');
        }
    }

    async function analyze() {
        const sectors = selectedSectorIds();
        if (!sectors.length) {
            analyzeStatus.textContent = 'Select or enter at least one sector.';
            analyzeStatus.classList.add('error');
            return;
        }

        analyzeBtn.disabled = true;
        const siteHint = sectors.length > 5
            ? ` (${sectors.length} sectors — parallel NetAct CM queries for selected sites)`
            : '';
        analyzeStatus.textContent = `Reading throughput and fetching AMLE from NetAct…${siteHint}`;
        analyzeStatus.classList.remove('error');
        previewToken = null;
        downloadXmlBtn.disabled = true;
        downloadBackupXmlBtn.disabled = true;
        downloadExcelBtn.disabled = true;
        if (applyOssBtn) applyOssBtn.disabled = true;

        try {
            const resp = await fetch('/api/nokia-load-balancing/analyze', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    sectors,
                    date: balanceDate.value || todayIso(),
                }),
            });
            const data = await resp.json();
            if (!resp.ok || !data.success) {
                analyzeStatus.textContent = (data.errors || [data.error || 'Analysis failed']).join('; ');
                analyzeStatus.classList.add('error');
                showWarnings(data.warnings || []);
                return;
            }

            previewToken = data.token;
            renderResults(data.rows || []);
            showWarnings(data.warnings || []);
            resultsPanel.hidden = false;
            resultsPanel.scrollIntoView({ behavior: 'smooth', block: 'start' });
            const summary = data.summary || {};
            analyzeStatus.textContent =
                `${summary.hl_rows_proposed ?? 0} AMLEPR row(s) ready · ` +
                `${summary.sectors_with_proposals ?? 0}/${summary.sectors_requested ?? data.sector_count ?? 0} sector(s) · ` +
                `${summary.hl_rows_skipped_clamped ?? 0} row(s) at 0/100 limits`;
            if (data.source_file) {
                sourceFile.textContent = `Throughput source: ${data.source_file}`;
            }
            downloadXmlBtn.disabled = !(data.change_count > 0);
            downloadBackupXmlBtn.disabled = !(data.change_count > 0);
            downloadExcelBtn.disabled = !((data.review_row_count || 0) > 0 || (data.change_count || 0) > 0);
            if (applyOssBtn) {
                applyOssBtn.disabled = !(data.change_count > 0) || !ossPushConfigured;
            }
        } catch (err) {
            analyzeStatus.textContent = 'Request failed: ' + err.message;
            analyzeStatus.classList.add('error');
        } finally {
            updateAnalyzeButton();
        }
    }

    async function applyToOss() {
        if (!previewToken || !applyConfirmation) return;
        const typed = prompt(
            `Apply proposed AMLE changes to NetAct OSS?\n\nType exactly:\n${applyConfirmation}`
        );
        if (typed !== applyConfirmation) {
            if (typed !== null) alert('Confirmation phrase did not match. No changes were sent.');
            return;
        }
        applyOssBtn.disabled = true;
        analyzeStatus.textContent = 'Uploading RAML plan to OSS and starting CM import…';
        analyzeStatus.classList.remove('error');
        try {
            const resp = await fetch('/api/nokia-load-balancing/apply', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ token: previewToken, confirmation: applyConfirmation, wait: true }),
            });
            const data = await resp.json();
            if (!resp.ok || !data.success) {
                analyzeStatus.textContent = data.error || 'OSS apply failed';
                analyzeStatus.classList.add('error');
                applyOssBtn.disabled = false;
                return;
            }
            analyzeStatus.textContent =
                `OSS import started · operation ${data.operation_id || '—'} · ${data.change_count || 0} parameter change(s)` +
                (data.status ? ` · status: ${data.status}` : '');
        } catch (err) {
            analyzeStatus.textContent = 'OSS apply failed: ' + err.message;
            analyzeStatus.classList.add('error');
            applyOssBtn.disabled = false;
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

    sectorCheckAll.addEventListener('change', () => {
        const checked = sectorCheckAll.checked;
        visibleSectorRows().forEach((row) => {
            const cb = row.querySelector('.sector-check');
            if (cb) cb.checked = checked;
        });
        updateRowSelectionStyles();
        updateSectorMeta();
        updateAnalyzeButton();
    });

    selectVisibleBtn.addEventListener('click', () => {
        visibleSectorRows().forEach((row) => {
            const cb = row.querySelector('.sector-check');
            if (cb) cb.checked = true;
        });
        updateRowSelectionStyles();
        updateSectorMeta();
        updateAnalyzeButton();
    });

    clearAllBtn.addEventListener('click', () => {
        sectorTableBody.querySelectorAll('.sector-check').forEach((el) => {
            el.checked = false;
        });
        sectorCheckAll.checked = false;
        updateRowSelectionStyles();
        updateSectorMeta();
        updateAnalyzeButton();
    });

    sectorFilter.addEventListener('input', applySectorFilter);
    syncBalanceBtn.addEventListener('click', syncBalance);
    refreshDbBtn.addEventListener('click', () => {
        loadDbStatus();
        loadSnapshots();
    });
    loadTrendBtn.addEventListener('click', loadTrend);
    reloadBtn.addEventListener('click', loadSectors);
    manualSectors.addEventListener('input', updateAnalyzeButton);
    analyzeBtn.addEventListener('click', analyze);
    downloadBackupXmlBtn.addEventListener('click', () =>
        downloadFile('/api/nokia-load-balancing/download-backup-xml', `nokia_lb_backup_${previewToken.slice(0, 8)}.xml`)
    );
    downloadXmlBtn.addEventListener('click', () =>
        downloadFile('/api/nokia-load-balancing/download-xml', `nokia_lb_${previewToken.slice(0, 8)}.xml`)
    );
    downloadExcelBtn.addEventListener('click', () =>
        downloadFile('/api/nokia-load-balancing/download-excel', `nokia_lb_${previewToken.slice(0, 8)}.xlsx`)
    );
    if (applyOssBtn) applyOssBtn.addEventListener('click', applyToOss);

    balanceDate.value = todayIso();
    ingestEnd.value = todayIso();
    ingestStart.value = daysAgoIso(13);
    trendEnd.value = todayIso();
    trendStart.value = daysAgoIso(13);
    setStatuses();
    loadDbStatus();
    loadSnapshots();
    if (document.body.dataset.balanceConfigured === 'true') {
        loadSectors();
    }
})();
