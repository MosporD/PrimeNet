/**
 * Admin Panel Page JavaScript
 */

let allUsers = [];

document.addEventListener('DOMContentLoaded', () => {
    loadAllUsers();
    loadSyncStatus();
    loadSyncHistory();
});

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

        allUsers = data.users;
        displayUsers(allUsers);
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
        return;
    }

    tbody.innerHTML = users.map(user => `
        <tr>
            <td>${user.id}</td>
            <td><strong>${user.username}</strong></td>
            <td>${user.email}</td>
            <td><span class="role-badge ${user.role}">${user.role}</span></td>
            <td><span class="status-badge ${user.is_active ? 'active' : 'inactive'}">
                ${user.is_active ? 'Active' : 'Inactive'}
            </span></td>
            <td>${formatDate(user.created_at)}</td>
            <td>${user.last_activity || 'Never'}</td>
            <td>
                <div class="action-buttons">
                    <button class="action-btn role" onclick="toggleRole(${user.id}, '${user.role}')">
                        ${user.role === 'admin' ? 'Make User' : 'Make Admin'}
                    </button>
                    <button class="action-btn status" onclick="toggleStatus(${user.id}, ${user.is_active})">
                        ${user.is_active ? 'Deactivate' : 'Activate'}
                    </button>
                </div>
            </td>
        </tr>
    `).join('');
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
    const newRole = currentRole === 'admin' ? 'user' : 'admin';

    if (!confirm(`Change user role to ${newRole}?`)) {
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

function searchUsers() {
    const searchTerm = document.getElementById('user-search').value.toLowerCase();
    filterUsers();
}

function filterUsers() {
    const searchTerm = document.getElementById('user-search').value.toLowerCase();
    const roleFilter = document.getElementById('role-filter').value;
    const statusFilter = document.getElementById('status-filter').value;

    const filtered = allUsers.filter(user => {
        const matchesSearch = !searchTerm ||
            user.username.toLowerCase().includes(searchTerm) ||
            user.email.toLowerCase().includes(searchTerm);

        const matchesRole = !roleFilter || user.role === roleFilter;

        const matchesStatus = !statusFilter ||
            (statusFilter === '1' && user.is_active) ||
            (statusFilter === '0' && !user.is_active);

        return matchesSearch && matchesRole && matchesStatus;
    });

    displayUsers(filtered);
}

function formatDate(dateString) {
    if (!dateString) return 'N/A';
    const date = new Date(dateString);
    return date.toLocaleDateString() + ' ' + date.toLocaleTimeString();
}

// ── Sync section ──────────────────────────────────────────────────────────

function showSyncMsg(text, type) {
    const el = document.getElementById('sync-msg');
    el.textContent = text;
    el.className = 'sync-msg ' + type;
    el.style.display = 'block';
    setTimeout(() => { el.style.display = 'none'; }, 6000);
}

function renderSyncRows(rows, tbodyId) {
    const tbody = document.getElementById(tbodyId);
    if (!rows || rows.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;">No data</td></tr>';
        return;
    }
    tbody.innerHTML = rows.map(r => `
        <tr>
            <td>${r.sync_type || ''}</td>
            <td>${r.technology || ''}</td>
            <td><span class="sync-badge ${r.status}">${r.status}</span></td>
            <td>${r.rows_affected != null ? r.rows_affected : '-'}</td>
            <td style="max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"
                title="${r.message || ''}">${r.message || '-'}</td>
            <td>${r.started_at || '-'}</td>
        </tr>
    `).join('');
}

async function loadSyncStatus() {
    try {
        const res  = await fetch('/api/sync/status');
        const data = await res.json();
        if (data.success) renderSyncRows(data.last_syncs, 'sync-status-body');
    } catch (e) {
        document.getElementById('sync-status-body').innerHTML =
            `<tr><td colspan="6" style="color:#e74c3c;text-align:center;">Error: ${e.message}</td></tr>`;
    }
}

async function loadSyncHistory() {
    try {
        const res  = await fetch('/api/sync/history?limit=20');
        const data = await res.json();
        if (data.success) renderSyncRows(data.history, 'sync-history-body');
    } catch (e) {
        document.getElementById('sync-history-body').innerHTML =
            `<tr><td colspan="6" style="color:#e74c3c;text-align:center;">Error: ${e.message}</td></tr>`;
    }
}

async function triggerSync(type) {
    // type: 'nokia_pm' | 'huawei_pm' | 'metadata'
    const endpointMap = {
        nokia_pm:  '/api/sync/trigger/pm',      // triggers both nokia
        huawei_pm: '/api/sync/trigger/pm',      // same endpoint triggers both Nokia+Huawei
        metadata:  '/api/sync/trigger/metadata',
    };

    // Nokia and Huawei share the /trigger/pm endpoint; use dedicated ones if available
    const endpoint = type === 'metadata'
        ? '/api/sync/trigger/metadata'
        : '/api/sync/trigger/pm';

    showSyncMsg(`Triggering ${type.replace('_', ' ')} sync…`, 'info');

    try {
        const res  = await fetch(endpoint, { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            showSyncMsg(data.message || 'Sync started in background.', 'success');
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

async function inspectLocal() {
    const pre = document.getElementById('inspect-output');
    pre.style.display = 'block';
    pre.textContent = 'Reading locally downloaded files…';
    try {
        const res  = await fetch('/api/sync/inspect_local');
        const data = await res.json();
        if (!data.success) { pre.textContent = 'Error: ' + (data.error || 'unknown'); return; }

        const lines = [];
        for (const [source, info] of Object.entries(data.report)) {
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
            // Nokia PM — flat columns array
            if (info.columns) {
                lines.push(`  File: ${info.file}`);
                lines.push(`  Detected tech: ${info.detected_tech || 'unknown'}`);
                lines.push(`  Columns (${info.columns.length}):`);
                info.columns.forEach(c => lines.push(`    • ${c}`));
                if (typeof info.mapping_check === 'object') {
                    lines.push(`  Mapping check (configured source → found?):`);
                    for (const [src, status] of Object.entries(info.mapping_check))
                        lines.push(`    ${status === 'ok' ? '✓' : '✗ MISSING'} "${src}"`);
                }
            }
            // Huawei PM — sheets
            if (info.sheets) {
                lines.push(`  File: ${info.file}`);
                for (const [tech, sr] of Object.entries(info.sheets)) {
                    lines.push(`  Sheet [${tech}] → "${sr.sheet}": ${sr.found ? 'found' : 'NOT FOUND'}`);
                    if (sr.found) {
                        lines.push(`    Columns: ${sr.columns.join(', ')}`);
                        if (sr.mapping_check)
                            for (const [src, status] of Object.entries(sr.mapping_check))
                                lines.push(`    ${status === 'ok' ? '✓' : '✗ MISSING'} "${src}"`);
                    } else if (sr.available_sheets) {
                        lines.push(`    Available sheets: ${sr.available_sheets.join(', ')}`);
                    }
                }
            }
            // Metadata
            if (info.files) {
                for (const [tech, fr] of Object.entries(info.files)) {
                    lines.push(`  [${tech}] ${fr.file}`);
                    if (Array.isArray(fr.columns)) {
                        lines.push(`    Columns: ${fr.columns.join(', ')}`);
                        if (typeof fr.mapping_check === 'object')
                            for (const [src, status] of Object.entries(fr.mapping_check))
                                lines.push(`    ${status === 'ok' ? '✓' : '✗ MISSING'} "${src}"`);
                    } else {
                        lines.push(`    ${fr.mapping_check || fr.columns}`);
                    }
                }
            }
        }
        pre.textContent = lines.join('\n');
    } catch (e) {
        pre.textContent = 'Error: ' + e.message;
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
