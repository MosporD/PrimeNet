/**
 * Admin Panel Page JavaScript
 */

let allUsers = [];

document.addEventListener('DOMContentLoaded', () => {
    loadAllUsers();
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
