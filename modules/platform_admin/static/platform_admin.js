/**
 * NexusCore Platform Admin — users + module access.
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
const CAN_MANAGE_ACCESS = document.body?.dataset?.canManageAccess === "1";

let featureAccessLoaded = false;
let featureAccessRoles = [];

document.addEventListener("DOMContentLoaded", () => {
    const sectionFromUrl = new URLSearchParams(window.location.search).get("section");
    const defaultPage = sectionFromUrl || "user-admin";
    openAdminPage(defaultPage);
    loadAllUsers();
});

function openAdminPage(pageName) {
    if (pageName === "feature-access" && !CAN_MANAGE_ACCESS) {
        pageName = "user-admin";
    }
    document.querySelectorAll(".admin-page-tab").forEach((tab) => {
        tab.classList.toggle("active", tab.getAttribute("data-page") === pageName);
    });
    document.querySelectorAll(".admin-page-panel").forEach((panel) => {
        panel.classList.toggle("active", panel.getAttribute("data-page") === pageName);
    });
    if (pageName === "feature-access" && !featureAccessLoaded) {
        loadFeatureAccess();
    }
}

function _setFeatureStatus(msg, isError) {
    const el = document.getElementById("feature-access-status");
    if (!el) return;
    el.textContent = msg || "";
    el.classList.toggle("is-error", !!isError);
}

async function loadFeatureAccess() {
    try {
        const res = await fetch(`${API}/feature-access`);
        const data = await res.json();
        if (!res.ok || !data.success) {
            _setFeatureStatus((data && data.error) || "Failed to load.", true);
            return;
        }
        featureAccessRoles = data.editable_roles || [];
        renderFeatureAccess(data.features || []);
        featureAccessLoaded = true;
        _setFeatureStatus("");
    } catch (e) {
        _setFeatureStatus("Network error loading feature access.", true);
    }
}

function renderFeatureAccess(features) {
    const head = document.getElementById("feature-access-head");
    const body = document.getElementById("feature-access-body");
    if (!head || !body) return;

    let headHtml = '<tr><th>Feature</th><th>Section</th><th class="fa-owner-col">Owner</th>';
    featureAccessRoles.forEach((r) => {
        headHtml += `<th>${r.label}</th>`;
    });
    headHtml += "</tr>";
    head.innerHTML = headHtml;

    let rows = "";
    features.forEach((f) => {
        const enabled = new Set(f.roles || []);
        let cells = "";
        featureAccessRoles.forEach((r) => {
            const checked = enabled.has(r.key) ? "checked" : "";
            const dis = f.locked ? "disabled" : "";
            cells += `<td class="fa-check"><input type="checkbox" data-href="${f.href}" data-role="${r.key}" ${checked} ${dis}></td>`;
        });
        const lockBadge = f.locked
            ? ' <span class="fa-lock" title="Core feature — cannot be restricted">🔒</span>'
            : "";
        rows += `<tr class="fa-row" data-label="${(f.label + " " + f.href).toLowerCase()}">
            <td class="fa-name">${f.label}${lockBadge}<span class="fa-href">${f.href}</span></td>
            <td class="fa-section">${f.section}</td>
            <td class="fa-check fa-owner-col"><input type="checkbox" checked disabled title="Owner always has access"></td>
            ${cells}
        </tr>`;
    });
    body.innerHTML = rows || '<tr><td class="feature-access-loading">No features found.</td></tr>';
}

function filterFeatureAccess() {
    const q = (document.getElementById("feature-access-search").value || "").trim().toLowerCase();
    document.querySelectorAll("#feature-access-body .fa-row").forEach((row) => {
        const hit = (row.getAttribute("data-label") || "").indexOf(q) !== -1;
        row.style.display = hit ? "" : "none";
    });
}

async function saveFeatureAccess() {
    const btn = document.getElementById("feature-access-save-btn");
    const byHref = {};
    document.querySelectorAll('#feature-access-body input[type="checkbox"][data-href]').forEach((cb) => {
        if (cb.disabled) return;
        const href = cb.getAttribute("data-href");
        if (!byHref[href]) byHref[href] = [];
        if (cb.checked) byHref[href].push(cb.getAttribute("data-role"));
    });
    const updates = Object.keys(byHref).map((href) => ({ href, roles: byHref[href] }));
    if (btn) btn.disabled = true;
    _setFeatureStatus("Saving…");
    try {
        const res = await fetch(`${API}/feature-access`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ updates }),
        });
        const data = await res.json();
        if (!res.ok || !data.success) {
            _setFeatureStatus((data && data.error) || "Save failed.", true);
        } else {
            if (data.features) renderFeatureAccess(data.features);
            _setFeatureStatus(`Saved ${data.updated} feature(s).`);
        }
    } catch (e) {
        _setFeatureStatus("Network error while saving.", true);
    } finally {
        if (btn) btn.disabled = false;
    }
}

async function resetFeatureAccess() {
    if (!confirm("Reset all feature visibility to defaults? This clears every override.")) return;
    _setFeatureStatus("Resetting…");
    try {
        const res = await fetch(`${API}/feature-access/reset`, { method: "POST" });
        const data = await res.json();
        if (!res.ok || !data.success) {
            _setFeatureStatus((data && data.error) || "Reset failed.", true);
        } else {
            if (data.features) renderFeatureAccess(data.features);
            _setFeatureStatus("Restored defaults.");
        }
    } catch (e) {
        _setFeatureStatus("Network error while resetting.", true);
    }
}

async function loadAllUsers() {
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
    } catch (error) {
        console.error("Error loading users:", error);
        document.getElementById("users-table-body").innerHTML = `
            <tr><td colspan="9" style="text-align: center; color: #e74c3c;">
                Error loading users: ${_escapeHtml(error.message)}
            </td></tr>
        `;
    }
}

function displayUsers(users) {
    const tbody = document.getElementById("users-table-body");

    if (!users || users.length === 0) {
        tbody.innerHTML = '<tr><td colspan="9" style="text-align: center;">No users found</td></tr>';
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
