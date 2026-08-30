let _profileRole = '';

window.addEventListener('DOMContentLoaded', () => {
    maybeShowForcedPasswordNotice();
    loadProfile();
    loadPreferences();
    loadVendorCredentials();
    document.getElementById('newPassword').addEventListener('input', updateStrength);
});

function maybeShowForcedPasswordNotice() {
    const params = new URLSearchParams(window.location.search);
    if (params.get('force_password_change') === '1') {
        alert('Password change required: you must update your password now before using other modules.');
        const section = document.querySelector('.form-card:nth-of-type(2)');
        if (section) section.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
}

// ── Profile Load ──────────────────────────────────────────────────────────────
async function loadProfile() {
    const res  = await fetch('/api/profile');
    const data = await res.json();
    if (!data.success) return;

    const p = data.profile;
    _profileRole = String(p.role || '').toLowerCase();
    document.getElementById('fieldUsername').value   = p.username || '';
    document.getElementById('fieldFullName').value   = p.full_name || '';
    document.getElementById('fieldDepartment').value = p.department || '';
    document.getElementById('fieldEmail').value      = p.email || '';

    // Avatar
    const initial = (p.full_name || p.username || '?')[0].toUpperCase();
    document.getElementById('avatarCircle').textContent = initial;
    document.getElementById('avatarName').textContent   = p.full_name || p.username;
    document.getElementById('avatarRole').textContent   = p.role;
    document.getElementById('memberSince').textContent  = p.created_at ? p.created_at.slice(0, 10) : '—';
    document.getElementById('lastLogin').textContent    = p.last_login ? p.last_login.slice(0, 16) : '—';
    document.getElementById('activityCount').textContent = (p.activity_count || 0).toLocaleString();
    applyProfileEditPermissions();
}

function applyProfileEditPermissions() {
    const restricted = _profileRole === 'user' || _profileRole === 'ran_config_user';
    const fields = ['fieldUsername', 'fieldFullName', 'fieldDepartment', 'fieldEmail'];
    fields.forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.disabled = restricted;
    });
    const btn = document.querySelector('button[onclick="updateProfile()"]');
    if (btn) {
        btn.disabled = restricted;
        btn.title = restricted ? 'Profile editing is disabled for your role.' : '';
    }
    const el = document.getElementById('profileStatus');
    if (restricted && el && !el.textContent) {
        el.className = 'status-message';
        el.textContent = 'Profile updates are disabled for your role.';
    }
}

// ── Update Profile ────────────────────────────────────────────────────────────
async function updateProfile() {
    if (_profileRole === 'user' || _profileRole === 'ran_config_user') {
        const el = document.getElementById('profileStatus');
        if (el) {
            el.className = 'status-message error';
            el.textContent = 'Profile details update is disabled for your role.';
        }
        return;
    }
    const payload = {
        username:   document.getElementById('fieldUsername').value.trim(),
        full_name:  document.getElementById('fieldFullName').value.trim(),
        department: document.getElementById('fieldDepartment').value.trim(),
        email:      document.getElementById('fieldEmail').value.trim(),
    };
    const res  = await fetch('/api/profile/update', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    const data = await res.json();
    const el = document.getElementById('profileStatus');
    if (data.success) {
        el.className = 'status-message success';
        el.textContent = data.message;
        loadProfile();
    } else {
        el.className = 'status-message error';
        el.textContent = data.error || 'Update failed';
    }
}

async function submitPhotoRequest() {
    const fileInput = document.getElementById('profilePhotoFile');
    const statusEl = document.getElementById('photoStatus');
    const file = fileInput?.files?.[0];
    if (!file) {
        statusEl.className = 'status-message error';
        statusEl.textContent = 'Please choose a picture first.';
        return;
    }
    const fd = new FormData();
    fd.append('photo', file);
    try {
        const res = await fetch('/api/profile/photo-request', { method: 'POST', body: fd });
        const data = await res.json();
        if (!data.success) throw new Error(data.error || 'Upload failed');
        statusEl.className = 'status-message success';
        statusEl.textContent = data.message || 'Photo uploaded for approval.';
        fileInput.value = '';
    } catch (err) {
        statusEl.className = 'status-message error';
        statusEl.textContent = err.message || 'Upload failed';
    }
}

// ── Change Password ───────────────────────────────────────────────────────────
async function changePassword() {
    const payload = {
        current_password: document.getElementById('currentPassword').value,
        new_password:     document.getElementById('newPassword').value,
        confirm_password: document.getElementById('confirmPassword').value,
    };
    const res  = await fetch('/api/profile/change-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    const data = await res.json();
    const el = document.getElementById('passwordStatus');
    if (data.success) {
        el.className = 'status-message success';
        el.textContent = data.message;
        document.getElementById('currentPassword').value = '';
        document.getElementById('newPassword').value = '';
        document.getElementById('confirmPassword').value = '';
        updateStrength();
        const params = new URLSearchParams(window.location.search);
        if (params.get('force_password_change') === '1') {
            window.location.href = '/dashboard';
        }
    } else {
        el.className = 'status-message error';
        el.textContent = data.error || 'Password change failed';
    }
}

function updateStrength() {
    const pw    = document.getElementById('newPassword').value;
    const fill  = document.getElementById('strengthFill');
    const label = document.getElementById('strengthLabel');
    const score = calcStrength(pw);
    const pct   = (score / 5) * 100;
    const colors = ['#e74c3c', '#e67e22', '#f1c40f', '#2ecc71', '#27ae60'];
    const labels = ['Very Weak', 'Weak', 'Fair', 'Strong', 'Very Strong'];
    fill.style.width = pct + '%';
    fill.style.background = pw ? colors[score - 1] || colors[0] : '';
    label.textContent = pw ? labels[score - 1] || '' : '';
}

function calcStrength(pw) {
    if (!pw) return 0;
    let s = 0;
    if (pw.length >= 6)  s++;
    if (pw.length >= 10) s++;
    if (/[A-Z]/.test(pw)) s++;
    if (/[0-9]/.test(pw)) s++;
    if (/[^A-Za-z0-9]/.test(pw)) s++;
    return s;
}

// ── Preferences ───────────────────────────────────────────────────────────────
async function loadPreferences() {
    const res  = await fetch('/api/profile/preferences');
    const data = await res.json();
    if (!data.success) return;
    const prefs = data.preferences;

    if (prefs.default_tab)    document.getElementById('prefDefaultTab').value    = prefs.default_tab;
    if (prefs.default_tech)   document.getElementById('prefDefaultTech').value   = prefs.default_tech;
    if (prefs.default_vendor) document.getElementById('prefDefaultVendor').value = prefs.default_vendor;
    const layout = (prefs.dashboard_layout && typeof prefs.dashboard_layout === 'object')
        ? prefs.dashboard_layout
        : {};
    const showMap = document.getElementById('prefShowConstellation');
    if (showMap) showMap.checked = layout.show_constellation !== false;
    const pmView = String(prefs.pm_view_mode || '').toLowerCase();
    if (pmView === 'table' || pmView === 'charts') {
        document.getElementById('prefCompact').checked = pmView === 'table';
    } else if (typeof prefs.compact_tables === 'boolean') {
        // Backward compatibility with old key.
        document.getElementById('prefCompact').checked = prefs.compact_tables;
    }
}

async function savePreferences() {
    const payload = {
        default_tab:    document.getElementById('prefDefaultTab').value,
        default_tech:   document.getElementById('prefDefaultTech').value,
        default_vendor: document.getElementById('prefDefaultVendor').value,
        pm_view_mode:   document.getElementById('prefCompact').checked ? 'table' : 'charts',
        // Keep old key so existing integrations don't break.
        compact_tables: document.getElementById('prefCompact').checked,
        dashboard_layout: {
            show_constellation: document.getElementById('prefShowConstellation')
                ? document.getElementById('prefShowConstellation').checked
                : true,
        },
    };
    const res  = await fetch('/api/profile/preferences', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    const data = await res.json();
    const el = document.getElementById('prefStatus');
    if (data.success) {
        el.className = 'status-message success';
        el.textContent = '✓ Preferences saved';
        setTimeout(() => { el.className = 'status-message'; el.textContent = ''; }, 3000);
    } else {
        el.className = 'status-message error';
        el.textContent = data.error || 'Save failed';
    }
}

// ── Vendor credentials (RET management) ─────────────────────────────────────

function _vendorCredUi(vendor) {
    const label = vendor === 'nokia' ? 'MantaRay' : 'U2020';
    return {
        vendor,
        label,
        usernameId: `${vendor}CredUsername`,
        passwordId: `${vendor}CredPassword`,
        statusId: `${vendor}CredStatus`,
        messageId: `${vendor}CredMessage`,
    };
}

function applyVendorCredentialStatus(credentials) {
    ['nokia', 'huawei'].forEach((vendor) => {
        const ui = _vendorCredUi(vendor);
        const statusEl = document.getElementById(ui.statusId);
        const usernameEl = document.getElementById(ui.usernameId);
        const info = (credentials && credentials[vendor]) || {};
        if (usernameEl && info.configured && info.username) {
            usernameEl.value = info.username;
        }
        if (statusEl) {
            if (info.configured) {
                statusEl.textContent = `Configured (${info.username})`;
                statusEl.className = 'vendor-cred-pill configured';
            } else {
                statusEl.textContent = 'Not configured';
                statusEl.className = 'vendor-cred-pill';
            }
        }
    });
}

async function loadVendorCredentials() {
    if (!document.getElementById('nokiaCredUsername')) return;
    const res = await fetch('/api/profile/vendor-credentials');
    const data = await res.json();
    if (data.success) {
        applyVendorCredentialStatus(data.credentials);
    }
}

async function saveVendorCredentials(vendor) {
    const ui = _vendorCredUi(vendor);
    const username = document.getElementById(ui.usernameId).value.trim();
    const password = document.getElementById(ui.passwordId).value;
    const messageEl = document.getElementById(ui.messageId);
    if (!username) {
        messageEl.className = 'status-message error';
        messageEl.textContent = 'Username is required.';
        return;
    }
    if (!password) {
        messageEl.className = 'status-message error';
        messageEl.textContent = 'Enter your password to save credentials.';
        return;
    }
    const res = await fetch('/api/profile/vendor-credentials', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ vendor, username, password }),
    });
    const data = await res.json();
    if (data.success) {
        messageEl.className = 'status-message success';
        messageEl.textContent = data.message;
        document.getElementById(ui.passwordId).value = '';
        applyVendorCredentialStatus(data.credentials);
    } else {
        messageEl.className = 'status-message error';
        messageEl.textContent = data.error || 'Save failed';
    }
}

async function clearVendorCredentials(vendor) {
    const ui = _vendorCredUi(vendor);
    if (!confirm(`Remove your saved ${ui.label} credentials?`)) return;
    const res = await fetch(`/api/profile/vendor-credentials/${vendor}`, { method: 'DELETE' });
    const data = await res.json();
    const messageEl = document.getElementById(ui.messageId);
    if (data.success) {
        messageEl.className = 'status-message success';
        messageEl.textContent = data.message;
        document.getElementById(ui.usernameId).value = '';
        document.getElementById(ui.passwordId).value = '';
        applyVendorCredentialStatus(data.credentials);
    } else {
        messageEl.className = 'status-message error';
        messageEl.textContent = data.error || 'Clear failed';
    }
}
