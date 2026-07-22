/**
 * Admin Panel Page JavaScript
 */

let allUsers = [];
let filteredUsers = [];
let syncMsgTimer = null;
let syncStatusRows = [];
let syncHistoryRows = [];
let usersPage = 1;
let syncStatusPage = 1;
let syncHistoryPage = 1;
const USERS_PAGE_SIZE = 12;
const SYNC_PAGE_SIZE = 10;
let progressPollTimer = null;
const ROLE_LABELS = {
    admin: 'Owner',
    user: 'User',
    ran_config_user: 'RNC User',
    noc_sys: 'NOC SYS',
};
const DEFAULT_USER_PASSWORD = document.getElementById('default-user-password-label')?.textContent?.trim() || 'Zain@1234';
const CURRENT_USER_ID = Number(document.body?.dataset?.currentUserId || 0);
const API_CONNECTION_KEYS = ['nokia_cm', 'huawei_cm', 'huawei_pm'];

document.addEventListener('DOMContentLoaded', () => {
    const sectionFromUrl = new URLSearchParams(window.location.search).get('section');
    const firstTab = document.querySelector('.admin-page-tab.active');
    const defaultPage = sectionFromUrl || (firstTab ? firstTab.getAttribute('data-page') : 'user-admin');
    openAdminPage(defaultPage || 'user-admin');
    loadAllUsers();
    if (document.querySelector('.admin-page-tab[data-page="data-sync"]')) {
        loadSyncStatus();
        loadSyncHistory();
        startProgressPolling();
    }
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
    if (pageName === 'feature-access' && !featureAccessLoaded) {
        loadFeatureAccess();
    }
}

// ── Feature Access ─────────────────────────────────────────────────────────
let featureAccessLoaded = false;
let featureAccessRoles = [];

function _setFeatureStatus(msg, isError) {
    const el = document.getElementById('feature-access-status');
    if (!el) return;
    el.textContent = msg || '';
    el.classList.toggle('is-error', !!isError);
}

async function loadFeatureAccess() {
    try {
        const res = await fetch('/api/admin/feature-access');
        const data = await res.json();
        if (!res.ok || !data.success) {
            _setFeatureStatus((data && data.error) || 'Failed to load.', true);
            return;
        }
        featureAccessRoles = data.editable_roles || [];
        renderFeatureAccess(data.features || []);
        featureAccessLoaded = true;
        _setFeatureStatus('');
    } catch (e) {
        _setFeatureStatus('Network error loading feature access.', true);
    }
}

function renderFeatureAccess(features) {
    const head = document.getElementById('feature-access-head');
    const body = document.getElementById('feature-access-body');
    if (!head || !body) return;

    let headHtml = '<tr><th>Feature</th><th>Section</th><th class="fa-owner-col">Owner</th>';
    featureAccessRoles.forEach(r => { headHtml += `<th>${r.label}</th>`; });
    headHtml += '</tr>';
    head.innerHTML = headHtml;

    let rows = '';
    features.forEach(f => {
        const enabled = new Set(f.roles || []);
        let cells = '';
        featureAccessRoles.forEach(r => {
            const checked = enabled.has(r.key) ? 'checked' : '';
            const dis = f.locked ? 'disabled' : '';
            cells += `<td class="fa-check"><input type="checkbox" data-href="${f.href}" data-role="${r.key}" ${checked} ${dis}></td>`;
        });
        const lockBadge = f.locked ? ' <span class="fa-lock" title="Core feature — cannot be restricted">🔒</span>' : '';
        rows += `<tr class="fa-row" data-label="${(f.label + ' ' + f.href).toLowerCase()}">
            <td class="fa-name">${f.label}${lockBadge}<span class="fa-href">${f.href}</span></td>
            <td class="fa-section">${f.section}</td>
            <td class="fa-check fa-owner-col"><input type="checkbox" checked disabled title="Owner always has access"></td>
            ${cells}
        </tr>`;
    });
    body.innerHTML = rows || '<tr><td class="feature-access-loading">No features found.</td></tr>';
}

function filterFeatureAccess() {
    const q = (document.getElementById('feature-access-search').value || '').trim().toLowerCase();
    document.querySelectorAll('#feature-access-body .fa-row').forEach(row => {
        const hit = (row.getAttribute('data-label') || '').indexOf(q) !== -1;
        row.style.display = hit ? '' : 'none';
    });
}

async function saveFeatureAccess() {
    const btn = document.getElementById('feature-access-save-btn');
    const byHref = {};
    document.querySelectorAll('#feature-access-body input[type="checkbox"][data-href]').forEach(cb => {
        if (cb.disabled) return;
        const href = cb.getAttribute('data-href');
        if (!byHref[href]) byHref[href] = [];
        if (cb.checked) byHref[href].push(cb.getAttribute('data-role'));
    });
    const updates = Object.keys(byHref).map(href => ({ href, roles: byHref[href] }));
    if (btn) btn.disabled = true;
    _setFeatureStatus('Saving…');
    try {
        const res = await fetch('/api/admin/feature-access', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ updates }),
        });
        const data = await res.json();
        if (!res.ok || !data.success) {
            _setFeatureStatus((data && data.error) || 'Save failed.', true);
        } else {
            if (data.features) renderFeatureAccess(data.features);
            _setFeatureStatus(`Saved ${data.updated} feature(s).`);
        }
    } catch (e) {
        _setFeatureStatus('Network error while saving.', true);
    } finally {
        if (btn) btn.disabled = false;
    }
}

async function resetFeatureAccess() {
    if (!confirm('Reset all feature visibility to defaults? This clears every override.')) return;
    _setFeatureStatus('Resetting…');
    try {
        const res = await fetch('/api/admin/feature-access/reset', { method: 'POST' });
        const data = await res.json();
        if (!res.ok || !data.success) {
            _setFeatureStatus((data && data.error) || 'Reset failed.', true);
        } else {
            if (data.features) renderFeatureAccess(data.features);
            _setFeatureStatus('Restored defaults.');
        }
    } catch (e) {
        _setFeatureStatus('Network error while resetting.', true);
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

    card.classList.remove('running', 'done', 'error');
    if (running || stage === 'running') card.classList.add('running');
    else if (stage === 'error') card.classList.add('error');
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

async function loadAllUsers() {
    try {
        const response = await fetch('/api/admin/users');
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ error: 'Unknown error' }));
            throw new Error(errorData.error || `HTTP ${response.status}: ${response.statusText}`);
        }
        const data = await response.json();

        if (!data.success) {
            throw new Error(data.error || 'Failed to load users');
        }

        allUsers = data.users || [];
        filteredUsers = [...allUsers];
        usersPage = 1;
        displayUsers(filteredUsers);
        updateStats(allUsers);
    } catch (error) {
        console.error('Error loading users:', error);
        document.getElementById('users-table-body').innerHTML = `
            <tr><td colspan="8" style="text-align: center; color: #e74c3c;">
                Error loading users: ${error.message}
            </td></tr>
        `;
    }
}

function displayUsers(users) {
    const tbody = document.getElementById('users-table-body');

    if (!users || users.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" style="text-align: center;">No users found</td></tr>';
        renderPagination('users-pagination', 0, USERS_PAGE_SIZE, 1, 'goToUsersPage');
        return;
    }

    const start = (usersPage - 1) * USERS_PAGE_SIZE;
    const pageRows = users.slice(start, start + USERS_PAGE_SIZE);
    tbody.innerHTML = pageRows.map(user => `
        <tr>
            <td>${_escapeHtml(user.id)}</td>
            <td><strong>${_escapeHtml(user.username)}</strong></td>
            <td>${_escapeHtml(user.email)}</td>
            <td><span class="role-badge ${_escapeHtml(user.role)}">${_escapeHtml(user.role_label || ROLE_LABELS[user.role] || user.role)}</span></td>
            <td><span class="status-badge ${user.is_active ? 'active' : 'inactive'}">
                ${user.is_active ? 'Active' : 'Inactive'}
            </span></td>
            <td>${_escapeHtml(formatDate(user.created_at))}</td>
            <td>${_escapeHtml(user.last_activity || 'Never')}</td>
            <td>
                <div class="action-buttons">
                    <button class="action-btn reset" onclick="resetUserPassword(${Number(user.id)})">
                        Reset Password
                    </button>
                    <button class="action-btn role" onclick="toggleRole(${Number(user.id)}, '${_escapeHtml(user.role)}')">
                        Change Role
                    </button>
                    <button class="action-btn status" onclick="toggleStatus(${Number(user.id)}, ${!!user.is_active})">
                        ${user.is_active ? 'Deactivate' : 'Activate'}
                    </button>
                    ${Number(user.id) === CURRENT_USER_ID
                        ? ''
                        : `<button class="action-btn delete" onclick="removeUser(${Number(user.id)})">Remove</button>`}
                </div>
            </td>
        </tr>
    `).join('');
    renderPagination('users-pagination', users.length, USERS_PAGE_SIZE, usersPage, 'goToUsersPage');
}

function updateStats(users) {
    const total = users.length;
    const active = users.filter(u => u.is_active).length;
    const admins = users.filter(u => u.role === 'admin').length;

    document.getElementById('total-users').textContent = total;
    document.getElementById('active-users').textContent = active;
    document.getElementById('admin-users').textContent = admins;
}

async function toggleRole(userId, currentRole) {
    const rolePrompt = `Enter role for this user:\n- admin (Owner)\n- user (User)\n- ran_config_user (RNC User)\n- noc_sys (NOC SYS)\nCurrent: ${currentRole}`;
    const newRole = (prompt(rolePrompt, currentRole) || '').trim();
    if (!newRole || newRole === currentRole) {
        return;
    }
    if (!['admin', 'user', 'ran_config_user', 'noc_sys'].includes(newRole)) {
        showNotification('Invalid role value', 'error');
        return;
    }

    try {
        const response = await fetch(`/api/admin/users/${userId}/role`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ role: newRole })
        });

        const data = await response.json();

        if (data.success) {
            showNotification('Role updated successfully', 'success');
            loadAllUsers();
        } else {
            showNotification(data.error || 'Failed to update role', 'error');
        }
    } catch (error) {
        showNotification('Error updating role', 'error');
    }
}

async function removeUser(userId) {
    const target = allUsers.find(u => Number(u.id) === Number(userId));
    const username = target?.username || `user #${userId}`;
    if (Number(userId) === CURRENT_USER_ID) {
        showNotification('You cannot delete your own account', 'error');
        return;
    }
    if (!confirm(`Permanently remove ${username}? This cannot be undone.`)) {
        return;
    }

    try {
        const response = await fetch(`/api/admin/users/${userId}`, {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
        });
        const data = await response.json();
        if (!response.ok || !data.success) {
            showNotification(data.error || 'Failed to remove user', 'error');
            return;
        }
        showNotification(data.message || `User ${username} removed`, 'success');
        loadAllUsers();
    } catch (error) {
        showNotification('Error removing user', 'error');
    }
}

async function toggleStatus(userId, currentStatus) {
    const newStatus = !currentStatus;

    if (!confirm(`${newStatus ? 'Activate' : 'Deactivate'} this user?`)) {
        return;
    }

    try {
        const response = await fetch(`/api/admin/users/${userId}/status`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ is_active: newStatus })
        });

        const data = await response.json();

        if (data.success) {
            showNotification('Status updated successfully', 'success');
            loadAllUsers();
        } else {
            showNotification(data.error || 'Failed to update status', 'error');
        }
    } catch (error) {
        showNotification('Error updating status', 'error');
    }
}

function toggleAddUserPanel(forceOpen) {
    const panel = document.getElementById('add-user-panel');
    if (!panel) return;
    const show = typeof forceOpen === 'boolean' ? forceOpen : panel.hidden;
    panel.hidden = !show;
    if (show) {
        document.getElementById('new-user-username')?.focus();
    }
}

function toggleCustomPasswordField() {
    const useDefault = document.getElementById('new-user-default-password')?.checked;
    const wrap = document.getElementById('new-user-password-wrap');
    const input = document.getElementById('new-user-password');
    if (!wrap || !input) return;
    wrap.hidden = !!useDefault;
    input.required = !useDefault;
    if (useDefault) input.value = '';
}

async function submitAddUser(event) {
    event.preventDefault();
    const username = (document.getElementById('new-user-username')?.value || '').trim();
    const email = (document.getElementById('new-user-email')?.value || '').trim();
    const full_name = (document.getElementById('new-user-full-name')?.value || '').trim();
    const role = (document.getElementById('new-user-role')?.value || 'user').trim();
    const use_default_password = !!document.getElementById('new-user-default-password')?.checked;
    const password = (document.getElementById('new-user-password')?.value || '').trim();

    if (!username || !email) {
        showNotification('Username and email are required', 'error');
        return;
    }

    try {
        const response = await fetch('/api/admin/users', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                username,
                email,
                full_name,
                role,
                use_default_password,
                password: use_default_password ? undefined : password,
            }),
        });
        const data = await response.json();
        if (!response.ok || !data.success) {
            showNotification(data.error || 'Failed to create user', 'error');
            return;
        }

        showNotification(
            use_default_password
                ? `User created with default password (${DEFAULT_USER_PASSWORD})`
                : 'User created successfully',
            'success',
        );
        document.getElementById('add-user-form')?.reset();
        document.getElementById('new-user-default-password').checked = true;
        toggleCustomPasswordField();
        toggleAddUserPanel(false);
        loadAllUsers();
    } catch (error) {
        showNotification('Error creating user', 'error');
    }
}

async function resetUserPassword(userId) {
    const target = allUsers.find(u => Number(u.id) === Number(userId));
    const username = target?.username || `user #${userId}`;
    if (!confirm(`Reset password for ${username} to the default (${DEFAULT_USER_PASSWORD})?`)) {
        return;
    }

    try {
        const response = await fetch(`/api/admin/users/${userId}/reset-password`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
        });
        const data = await response.json();
        if (!response.ok || !data.success) {
            showNotification(data.error || 'Failed to reset password', 'error');
            return;
        }
        showNotification(`Password reset to default for ${username}`, 'success');
    } catch (error) {
        showNotification('Error resetting password', 'error');
    }
}

function searchUsers() {
    const searchTerm = document.getElementById('user-search').value.toLowerCase();
    filterUsers();
}

function filterUsers() {
    const searchTerm = document.getElementById('user-search').value.toLowerCase();
    const roleFilter = document.getElementById('role-filter').value;
    const statusFilter = document.getElementById('status-filter').value;

    filteredUsers = allUsers.filter(user => {
        const matchesSearch = !searchTerm ||
            user.username.toLowerCase().includes(searchTerm) ||
            user.email.toLowerCase().includes(searchTerm);

        const matchesRole = !roleFilter || user.role === roleFilter;

        const matchesStatus = !statusFilter ||
            (statusFilter === '1' && user.is_active) ||
            (statusFilter === '0' && !user.is_active);

        return matchesSearch && matchesRole && matchesStatus;
    });

    usersPage = 1;
    displayUsers(filteredUsers);
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

function goToUsersPage(page) {
    usersPage = Math.max(1, page);
    displayUsers(filteredUsers);
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
