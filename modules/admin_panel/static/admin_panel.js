/**
 * Admin Panel Page JavaScript
 */

let syncMsgTimer = null;
let syncStatusRows = [];
let syncHistoryRows = [];
let retFallbackRows = [];
let cmExtractActivityRows = [];
let activityRows = [];
let filteredActivityRows = [];
let syncStatusPage = 1;
let syncHistoryPage = 1;
let activityPage = 1;
let activityLoaded = false;
const SYNC_PAGE_SIZE = 10;
const ACTIVITY_PAGE_SIZE = 15;
let progressPollTimer = null;
const API_CONNECTION_KEYS = ['nokia_cm', 'huawei_cm', 'huawei_pm'];

document.addEventListener('DOMContentLoaded', () => {
    const sectionFromUrl = new URLSearchParams(window.location.search).get('section');
    const firstTab = document.querySelector('.admin-page-tab.active');
    let defaultPage = sectionFromUrl || (firstTab ? firstTab.getAttribute('data-page') : 'data-sync');
    if (defaultPage === 'user-admin' || defaultPage === 'feature-access') {
        defaultPage = 'data-sync';
    }
    openAdminPage(defaultPage || 'data-sync');
    loadRetCredentialFallbacks();
    loadCmExtractActivity();
    loadSyncStatus();
    loadSyncHistory();
    loadRruInventoryStatus();
    loadAdjacencyGisStatus();
    startProgressPolling();
});

function openAdminPage(pageName) {
    document.querySelectorAll('.admin-page-tab').forEach(tab => {
        const isActive = tab.getAttribute('data-page') === pageName;
        tab.classList.toggle('active', isActive);
    });
    document.querySelectorAll('.admin-page-panel').forEach(panel => {
        panel.classList.toggle('active', panel.getAttribute('data-page') === pageName);
    });
    if (pageName === 'data-sync') {
        startProgressPolling();
    } else {
        stopProgressPolling();
    }
    if (pageName === 'activity-log' && !activityLoaded) {
        loadActivityLog();
    }
    if (pageName === 'pm-plus-rules') {
        refreshPmPlusRules();
    }
    if (pageName === 'ops-alerts') {
        loadRetCredentialFallbacks();
        loadCmExtractActivity();
    }
}

function stopProgressPolling() {
    if (progressPollTimer) {
        clearInterval(progressPollTimer);
        progressPollTimer = null;
    }
}

function startProgressPolling() {
    if (progressPollTimer) return;
    loadSyncProgress();
    progressPollTimer = setInterval(loadSyncProgress, 2500);
}

function _renderOneProgressCard(key, data) {
    const card = document.getElementById(`progress-card-${key}`);
    const meta = document.getElementById(`progress-meta-${key}`);
    const fill = document.getElementById(`progress-fill-${key}`);
    if (!card || !meta || !fill) return;

    const running = !!data?.running;
    const stage = String(data?.stage || 'idle');
    const percent = Math.max(0, Math.min(100, Number(data?.percent || 0)));
    const progress = Number(data?.progress || 0);
    const total = Number(data?.total || 0);
    const message = data?.message || '';
    const updatedAt = data?.updated_at || '';

    card.classList.remove('running', 'done', 'error', 'skipped');
    if (running || stage === 'running') card.classList.add('running');
    else if (stage === 'error') card.classList.add('error');
    else if (stage === 'skipped') card.classList.add('skipped');
    else if (stage === 'done') card.classList.add('done');

    fill.style.width = `${percent}%`;
    const counter = total > 0 ? `${progress}/${total} (${percent}%)` : `${percent}%`;
    const shortMsg = message ? ` - ${message}` : '';
    const stamp = updatedAt ? ` [${updatedAt}]` : '';
    meta.textContent = `${counter}${shortMsg}${stamp}`;
}

async function loadSyncProgress() {
    try {
        const res = await fetch('/api/sync/progress');
        const data = await res.json();
        if (!data.success || !data.progress) return;
        _renderOneProgressCard('nokia_pm', data.progress.nokia_pm || {});
        _renderOneProgressCard('huawei_pm', data.progress.huawei_pm || {});
        _renderOneProgressCard('metadata', data.progress.metadata || {});
    } catch (e) {
        // Keep UI silent on transient polling errors.
    }
}

function formatDate(dateString) {
    if (!dateString) return 'N/A';
    const date = new Date(dateString);
    return date.toLocaleDateString() + ' ' + date.toLocaleTimeString();
}

// ── Sync section ──────────────────────────────────────────────────────────

function _escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

function hideSyncMsg() {
    const el = document.getElementById('sync-msg');
    if (!el) return;
    el.style.display = 'none';
    if (syncMsgTimer) {
        clearTimeout(syncMsgTimer);
        syncMsgTimer = null;
    }
}

function showSyncMsg(text, type, fileLines = [], durationMs = 15000) {
    const el = document.getElementById('sync-msg');
    if (!el) return;

    const filesHtml = (fileLines && fileLines.length)
        ? `<div class="sync-msg-files">${fileLines.map(line => `<div class="sync-msg-file-line">${_escapeHtml(line)}</div>`).join('')}</div>`
        : '';

    el.className = 'sync-msg ' + type;
    el.innerHTML = `
        <button type="button" class="sync-msg-close" aria-label="Close" onclick="hideSyncMsg()">×</button>
        <div class="sync-msg-title">${_escapeHtml(text)}</div>
        ${filesHtml}
    `;
    el.style.display = 'block';
    if (syncMsgTimer) clearTimeout(syncMsgTimer);
    syncMsgTimer = setTimeout(() => {
        hideSyncMsg();
    }, durationMs);
}

async function fetchLatestDownloadedFiles(type) {
    try {
        const res = await fetch(`/api/sync/latest_downloads?type=${encodeURIComponent(type)}`);
        const data = await res.json();
        if (!data.success || !data.downloads) return [];

        const downloads = data.downloads[type];
        if (!downloads || !Array.isArray(downloads.files) || downloads.files.length === 0) {
            return ['No downloaded files found yet for this source.'];
        }
        return downloads.files.slice(0, 8).map(f => `${f.name} (${f.modified_at})`);
    } catch (e) {
        return [`Could not load file list: ${e.message}`];
    }
}

function renderSyncRows(rows, tbodyId) {
    const tbody = document.getElementById(tbodyId);
    if (!rows || rows.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;">No data</td></tr>';
        return;
    }
    tbody.innerHTML = rows.map((r, idx) => {
        const isError = String(r.status || '').toLowerCase() === 'error';
        const msg = r.message || '-';
        const safeTitle = _escapeHtml(msg);
        const shortMsg = _escapeHtml(msg);
        const errorBtn = isError && msg && msg !== '-'
            ? `<button class="btn-small btn-small-secondary" style="margin-left:8px;" onclick="showSyncHistoryError(${idx}, '${tbodyId}')">View</button>`
            : '';
        return `
        <tr>
            <td>${r.sync_type || ''}</td>
            <td>${r.technology || ''}</td>
            <td><span class="sync-badge ${r.status}">${r.status}</span></td>
            <td>${r.rows_affected != null ? r.rows_affected : '-'}</td>
            <td style="max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"
                title="${safeTitle}">${shortMsg}${errorBtn}</td>
            <td>${r.started_at || '-'}</td>
        </tr>
    `;
    }).join('');
}

function showSyncHistoryError(index, tbodyId) {
    try {
        const list = tbodyId === 'sync-history-body' ? syncHistoryRows : syncStatusRows;
        const start = tbodyId === 'sync-history-body'
            ? (syncHistoryPage - 1) * SYNC_PAGE_SIZE
            : (syncStatusPage - 1) * SYNC_PAGE_SIZE;
        const row = list[start + Number(index)];
        const message = (row && row.message) ? String(row.message) : 'No error details available.';
        alert(message);
    } catch (e) {
        alert('Could not open error details.');
    }
}

function renderPagination(containerId, totalItems, pageSize, currentPage, callbackName) {
    const el = document.getElementById(containerId);
    if (!el) return;
    const totalPages = Math.max(1, Math.ceil(totalItems / pageSize));
    if (totalItems <= pageSize) {
        el.innerHTML = '';
        return;
    }
    const prevDisabled = currentPage <= 1 ? 'disabled' : '';
    const nextDisabled = currentPage >= totalPages ? 'disabled' : '';
    el.innerHTML = `
        <button class="page-btn" ${prevDisabled} onclick="${callbackName}(${currentPage - 1})">Prev</button>
        <span class="page-info">Page ${currentPage} of ${totalPages}</span>
        <button class="page-btn" ${nextDisabled} onclick="${callbackName}(${currentPage + 1})">Next</button>
    `;
}

function goToSyncStatusPage(page) {
    syncStatusPage = Math.max(1, page);
    renderSyncStatusPage();
}

function goToSyncHistoryPage(page) {
    syncHistoryPage = Math.max(1, page);
    renderSyncHistoryPage();
}

function renderSyncStatusPage() {
    const start = (syncStatusPage - 1) * SYNC_PAGE_SIZE;
    const rows = syncStatusRows.slice(start, start + SYNC_PAGE_SIZE);
    renderSyncRows(rows, 'sync-status-body');
    renderPagination('sync-status-pagination', syncStatusRows.length, SYNC_PAGE_SIZE, syncStatusPage, 'goToSyncStatusPage');
}

function renderSyncHistoryPage() {
    const start = (syncHistoryPage - 1) * SYNC_PAGE_SIZE;
    const rows = syncHistoryRows.slice(start, start + SYNC_PAGE_SIZE);
    renderSyncRows(rows, 'sync-history-body');
    renderPagination('sync-history-pagination', syncHistoryRows.length, SYNC_PAGE_SIZE, syncHistoryPage, 'goToSyncHistoryPage');
}

async function loadSyncStatus() {
    try {
        const res  = await fetch('/api/sync/status');
        const data = await res.json();
        if (data.success) {
            syncStatusRows = data.last_syncs || [];
            syncStatusPage = 1;
            renderSyncStatusPage();
        }
    } catch (e) {
        document.getElementById('sync-status-body').innerHTML =
            `<tr><td colspan="6" style="color:#e74c3c;text-align:center;">Error: ${_escapeHtml(e.message)}</td></tr>`;
    }
}

async function loadSyncHistory() {
    try {
        const dayEl = document.getElementById('sync-history-day');
        const typeEl = document.getElementById('sync-history-type');
        const day = dayEl && dayEl.value ? dayEl.value : '';
        const syncType = typeEl && typeEl.value ? typeEl.value : '';
        const qs = new URLSearchParams({ limit: '100' });
        if (day) qs.set('day', day);
        if (syncType) qs.set('sync_type', syncType);
        const res  = await fetch(`/api/sync/history?${qs.toString()}`);
        const data = await res.json();
        if (data.success) {
            syncHistoryRows = data.history || [];
            syncHistoryPage = 1;
            renderSyncHistoryPage();
        }
    } catch (e) {
        document.getElementById('sync-history-body').innerHTML =
            `<tr><td colspan="6" style="color:#e74c3c;text-align:center;">Error: ${_escapeHtml(e.message)}</td></tr>`;
    }
}

function clearSyncHistoryFilters() {
    const dayEl = document.getElementById('sync-history-day');
    const typeEl = document.getElementById('sync-history-type');
    if (dayEl) dayEl.value = '';
    if (typeEl) typeEl.value = '';
    loadSyncHistory();
}

async function triggerSync(type) {
    // type: 'nokia_pm' | 'huawei_pm' | 'metadata' | category refresh keys
    const endpointMap = {
        nokia_pm:  '/api/sync/trigger/nokia_pm',
        huawei_pm: '/api/sync/trigger/huawei_pm',
        metadata:  '/api/sync/trigger/metadata',
        cells_hourly: '/api/sync/trigger/cells_hourly',
        cells_daily: '/api/sync/trigger/cells_daily',
        groups_hourly: '/api/sync/trigger/groups_hourly',
        groups_daily: '/api/sync/trigger/groups_daily',
    };

    const endpoint = endpointMap[type] || '/api/sync/trigger/pm';

    showSyncMsg(`Triggering ${type.replace('_', ' ')} sync...`, 'info');

    try {
        const res  = await fetch(endpoint, { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            // Give background trigger a short head start, then show latest downloaded files.
            await new Promise(resolve => setTimeout(resolve, 2200));
            const latestFiles = (type === 'nokia_pm' || type === 'huawei_pm' || type === 'metadata')
                ? await fetchLatestDownloadedFiles(type)
                : [];
            showSyncMsg(data.message || 'Sync started in background.', 'success', latestFiles);
            // Refresh status after a short delay
            setTimeout(loadSyncStatus,  4000);
            setTimeout(loadSyncHistory, 4000);
        } else {
            showSyncMsg(data.error || 'Sync trigger failed.', 'error');
        }
    } catch (e) {
        showSyncMsg('Error: ' + e.message, 'error');
    }
}

async function triggerRruInventory() {
    showSyncMsg('Starting Configuration Dashboard ingest (RMOD_R + WNCELG)…', 'info');
    try {
        const res = await fetch('/api/admin/configuration-dashboard/run', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            showSyncMsg(data.message || 'Dashboard ingest started.', 'success');
            setTimeout(loadRruInventoryStatus, 5000);
            setTimeout(loadSyncHistory, 8000);
        } else {
            showSyncMsg(data.error || 'Dashboard ingest trigger failed.', 'error');
        }
    } catch (e) {
        showSyncMsg('Error: ' + e.message, 'error');
    }
}

async function loadRruInventoryStatus() {
    const el = document.getElementById('rru-inventory-status');
    try {
        const res = await fetch('/api/admin/configuration-dashboard/status');
        const data = await res.json();
        if (!res.ok || !data.success) {
            if (el) el.textContent = data.error || 'Failed to load dashboard status.';
            return;
        }
        const snap = data.hardware || data.snapshot || {};
        const wncelg = data.wncelg || {};
        const last = data.last_run || {};
        const parts = [
            `Schedule: ${data.schedule || 'Daily 04:00'}`,
            `Nokia: ${data.nokia_ready ? 'configured' : 'not configured'}`,
            `Hardware: ${snap.built_at || 'none'} (${snap.status || 'n/a'}, ${snap.row_count || 0} RRUs)`,
            `WNCELG: ${wncelg.built_at || 'none'} (${wncelg.status || 'n/a'}, ${wncelg.site_count || 0} sites)`,
        ];
        if (last.trigger_source) {
            parts.push(`Last run: ${last.trigger_source} ${last.success === false ? 'FAILED' : 'ok'}`);
        }
        if (snap.error) parts.push(`Hardware error: ${snap.error}`);
        if (wncelg.error) parts.push(`WNCELG error: ${wncelg.error}`);
        if (el) el.textContent = parts.join(' · ');
    } catch (e) {
        if (el) el.textContent = 'Status error: ' + e.message;
    }
}

async function triggerAdjacencyGis(vendor = 'all') {
    showSyncMsg(`Starting Adjacency GIS ingest (${vendor})…`, 'info');
    try {
        const res = await fetch('/api/admin/adjacency-gis/run', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ vendor }),
        });
        const data = await res.json();
        if (data.success) {
            showSyncMsg(data.message || 'Adjacency GIS ingest started.', 'success');
            setTimeout(loadAdjacencyGisStatus, 5000);
            setTimeout(loadSyncHistory, 8000);
        } else {
            showSyncMsg(data.error || 'Adjacency GIS trigger failed.', 'error');
        }
    } catch (e) {
        showSyncMsg('Error: ' + e.message, 'error');
    }
}

async function loadAdjacencyGisStatus() {
    const el = document.getElementById('adjacency-gis-status');
    try {
        const res = await fetch('/api/admin/adjacency-gis/status');
        const data = await res.json();
        if (!res.ok || !data.success) {
            if (el) el.textContent = data.error || 'Failed to load Adjacency GIS status.';
            return;
        }
        const snap = data.snapshot || {};
        const nok = data.nokia || {};
        const huw = data.huawei || {};
        const parts = [
            `Schedule: ${data.schedule || 'Nokia 04:30 / Huawei 04:45'}`,
            `Nokia CM: ${data.nokia_ready ? 'ok' : 'n/a'} (${nok.built_at || 'none'}, sec ${nok.sector_count || 0}, edg ${nok.edge_count || 0})`,
            `Huawei CM: ${data.huawei_ready ? 'ok' : 'n/a'} (${huw.built_at || 'none'}, sec ${huw.sector_count || 0}, edg ${huw.edge_count || 0})`,
            `Combined: ${snap.sector_count || 0} sectors / ${snap.edge_count || 0} edges`,
        ];
        if (snap.error) parts.push(`Error: ${snap.error}`);
        if (el) el.textContent = parts.join(' · ');
    } catch (e) {
        if (el) el.textContent = 'Status error: ' + e.message;
    }
}

async function loadPmLatestTimestamps() {
    showSyncMsg('Reading PM databases…', 'info', [], 45000);
    try {
        const res = await fetch('/api/admin/pm-latest-timestamps');
        const data = await res.json();
        if (!res.ok || data.error) {
            showSyncMsg(data.error || `HTTP ${res.status}`, 'error', [], 20000);
            return;
        }
        if (!data.success) {
            showSyncMsg(data.error || 'Request failed', 'error', [], 20000);
            return;
        }
        const lines = [];
        (data.databases || []).forEach((d) => {
            const pathInfo = d.path ? ` (${d.path})` : (d.schema ? ` (schema ${d.schema})` : '');
            if (d.error) {
                lines.push(`${d.label}: error — ${d.error}${pathInfo}`);
                return;
            }
            if (!d.exists) {
                lines.push(`${d.label}: no database file yet${pathInfo}`);
                return;
            }
            const ts = d.last_timestamp || 'no data / no timestamp column';
            const tbl = d.latest_table ? ` [table: ${d.latest_table}]` : '';
            lines.push(`${d.label}: ${ts}${tbl}`);

            // Detailed breakdown per table/technology for easier validation.
            const details = Array.isArray(d.per_table) ? d.per_table : [];
            if (!details.length) {
                lines.push('  - no per-table timestamps found');
                return;
            }
            const sorted = [...details].sort((a, b) => {
                const ta = String(a?.table || '').toLowerCase();
                const tb = String(b?.table || '').toLowerCase();
                return ta.localeCompare(tb);
            });
            sorted.forEach((entry) => {
                lines.push(`  - ${entry.table}: ${entry.last_timestamp || 'n/a'}`);
            });
        });
        showSyncMsg('Latest timestamp in each PM database', 'success', lines, 60000);
    } catch (e) {
        showSyncMsg('Error: ' + e.message, 'error', [], 20000);
    }
}

async function inspectLocal() {
    const pre = document.getElementById('inspect-output');
    pre.style.display = 'block';
    pre.textContent = 'Reading locally downloaded files…';

    function renderColumns(columns, indent) {
        const pad = '  '.repeat(indent);
        if (Array.isArray(columns)) {
            return [`${pad}Columns: ${columns.join(', ')}`];
        }
        if (columns && typeof columns === 'object') {
            // Excel file — columns is {sheetName: [col, ...], ...}
            return Object.entries(columns).flatMap(([sheet, cols]) =>
                [`${pad}Sheet [${sheet}]: ${Array.isArray(cols) ? cols.join(', ') : cols}`]
            );
        }
        return [];
    }

    try {
        const res  = await fetch('/api/sync/inspect_local');
        const data = await res.json();
        if (!data.success) { pre.textContent = 'Error: ' + (data.error || 'unknown'); return; }

        const lines = [];
        const r = data.report;

        for (const [source, info] of Object.entries(r)) {
            lines.push(`\n══ ${source.toUpperCase()} ══`);

            if (info.status === 'no_files') {
                lines.push(`  No files found in ${info.dir}`);
                lines.push(`  → Trigger a sync first, then click Inspect again.`);
                continue;
            }
            if (info.status === 'read_error') {
                lines.push(`  ERROR reading ${info.file}: ${info.error}`);
                continue;
            }

            // Nokia PM / Huawei PM — single file result
            if (!info.files) {
                lines.push(`  File: ${info.file}`);
                lines.push(...renderColumns(info.columns, 2));
            }

            // Metadata — multiple files
            if (info.files) {
                for (const [key, fr] of Object.entries(info.files)) {
                    lines.push(`  [${key}] ${fr.file}`);
                    if (fr.error) {
                        lines.push(`    ERROR: ${fr.error}`);
                    } else {
                        lines.push(...renderColumns(fr.columns, 3));
                    }
                }
            }
        }
        pre.textContent = lines.join('\n');
    } catch (e) {
        pre.textContent = 'Error: ' + e.message;
    }
}

async function importPmFromPath() {
    const pathEl = document.getElementById('pm-local-path');
    const vendorEl = document.getElementById('pm-local-vendor');
    const recursiveEl = document.getElementById('pm-local-recursive');

    const path = (pathEl?.value || '').trim();
    const vendor = (vendorEl?.value || 'all').trim().toLowerCase();
    const recursive = !!(recursiveEl?.checked);

    if (!path) {
        showSyncMsg('Please provide a local folder path first.', 'error');
        return;
    }

    showSyncMsg('Starting local PM import…', 'info', [
        `Path: ${path}`,
        `Vendor: ${vendor}`,
        `Recursive: ${recursive ? 'yes' : 'no'}`,
    ]);

    try {
        const res = await fetch('/api/sync/import_pm_path', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path, vendor, recursive }),
        });
        const data = await res.json();
        if (data.success) {
            showSyncMsg(data.message || 'Local PM import started.', 'success', [
                `Path: ${path}`,
                `Vendor: ${vendor}`,
                'Track progress in Sync History.',
            ]);
            setTimeout(loadSyncStatus, 4000);
            setTimeout(loadSyncHistory, 4000);
            setTimeout(loadSyncStatus, 12000);
            setTimeout(loadSyncHistory, 12000);
        } else {
            showSyncMsg(data.error || 'Local PM import failed to start.', 'error');
        }
    } catch (e) {
        showSyncMsg('Error: ' + e.message, 'error');
    }
}

async function testConnectivity() {
    showSyncMsg('Testing connectivity to all servers…', 'info');
    try {
        const res  = await fetch('/api/sync/test');
        const data = await res.json();
        if (!data.success) { showSyncMsg('Test failed.', 'error'); return; }

        const r = data.results;
        const lines = Object.entries(r).map(([name, info]) => {
            if (info.status === 'skipped') return `${name}: skipped (${info.reason})`;
            if (info.status === 'error')   return `${name}: ERROR — ${info.error}`;
            if (info.tree) {
                const f = info.tree.latest_folder || '(none)';
                const keys = Object.keys(info.tree.structure || {});
                return `${name}: OK — latest folder: ${f}, sub-keys: ${keys.join(', ') || 'flat'}`;
            }
            if (info.dirs) {
                const summary = Object.entries(info.dirs)
                    .map(([t, d]) => `${t}:${d.excel_files ?? d.files_found ?? '?'}`)
                    .join(' ');
                return `${name}: OK — ${summary}`;
            }
            return `${name}: OK — ${info.excel_files ?? info.files_found ?? '?'} files`;
        });
        showSyncMsg(lines.join(' | '), 'success');
    } catch (e) {
        showSyncMsg('Error: ' + e.message, 'error');
    }
}

function _setApiConnectionCard(key, result, testing = false) {
    const card = document.getElementById(`api-card-${key}`);
    const pill = document.getElementById(`api-status-${key}`);
    const endpointEl = document.getElementById(`api-endpoint-${key}`);
    const messageEl = document.getElementById(`api-message-${key}`);
    if (!pill || !messageEl) return;

    card?.classList.remove('api-ok', 'api-error', 'api-skipped', 'api-testing');
    pill.classList.remove('ok', 'error', 'skipped', 'testing', 'neutral');

    if (testing) {
        card?.classList.add('api-testing');
        pill.classList.add('testing');
        pill.textContent = 'Testing…';
        messageEl.textContent = 'Running live connection check…';
        return;
    }

    if (result?.endpoint && endpointEl) {
        endpointEl.textContent = result.endpoint;
    }

    const status = result?.status || 'skipped';
    if (status === 'ok') {
        card?.classList.add('api-ok');
        pill.classList.add('ok');
        pill.textContent = 'Connected';
        messageEl.textContent = result.message || 'Connection successful';
        return;
    }
    if (status === 'error') {
        card?.classList.add('api-error');
        pill.classList.add('error');
        pill.textContent = 'Failed';
        messageEl.textContent = result.message || result.error || 'Connection failed';
        return;
    }

    card?.classList.add('api-skipped');
    pill.classList.add('skipped');
    pill.textContent = 'Skipped';
    messageEl.textContent = result?.message || 'Not configured or disabled';
}

function _applyApiConnectionResults(results) {
    Object.entries(results || {}).forEach(([key, result]) => {
        _setApiConnectionCard(key, result, false);
    });
}

async function testApiConnection(vendor) {
    const keys = vendor === 'all' ? API_CONNECTION_KEYS : [vendor];
    keys.forEach(key => _setApiConnectionCard(key, null, true));

    try {
        const response = await fetch('/api/admin/test-api-connections', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ vendor }),
        });
        const data = await response.json();
        if (!response.ok || !data.success) {
            keys.forEach(key => _setApiConnectionCard(key, {
                status: 'error',
                message: data.error || `Request failed (HTTP ${response.status})`,
            }, false));
            showNotification(data.error || 'API connection test failed', 'error');
            return;
        }

        _applyApiConnectionResults(data.results || {});
        const summary = data.summary || {};
        if ((summary.failed || 0) > 0) {
            showNotification(`${summary.ok || 0} connected, ${summary.failed} failed`, 'error');
        } else if ((summary.tested || 0) > 0) {
            showNotification(`${summary.ok || 0} API connection(s) OK`, 'success');
        } else {
            showNotification('No APIs were configured for testing', 'info');
        }
    } catch (error) {
        keys.forEach(key => _setApiConnectionCard(key, {
            status: 'error',
            message: error.message || 'Connection test failed',
        }, false));
        showNotification(error.message || 'API connection test failed', 'error');
    }
}

async function testAllApiConnections() {
    const btn = document.getElementById('test-all-apis-btn');
    if (btn) btn.disabled = true;
    try {
        await testApiConnection('all');
    } finally {
        if (btn) btn.disabled = false;
    }
}

async function loadRetCredentialFallbacks() {
    const body = document.getElementById('ret-fallback-body');
    if (!body) return;
    try {
        const res = await fetch('/api/admin/ret-credential-fallbacks?limit=500');
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Failed to load fallback alerts');
        retFallbackRows = data.items || [];
        if (!retFallbackRows.length) {
            body.innerHTML = '<tr><td colspan="4" style="text-align:center;">No credential accountability alerts recorded.</td></tr>';
            return;
        }
        body.innerHTML = retFallbackRows.map((item) => {
            const action = item.action || '';
            const typeLabel = action === 'ret_missing_credentials'
                ? 'Missing credentials'
                : (action === 'ret_credential_fallback' ? 'Credential fallback' : action);
            return `
            <tr>
                <td>${(item.timestamp || '').slice(0, 19).replace('T', ' ')}</td>
                <td>${typeLabel}</td>
                <td>${_escapeHtml(item.username || ('User #' + (item.user_id || '?')))}</td>
                <td>${_escapeHtml(item.details || '')}</td>
            </tr>
        `;
        }).join('');
    } catch (error) {
        retFallbackRows = [];
        body.innerHTML = `<tr><td colspan="4" style="text-align:center;color:#c0392b;">${_escapeHtml(error.message || 'Load failed')}</td></tr>`;
    }
}

function _retAlertTypeLabel(action) {
    if (action === 'ret_missing_credentials') return 'Missing credentials';
    if (action === 'ret_credential_fallback') return 'Credential fallback';
    return action || '';
}

async function loadCmExtractActivity() {
    const body = document.getElementById('cm-extract-activity-body');
    if (!body) return;
    try {
        const res = await fetch('/api/admin/cm-extract-activity?limit=500');
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Failed to load CM extract activity');
        cmExtractActivityRows = data.items || [];
        if (!cmExtractActivityRows.length) {
            body.innerHTML = '<tr><td colspan="5" style="text-align:center;">No CM extractor activity recorded yet.</td></tr>';
            return;
        }
        body.innerHTML = cmExtractActivityRows.map((item) => `
            <tr>
                <td>${_escapeHtml((item.timestamp || '').slice(0, 19).replace('T', ' '))}</td>
                <td>${_escapeHtml(_activityActionLabel(item.action))}</td>
                <td>${_escapeHtml(item.username || ('User #' + (item.user_id || '?')))}</td>
                <td>${_escapeHtml(item.details || '')}</td>
                <td>${_escapeHtml(item.ip_address || '')}</td>
            </tr>
        `).join('');
    } catch (error) {
        cmExtractActivityRows = [];
        body.innerHTML = `<tr><td colspan="5" style="text-align:center;color:#c0392b;">${_escapeHtml(error.message || 'Load failed')}</td></tr>`;
    }
}

// ── Activity Log ───────────────────────────────────────────────────────────
const ACTIVITY_ACTION_LABELS = {
    login: 'Login',
    logout: 'Logout',
    register: 'Registered',
    config_upload: 'Config Uploaded',
    config_download: 'Config Downloaded',
    pci_conflict_check: 'PCI Check',
    report_generated: 'Report Generated',
    profile_update: 'Profile Updated',
    password_change: 'Password Changed',
    performance_view: 'Performance Viewed',
    saved_view_delete: 'Saved View Deleted',
    admin_table_export: 'Table Exported',
    vendor_credentials_save: 'Vendor Credentials Saved',
    vendor_credentials_clear: 'Vendor Credentials Cleared',
    ret_credential_fallback: 'RET Credential Fallback',
    ret_missing_credentials: 'RET Missing Credentials',
    cm_extract_start: 'CM Extract Started',
    cm_extract: 'CM Extract Success',
    cm_extract_async: 'CM Extract Async',
    cm_extract_fail: 'CM Extract Failed',
    cm_extract_download: 'CM Extract Download',
    cm_job_create: 'CM Job Created',
    cm_job_delete: 'CM Job Deleted',
    cm_job_download: 'CM Job Download',
    file_download: 'File Download',
};

function _activityActionLabel(action) {
    return ACTIVITY_ACTION_LABELS[action] || action || '';
}

function _activityUserLabel(item) {
    return item.username || `User #${item.user_id || '?'}`;
}

async function loadActivityLog() {
    const body = document.getElementById('activity-log-body');
    if (!body) return;
    activityLoaded = true;
    const limit = document.getElementById('activity-limit')?.value || '200';
    body.innerHTML = '<tr><td colspan="5" style="text-align:center;">Loading…</td></tr>';
    try {
        const res = await fetch(`/api/admin/activity?limit=${encodeURIComponent(limit)}`);
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Failed to load activity log');
        activityRows = data.activity || [];
        filterActivityLog();
    } catch (error) {
        activityRows = [];
        filteredActivityRows = [];
        body.innerHTML = `<tr><td colspan="5" style="text-align:center;color:#c0392b;">${_escapeHtml(error.message || 'Load failed')}</td></tr>`;
        renderPagination('activity-log-pagination', 0, ACTIVITY_PAGE_SIZE, 1, 'goToActivityPage');
    }
}

function filterActivityLog() {
    const term = (document.getElementById('activity-search')?.value || '').trim().toLowerCase();
    const actionPrefix = (document.getElementById('activity-action-filter')?.value || '').trim().toLowerCase();
    filteredActivityRows = activityRows.filter((item) => {
        const action = String(item.action || '').toLowerCase();
        if (actionPrefix === 'login') {
            if (action !== 'login' && action !== 'logout') return false;
        } else if (actionPrefix && !action.startsWith(actionPrefix)) {
            return false;
        }
        if (!term) return true;
        const haystack = [
            _activityUserLabel(item),
            _activityActionLabel(item.action),
            item.action,
            item.details,
            item.ip_address,
        ].join(' ').toLowerCase();
        return haystack.includes(term);
    });
    activityPage = 1;
    renderActivityPage();
}

function clearActivityFilters() {
    const search = document.getElementById('activity-search');
    if (search) search.value = '';
    const actionFilter = document.getElementById('activity-action-filter');
    if (actionFilter) actionFilter.value = '';
    filterActivityLog();
}

function goToActivityPage(page) {
    activityPage = Math.max(1, page);
    renderActivityPage();
}

function renderActivityPage() {
    const body = document.getElementById('activity-log-body');
    if (!body) return;
    if (!filteredActivityRows.length) {
        const message = activityRows.length ? 'No entries match the current filter.' : 'No activity recorded yet.';
        body.innerHTML = `<tr><td colspan="5" style="text-align:center;">${message}</td></tr>`;
        renderPagination('activity-log-pagination', 0, ACTIVITY_PAGE_SIZE, 1, 'goToActivityPage');
        return;
    }
    const start = (activityPage - 1) * ACTIVITY_PAGE_SIZE;
    body.innerHTML = filteredActivityRows.slice(start, start + ACTIVITY_PAGE_SIZE).map((item) => `
        <tr>
            <td>${_escapeHtml((item.timestamp || '').slice(0, 19).replace('T', ' '))}</td>
            <td>${_escapeHtml(_activityActionLabel(item.action))}</td>
            <td>${_escapeHtml(_activityUserLabel(item))}</td>
            <td>${_escapeHtml(item.details || '')}</td>
            <td>${_escapeHtml(item.ip_address || '')}</td>
        </tr>
    `).join('');
    renderPagination('activity-log-pagination', filteredActivityRows.length, ACTIVITY_PAGE_SIZE, activityPage, 'goToActivityPage');
}

function _activityRowExport(item) {
    return {
        timestamp: (item.timestamp || '').slice(0, 19).replace('T', ' '),
        action: _activityActionLabel(item.action),
        username: _activityUserLabel(item),
        details: item.details || '',
        ip_address: item.ip_address || '',
    };
}

function _syncRowExport(row) {
    return {
        sync_type: row.sync_type || '',
        technology: row.technology || '',
        status: row.status || '',
        rows_affected: row.rows_affected != null ? row.rows_affected : '',
        message: row.message || '',
        started_at: row.started_at || '',
    };
}

async function downloadAdminExcel(payload) {
    const res = await fetch('/api/admin/export/excel', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });
    if (!res.ok) {
        let message = 'Excel export failed';
        try {
            const data = await res.json();
            message = data.error || message;
        } catch (_) {
            /* ignore */
        }
        throw new Error(message);
    }
    const blob = await res.blob();
    const disposition = res.headers.get('Content-Disposition') || '';
    const match = disposition.match(/filename="?([^";]+)"?/i);
    const filename = match ? match[1] : `${payload.filename_stem || 'export'}_${Date.now()}.xlsx`;
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
}

async function exportAdminTable(tableKey) {
    try {
        let payload;
        if (tableKey === 'sync_status') {
            if (!syncStatusRows.length) {
                showNotification('No sync status rows to export', 'error');
                return;
            }
            payload = {
                table: 'sync_status',
                report_title: 'Last Sync per Source',
                sheet_title: 'Sync Status',
                filename_stem: 'Admin_Sync_Status',
                columns: ['sync_type', 'technology', 'status', 'rows_affected', 'message', 'started_at'],
                column_labels: {
                    sync_type: 'Type',
                    technology: 'Technology',
                    status: 'Status',
                    rows_affected: 'Rows',
                    message: 'Message',
                    started_at: 'When',
                },
                rows: syncStatusRows.map(_syncRowExport),
            };
        } else if (tableKey === 'sync_history') {
            if (!syncHistoryRows.length) {
                showNotification('No sync history rows to export', 'error');
                return;
            }
            const day = document.getElementById('sync-history-day')?.value || '';
            const syncType = document.getElementById('sync-history-type')?.value || '';
            payload = {
                table: 'sync_history',
                report_title: 'Recent Sync History',
                sheet_title: 'Sync History',
                filename_stem: 'Admin_Sync_History',
                columns: ['sync_type', 'technology', 'status', 'rows_affected', 'message', 'started_at'],
                column_labels: {
                    sync_type: 'Type',
                    technology: 'Technology',
                    status: 'Status',
                    rows_affected: 'Rows',
                    message: 'Message',
                    started_at: 'When',
                },
                rows: syncHistoryRows.map(_syncRowExport),
                meta: {
                    'Day Filter': day || '(all)',
                    'Type Filter': syncType || '(all)',
                },
            };
        } else if (tableKey === 'ret_credential_alerts') {
            if (!retFallbackRows.length) {
                await loadRetCredentialFallbacks();
            }
            if (!retFallbackRows.length) {
                showNotification('No RET credential alerts to export', 'error');
                return;
            }
            payload = {
                table: 'ret_credential_alerts',
                report_title: 'RET Credential Accountability Alerts',
                sheet_title: 'RET Alerts',
                filename_stem: 'Admin_RET_Credential_Alerts',
                columns: ['timestamp', 'type', 'username', 'details'],
                column_labels: {
                    timestamp: 'When',
                    type: 'Type',
                    username: 'User',
                    details: 'Details',
                },
                rows: retFallbackRows.map((item) => ({
                    timestamp: (item.timestamp || '').slice(0, 19).replace('T', ' '),
                    type: _retAlertTypeLabel(item.action),
                    username: item.username || (`User #${item.user_id || '?'}`),
                    details: item.details || '',
                })),
            };
        } else if (tableKey === 'cm_extract_activity') {
            if (!cmExtractActivityRows.length) {
                await loadCmExtractActivity();
            }
            if (!cmExtractActivityRows.length) {
                showNotification('No CM extractor activity to export', 'error');
                return;
            }
            payload = {
                table: 'cm_extract_activity',
                report_title: 'CM Extractor Activity',
                sheet_title: 'CM Extract Activity',
                filename_stem: 'Admin_CM_Extract_Activity',
                columns: ['timestamp', 'action', 'username', 'details', 'ip_address'],
                column_labels: {
                    timestamp: 'When',
                    action: 'Action',
                    username: 'User',
                    details: 'Details',
                    ip_address: 'IP Address',
                },
                rows: cmExtractActivityRows.map((item) => ({
                    timestamp: (item.timestamp || '').slice(0, 19).replace('T', ' '),
                    action: _activityActionLabel(item.action),
                    username: item.username || (`User #${item.user_id || '?'}`),
                    details: item.details || '',
                    ip_address: item.ip_address || '',
                })),
            };
        } else if (tableKey === 'recent_activity') {
            if (!activityLoaded) {
                await loadActivityLog();
            }
            if (!filteredActivityRows.length) {
                showNotification('No activity entries to export', 'error');
                return;
            }
            payload = {
                table: 'recent_activity',
                report_title: 'Activity Log',
                sheet_title: 'Activity Log',
                filename_stem: 'Admin_Activity_Log',
                columns: ['timestamp', 'action', 'username', 'details', 'ip_address'],
                column_labels: {
                    timestamp: 'When',
                    action: 'Action',
                    username: 'User',
                    details: 'Details',
                    ip_address: 'IP Address',
                },
                rows: filteredActivityRows.map(_activityRowExport),
                meta: {
                    'Search Filter': document.getElementById('activity-search')?.value?.trim() || '(none)',
                    'Action Filter': document.getElementById('activity-action-filter')?.value || '(all)',
                    'Records Loaded': `Last ${document.getElementById('activity-limit')?.value || '200'}`,
                },
            };
        } else {
            showNotification('Unknown table export', 'error');
            return;
        }

        await downloadAdminExcel(payload);
        showNotification(`Downloaded ${payload.rows.length} row(s) to Excel`, 'success');
    } catch (error) {
        showNotification(error.message || 'Excel export failed', 'error');
    }
}

// ── PM Plus aggregation rules ──────────────────────────────────────────────
let pmPlusCounterTimer = null;

function _pmPlusMsg(text, show) {
    const el = document.getElementById('pm-plus-rules-msg');
    if (!el) return;
    el.textContent = text || '';
    el.style.display = show === false || !text ? 'none' : '';
}

async function refreshPmPlusRules() {
    const famBox = document.getElementById('pm-plus-families');
    if (!famBox) return;
    famBox.innerHTML = '<p class="api-connections-intro">Loading…</p>';
    try {
        const fres = await fetch('/api/admin/pm-plus/rules/families');
        const fdata = await fres.json();
        if (!fres.ok || !fdata.success) {
            famBox.innerHTML = `<p class="api-connections-intro">${(fdata && fdata.error) || 'Failed to load families'}</p>`;
            return;
        }
        const opts = ['SUM', 'AVG', 'MAX', 'MIN'];
        const rows = (fdata.families || []).slice(0, 300);
        if (!rows.length) {
            famBox.innerHTML = '<p class="api-connections-intro">No family rules yet — import Nokia Excel catalog.</p>';
        } else {
            famBox.innerHTML = rows.map((f) => {
                const ta = opts.map((o) =>
                    `<option value="${o}" ${f.time_agg === o ? 'selected' : ''}>${o}</option>`
                ).join('');
                const na = opts.map((o) =>
                    `<option value="${o}" ${f.nw_agg === o ? 'selected' : ''}>${o}</option>`
                ).join('');
                return `<div class="pm-plus-rule-row">
                    <strong>${f.family}</strong>
                    <label>time <select data-fam="${f.family}" data-field="time_agg">${ta}</select></label>
                    <label>nw <select data-fam="${f.family}" data-field="nw_agg">${na}</select></label>
                    <button type="button" class="btn-user-secondary" data-fam="${f.family}" onclick="savePmPlusFamily(this)">Save</button>
                </div>`;
            }).join('');
        }
        await loadPmPlusCounters();
    } catch (e) {
        famBox.innerHTML = '<p class="api-connections-intro">Network error loading rules.</p>';
    }
}

async function savePmPlusFamily(btn) {
    const fam = btn.dataset.fam;
    const famBox = document.getElementById('pm-plus-families');
    const timeSel = famBox.querySelector(`select[data-fam="${fam}"][data-field="time_agg"]`);
    const nwSel = famBox.querySelector(`select[data-fam="${fam}"][data-field="nw_agg"]`);
    try {
        const res = await fetch('/api/admin/pm-plus/rules/families', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                family: fam,
                time_agg: timeSel.value,
                nw_agg: nwSel.value,
                enabled: true,
            }),
        });
        const data = await res.json();
        _pmPlusMsg(JSON.stringify(data, null, 2));
        showNotification(data.success ? `Saved ${fam}` : (data.error || 'Save failed'), data.success ? 'success' : 'error');
    } catch (e) {
        showNotification('Network error saving family', 'error');
    }
}

function debouncePmPlusCounters() {
    clearTimeout(pmPlusCounterTimer);
    pmPlusCounterTimer = setTimeout(loadPmPlusCounters, 300);
}

async function loadPmPlusCounters() {
    const ctrBox = document.getElementById('pm-plus-counters');
    if (!ctrBox) return;
    const q = (document.getElementById('pm-plus-counter-q')?.value || '').trim();
    ctrBox.innerHTML = '<p class="api-connections-intro">Loading…</p>';
    try {
        const res = await fetch(`/api/admin/pm-plus/rules/counters?q=${encodeURIComponent(q)}&limit=80`);
        const data = await res.json();
        if (!res.ok || !data.success) {
            ctrBox.innerHTML = `<p class="api-connections-intro">${(data && data.error) || 'Failed'}</p>`;
            return;
        }
        const opts = ['SUM', 'AVG', 'MAX', 'MIN'];
        ctrBox.innerHTML = (data.counters || []).map((c) => {
            const ta = opts.map((o) =>
                `<option value="${o}" ${c.time_agg === o ? 'selected' : ''}>${o}</option>`
            ).join('');
            const ov = c.time_agg_override ? ' (override)' : '';
            return `<div class="pm-plus-rule-row">
                <strong>${c.counter_id}</strong>
                <span class="api-connections-intro">${c.family || ''}${ov}</span>
                <select data-cid="${c.counter_id}">${ta}</select>
                <button type="button" class="btn-user-secondary" data-cid="${c.counter_id}" onclick="savePmPlusCounter(this)">Override</button>
                <button type="button" class="btn-user-secondary" data-cid="${c.counter_id}" onclick="clearPmPlusCounter(this)">Clear</button>
            </div>`;
        }).join('') || '<p class="api-connections-intro">No counters match.</p>';
    } catch (e) {
        ctrBox.innerHTML = '<p class="api-connections-intro">Network error.</p>';
    }
}

async function savePmPlusCounter(btn) {
    const cid = btn.dataset.cid;
    const sel = document.querySelector(`#pm-plus-counters select[data-cid="${cid}"]`);
    try {
        const res = await fetch('/api/admin/pm-plus/rules/counters', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ counter_id: cid, time_agg: sel.value, nw_agg: sel.value }),
        });
        const data = await res.json();
        _pmPlusMsg(JSON.stringify(data, null, 2));
        showNotification(data.success ? `Override ${cid}` : (data.error || 'Failed'), data.success ? 'success' : 'error');
    } catch (e) {
        showNotification('Network error', 'error');
    }
}

async function clearPmPlusCounter(btn) {
    try {
        const res = await fetch('/api/admin/pm-plus/rules/counters', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ counter_id: btn.dataset.cid, clear: true }),
        });
        const data = await res.json();
        _pmPlusMsg(JSON.stringify(data, null, 2));
        showNotification(data.success ? 'Cleared override' : (data.error || 'Failed'), data.success ? 'success' : 'error');
        loadPmPlusCounters();
    } catch (e) {
        showNotification('Network error', 'error');
    }
}

async function importPmPlusCatalog() {
    _pmPlusMsg('Importing catalog…');
    try {
        const res = await fetch('/api/admin/pm-plus/catalog/import', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({}),
        });
        const data = await res.json();
        _pmPlusMsg(JSON.stringify(data, null, 2));
        showNotification(data.success ? 'Catalog imported' : (data.error || 'Import failed'), data.success ? 'success' : 'error');
        if (data.success) refreshPmPlusRules();
    } catch (e) {
        showNotification('Network error importing catalog', 'error');
    }
}

async function runPmPlusRollup() {
    _pmPlusMsg('Running rollup…');
    try {
        const res = await fetch('/api/admin/pm-plus/rollup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ retention: true }),
        });
        const data = await res.json();
        _pmPlusMsg(JSON.stringify(data, null, 2));
        showNotification(data.success ? 'Rollup finished' : (data.error || 'Rollup failed'), data.success ? 'success' : 'error');
    } catch (e) {
        showNotification('Network error running rollup', 'error');
    }
}
