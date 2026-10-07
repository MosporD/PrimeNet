/**
 * NexusCore Platform Admin — users + platform (portal) access.
 */

const API = "/api/platform-admin";

let allUsers = [];
let filteredUsers = [];
let portalCatalog = [
    { key: "primenet", label: "Engineering (PrimeNet)", live: true },
    { key: "nexpulse", label: "Marketing (NexPulse)", live: true },
    { key: "sales", label: "Sales (NexArpu)", live: false },
    { key: "support", label: "Support (NexResolve)", live: false },
];
let usersPage = 1;
const USERS_PAGE_SIZE = 12;
const ROLE_LABELS = {
    admin: "Owner",
    user: "User",
    ran_config_user: "RNC User",
    noc_sys: "NOC SYS",
};
const DEFAULT_USER_PASSWORD =
    document.getElementById("default-user-password-label")?.textContent?.trim() || "Zain@1234";
const CURRENT_USER_ID = Number(document.body?.dataset?.currentUserId || 0);
document.addEventListener("DOMContentLoaded", () => {
    const sectionFromUrl = new URLSearchParams(window.location.search).get("section");
    let defaultPage = sectionFromUrl || "user-admin";
    if (defaultPage === "feature-access") {
        defaultPage = "platform-access";
    }
    openAdminPage(defaultPage);
    loadAllUsers();
});

function openAdminPage(pageName) {
    document.querySelectorAll(".admin-page-tab").forEach((tab) => {
        tab.classList.toggle("active", tab.getAttribute("data-page") === pageName);
    });
    document.querySelectorAll(".admin-page-panel").forEach((panel) => {
        panel.classList.toggle("active", panel.getAttribute("data-page") === pageName);
    });
    try {
        const url = new URL(window.location.href);
        url.searchParams.set("section", pageName);
        window.history.replaceState({}, "", url);
    } catch (_) { /* ignore */ }
    if (pageName === "platform-access") {
        renderPlatformAccessUsers();
        if (!allUsers.length) {
            loadAllUsers();
        }
    }
}

function _setPlatformAccessStatus(msg, isError) {
    const el = document.getElementById("platform-access-status");
    if (!el) return;
    el.textContent = msg || "";
    el.classList.toggle("is-error", !!isError);
}

function filterPlatformAccessUsers() {
    renderPlatformAccessUsers();
}

function renderPlatformAccessUsers() {
    const head = document.getElementById("platform-access-head");
    const body = document.getElementById("platform-access-body");
    if (!head || !body) return;

    const portals = portalCatalog || [];
    let headHtml = "<tr><th>Username</th><th>Role</th><th>Status</th>";
    portals.forEach((p) => {
        const planned = p.live ? "" : ' <span class="fa-href">(planned)</span>';
        headHtml += `<th title="${_escapeHtml(p.key)}">${_escapeHtml(p.label)}${planned}</th>`;
    });
    headHtml += "</tr>";
    head.innerHTML = headHtml;

    const q = (document.getElementById("platform-access-search")?.value || "").trim().toLowerCase();
    const users = (allUsers || []).filter((u) => {
        if (!q) return true;
        return (
            String(u.username || "").toLowerCase().includes(q) ||
            String(u.email || "").toLowerCase().includes(q)
        );
    });

    if (!users.length) {
        body.innerHTML = `<tr><td colspan="${3 + portals.length}" style="text-align:center;">No users found</td></tr>`;
        return;
    }

    body.innerHTML = users
        .map((user) => {
            const isOwner = user.role === "admin";
            const allowed = new Set(user.allowed_portals || []);
            const cells = portals
                .map((p) => {
                    const checked = isOwner || allowed.has(p.key) ? "checked" : "";
                    const disabled = isOwner ? "disabled" : "";
                    return `<td class="fa-check">
                        <input type="checkbox" ${checked} ${disabled}
                            title="${_escapeHtml(p.label)}"
                            onchange="toggleUserPortal(${Number(user.id)}, '${_escapeHtml(p.key)}', this.checked)">
                    </td>`;
                })
                .join("");
            return `<tr>
                <td><strong>${_escapeHtml(user.username)}</strong><div class="fa-href">${_escapeHtml(user.email || "")}</div></td>
                <td><span class="role-badge ${_escapeHtml(user.role)}">${_escapeHtml(user.role_label || ROLE_LABELS[user.role] || user.role)}</span></td>
                <td><span class="status-badge ${user.is_active ? "active" : "inactive"}">${user.is_active ? "Active" : "Inactive"}</span></td>
                ${cells}
            </tr>`;
        })
        .join("");
}

async function toggleUserPortal(userId, portalKey, enabled) {
    const user = allUsers.find((u) => Number(u.id) === Number(userId));
    if (!user || user.role === "admin") {
        renderPlatformAccessUsers();
        return;
    }
    const current = new Set(user.allowed_portals || []);
    if (enabled) current.add(portalKey);
    else current.delete(portalKey);
    if (!current.size) {
        showNotification("Keep at least one portal", "error");
        renderPlatformAccessUsers();
        return;
    }
    _setPlatformAccessStatus("Saving…");
    try {
        const response = await fetch(`${API}/users/${userId}/portals`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ allowed_portals: Array.from(current) }),
        });
        const data = await response.json();
        if (!response.ok || !data.success) {
            _setPlatformAccessStatus(data.error || "Save failed", true);
            showNotification(data.error || "Failed to update portals", "error");
            loadAllUsers();
            return;
        }
        user.allowed_portals = Array.from(current);
        user.portal_labels = (portalCatalog || [])
            .filter((p) => current.has(p.key))
            .map((p) => p.label);
        _setPlatformAccessStatus("Saved");
        renderPlatformAccessUsers();
        if (document.querySelector('.admin-page-panel[data-page="user-admin"].active')) {
            displayUsers(filteredUsers);
        }
    } catch (error) {
        _setPlatformAccessStatus("Network error", true);
        showNotification("Error updating portals", "error");
        loadAllUsers();
    }
}

async function loadAllUsers() {
    const platformBody = document.getElementById("platform-access-body");
    if (platformBody && !allUsers.length) {
        platformBody.innerHTML = '<tr><td style="text-align:center;">Loading…</td></tr>';
    }
    try {
        const response = await fetch(`${API}/users`);
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ error: "Unknown error" }));
            throw new Error(errorData.error || `HTTP ${response.status}: ${response.statusText}`);
        }
        const data = await response.json();
        if (!data.success) throw new Error(data.error || "Failed to load users");

        allUsers = data.users || [];
        portalCatalog = data.portal_catalog || portalCatalog;
        filteredUsers = [...allUsers];
        usersPage = 1;
        displayUsers(filteredUsers);
        updateStats(allUsers);
        renderPlatformAccessUsers();
        _setPlatformAccessStatus(`${allUsers.length} user(s)`);
    } catch (error) {
        console.error("Error loading users:", error);
        const usersBody = document.getElementById("users-table-body");
        if (usersBody) {
            usersBody.innerHTML = `
            <tr><td colspan="9" style="text-align: center; color: #e74c3c;">
                Error loading users: ${_escapeHtml(error.message)}
            </td></tr>
        `;
        }
        if (platformBody) {
            platformBody.innerHTML = `
            <tr><td style="text-align:center; color:#e74c3c;">
                Error loading users: ${_escapeHtml(error.message)}
            </td></tr>`;
        }
        _setPlatformAccessStatus(error.message || "Failed to load", true);
    }
}

function displayUsers(users) {
    const tbody = document.getElementById("users-table-body");

    if (!users || users.length === 0) {
        tbody.innerHTML = '<tr><td colspan="10" style="text-align: center;">No users found</td></tr>';
        renderPagination("users-pagination", 0, USERS_PAGE_SIZE, 1, "goToUsersPage");
        return;
    }

    const start = (usersPage - 1) * USERS_PAGE_SIZE;
    const pageRows = users.slice(start, start + USERS_PAGE_SIZE);
    tbody.innerHTML = pageRows
        .map(
            (user) => `
        <tr>
            <td>${_escapeHtml(user.id)}</td>
            <td><strong>${_escapeHtml(user.username)}</strong></td>
            <td>${_escapeHtml(user.email)}</td>
            <td><span class="role-badge ${_escapeHtml(user.role)}">${_escapeHtml(user.role_label || ROLE_LABELS[user.role] || user.role)}</span></td>
            <td class="portal-cell">${_escapeHtml((user.portal_labels || user.allowed_portals || []).join(", ") || "—")}</td>
            <td><span class="status-badge ${user.is_active ? "active" : "inactive"}">
                ${user.is_active ? "Active" : "Inactive"}
            </span></td>
            <td>${_escapeHtml(formatDate(user.created_at))}</td>
            <td>${_escapeHtml(user.last_activity || "Never")}</td>
            <td>
                <div class="action-buttons">
                    <button class="action-btn reset" onclick="resetUserPassword(${Number(user.id)})">Reset Password</button>
                    <button class="action-btn role" onclick="toggleRole(${Number(user.id)}, '${_escapeHtml(user.role)}')">Change Role</button>
                    <button class="action-btn portals" onclick="editUserPortals(${Number(user.id)}, '${_escapeHtml((user.allowed_portals || []).join(","))}')">Portals</button>
                    <button class="action-btn status" onclick="toggleStatus(${Number(user.id)}, ${!!user.is_active})">
                        ${user.is_active ? "Deactivate" : "Activate"}
                    </button>
                    ${
                        Number(user.id) === CURRENT_USER_ID
                            ? ""
                            : `<button class="action-btn delete" onclick="removeUser(${Number(user.id)})">Remove</button>`
                    }
                </div>
            </td>
        </tr>
    `
        )
        .join("");
    renderPagination("users-pagination", users.length, USERS_PAGE_SIZE, usersPage, "goToUsersPage");
}

function updateStats(users) {
    document.getElementById("total-users").textContent = users.length;
    document.getElementById("active-users").textContent = users.filter((u) => u.is_active).length;
    document.getElementById("admin-users").textContent = users.filter((u) => u.role === "admin").length;
}

async function toggleRole(userId, currentRole) {
    const rolePrompt = `Enter role for this user:\n- admin (Owner)\n- user (User)\n- ran_config_user (RNC User)\n- noc_sys (NOC SYS)\nCurrent: ${currentRole}`;
    const newRole = (prompt(rolePrompt, currentRole) || "").trim();
    if (!newRole || newRole === currentRole) return;
    if (!["admin", "user", "ran_config_user", "noc_sys"].includes(newRole)) {
        showNotification("Invalid role value", "error");
        return;
    }
    try {
        const response = await fetch(`${API}/users/${userId}/role`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ role: newRole }),
        });
        const data = await response.json();
        if (data.success) {
            showNotification("Role updated successfully", "success");
            loadAllUsers();
        } else {
            showNotification(data.error || "Failed to update role", "error");
        }
    } catch (error) {
        showNotification("Error updating role", "error");
    }
}

async function editUserPortals(userId, currentCsv) {
    const current = new Set(
        String(currentCsv || "")
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean)
    );
    const lines = (portalCatalog || []).map((p) => {
        const mark = current.has(p.key) ? "x" : " ";
        return `[${mark}] ${p.key} — ${p.label}${p.live ? "" : " (soon)"}`;
    });
    const promptText =
        "Enter portal keys separated by commas.\n" +
        "Keys: primenet, nexpulse, sales, support\n\n" +
        lines.join("\n") +
        `\n\nCurrent: ${currentCsv || "(none)"}`;
    const raw = prompt(promptText, currentCsv || "primenet");
    if (raw === null) return;
    const portals = raw
        .split(/[,;\s]+/)
        .map((s) => s.trim().toLowerCase())
        .filter(Boolean);
    if (!portals.length) {
        showNotification("Select at least one portal", "error");
        return;
    }
    try {
        const response = await fetch(`${API}/users/${userId}/portals`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ allowed_portals: portals }),
        });
        const data = await response.json();
        if (response.ok && data.success) {
            showNotification(data.message || "Portal access updated", "success");
            loadAllUsers();
        } else {
            showNotification(data.error || "Failed to update portals", "error");
        }
    } catch (error) {
        showNotification("Error updating portals", "error");
    }
}

async function removeUser(userId) {
    const target = allUsers.find((u) => Number(u.id) === Number(userId));
    const username = target?.username || `user #${userId}`;
    if (Number(userId) === CURRENT_USER_ID) {
        showNotification("You cannot delete your own account", "error");
        return;
    }
    if (!confirm(`Permanently remove ${username}? This cannot be undone.`)) return;

    try {
        const response = await fetch(`${API}/users/${userId}`, {
            method: "DELETE",
            headers: { "Content-Type": "application/json" },
        });
        const data = await response.json();
        if (!response.ok || !data.success) {
            showNotification(data.error || "Failed to remove user", "error");
            return;
        }
        showNotification(data.message || `User ${username} removed`, "success");
        loadAllUsers();
    } catch (error) {
        showNotification("Error removing user", "error");
    }
}

async function toggleStatus(userId, currentStatus) {
    const newStatus = !currentStatus;
    if (!confirm(`${newStatus ? "Activate" : "Deactivate"} this user?`)) return;

    try {
        const response = await fetch(`${API}/users/${userId}/status`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ is_active: newStatus }),
        });
        const data = await response.json();
        if (data.success) {
            showNotification("Status updated successfully", "success");
            loadAllUsers();
        } else {
            showNotification(data.error || "Failed to update status", "error");
        }
    } catch (error) {
        showNotification("Error updating status", "error");
    }
}

function toggleAddUserPanel(forceOpen) {
    const panel = document.getElementById("add-user-panel");
    if (!panel) return;
    const show = typeof forceOpen === "boolean" ? forceOpen : panel.hidden;
    panel.hidden = !show;
    if (show) document.getElementById("new-user-username")?.focus();
}

function toggleCustomPasswordField() {
    const useDefault = document.getElementById("new-user-default-password")?.checked;
    const wrap = document.getElementById("new-user-password-wrap");
    const input = document.getElementById("new-user-password");
    if (!wrap || !input) return;
    wrap.hidden = !!useDefault;
    input.required = !useDefault;
    if (useDefault) input.value = "";
}

async function submitAddUser(event) {
    event.preventDefault();
    const username = (document.getElementById("new-user-username")?.value || "").trim();
    const email = (document.getElementById("new-user-email")?.value || "").trim();
    const full_name = (document.getElementById("new-user-full-name")?.value || "").trim();
    const role = (document.getElementById("new-user-role")?.value || "user").trim();
    const use_default_password = !!document.getElementById("new-user-default-password")?.checked;
    const password = (document.getElementById("new-user-password")?.value || "").trim();
    const allowed_portals = Array.from(
        document.querySelectorAll('input[name="new-user-portal"]:checked')
    ).map((el) => el.value);

    if (!username || !email) {
        showNotification("Username and email are required", "error");
        return;
    }
    if (!allowed_portals.length) {
        showNotification("Select at least one portal", "error");
        return;
    }

    try {
        const response = await fetch(`${API}/users`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                username,
                email,
                full_name,
                role,
                use_default_password,
                password: use_default_password ? undefined : password,
                allowed_portals,
            }),
        });
        const data = await response.json();
        if (!response.ok || !data.success) {
            showNotification(data.error || "Failed to create user", "error");
            return;
        }
        showNotification(
            use_default_password
                ? `User created with default password (${DEFAULT_USER_PASSWORD})`
                : "User created successfully",
            "success"
        );
        document.getElementById("add-user-form")?.reset();
        document.getElementById("new-user-default-password").checked = true;
        toggleCustomPasswordField();
        toggleAddUserPanel(false);
        loadAllUsers();
    } catch (error) {
        showNotification("Error creating user", "error");
    }
}

async function resetUserPassword(userId) {
    const target = allUsers.find((u) => Number(u.id) === Number(userId));
    const username = target?.username || `user #${userId}`;
    if (!confirm(`Reset password for ${username} to the default (${DEFAULT_USER_PASSWORD})?`)) return;

    try {
        const response = await fetch(`${API}/users/${userId}/reset-password`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
        });
        const data = await response.json();
        if (!response.ok || !data.success) {
            showNotification(data.error || "Failed to reset password", "error");
            return;
        }
        showNotification(`Password reset to default for ${username}`, "success");
    } catch (error) {
        showNotification("Error resetting password", "error");
    }
}

function searchUsers() {
    filterUsers();
}

function filterUsers() {
    const searchTerm = document.getElementById("user-search").value.toLowerCase();
    const roleFilter = document.getElementById("role-filter").value;
    const statusFilter = document.getElementById("status-filter").value;

    filteredUsers = allUsers.filter((user) => {
        const matchesSearch =
            !searchTerm ||
            user.username.toLowerCase().includes(searchTerm) ||
            user.email.toLowerCase().includes(searchTerm);
        const matchesRole = !roleFilter || user.role === roleFilter;
        const matchesStatus =
            !statusFilter ||
            (statusFilter === "1" && user.is_active) ||
            (statusFilter === "0" && !user.is_active);
        return matchesSearch && matchesRole && matchesStatus;
    });
    usersPage = 1;
    displayUsers(filteredUsers);
}

function formatDate(dateString) {
    if (!dateString) return "N/A";
    const date = new Date(dateString);
    return date.toLocaleDateString() + " " + date.toLocaleTimeString();
}

function _escapeHtml(value) {
    return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function renderPagination(containerId, totalItems, pageSize, currentPage, callbackName) {
    const el = document.getElementById(containerId);
    if (!el) return;
    const totalPages = Math.max(1, Math.ceil(totalItems / pageSize));
    if (totalItems <= pageSize) {
        el.innerHTML = "";
        return;
    }
    const prevDisabled = currentPage <= 1 ? "disabled" : "";
    const nextDisabled = currentPage >= totalPages ? "disabled" : "";
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

async function exportUsersTable() {
    if (!filteredUsers.length) {
        showNotification("No users to export", "error");
        return;
    }
    const payload = {
        table: "users",
        report_title: "User Administration",
        sheet_title: "Users",
        filename_stem: "Platform_Users",
        columns: ["id", "username", "email", "role", "portals", "status", "created_at", "last_activity"],
        column_labels: {
            id: "ID",
            username: "Username",
            email: "Email",
            role: "Role",
            portals: "Portals",
            status: "Status",
            created_at: "Created",
            last_activity: "Last Activity",
        },
        rows: filteredUsers.map((user) => ({
            id: user.id,
            username: user.username,
            email: user.email,
            role: user.role_label || ROLE_LABELS[user.role] || user.role,
            portals: (user.portal_labels || user.allowed_portals || []).join(", "),
            status: user.is_active ? "Active" : "Inactive",
            created_at: formatDate(user.created_at),
            last_activity: user.last_activity || "Never",
        })),
        meta: {
            "Search Filter": document.getElementById("user-search")?.value?.trim() || "(none)",
            "Role Filter": document.getElementById("role-filter")?.value || "(all)",
            "Status Filter": document.getElementById("status-filter")?.value || "(all)",
        },
    };
    try {
        const response = await fetch(`${API}/export/excel`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            showNotification(err.error || "Export failed", "error");
            return;
        }
        const blob = await response.blob();
        const disposition = response.headers.get("Content-Disposition") || "";
        const match = /filename="?([^"]+)"?/.exec(disposition);
        const filename = match ? match[1] : `Platform_Users_${Date.now()}.xlsx`;
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
    } catch (e) {
        showNotification("Error exporting users", "error");
    }
}
