window.addEventListener('DOMContentLoaded', () => {
    loadProfile();
    loadPreferences();
    loadActivity();
    document.getElementById('newPassword').addEventListener('input', updateStrength);
});

// ── Profile Load ──────────────────────────────────────────────────────────────
async function loadProfile() {
    const res  = await fetch('/api/profile');
    const data = await res.json();
    if (!data.success) return;

    const p = data.profile;
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
}

// ── Update Profile ────────────────────────────────────────────────────────────
async function updateProfile() {
    const payload = {
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
    if (prefs.compact_tables) document.getElementById('prefCompact').checked     = prefs.compact_tables;
}

async function savePreferences() {
    const payload = {
        default_tab:    document.getElementById('prefDefaultTab').value,
        default_tech:   document.getElementById('prefDefaultTech').value,
        default_vendor: document.getElementById('prefDefaultVendor').value,
        compact_tables: document.getElementById('prefCompact').checked,
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

// ── Activity ──────────────────────────────────────────────────────────────────
async function loadActivity() {
    const res  = await fetch('/api/profile/activity');
    const data = await res.json();
    const list = document.getElementById('activityList');

    const activity = data.activity || [];
    if (!activity.length) {
        list.innerHTML = '<p style="color:#bbb;text-align:center;padding:20px">No activity recorded yet</p>';
        return;
    }

    list.innerHTML = activity.map(a => `
        <div class="activity-item">
            <span class="activity-time">${(a.timestamp || '').slice(0, 16)}</span>
            <div>
                <div class="activity-action">${formatAction(a.action)}</div>
                <div class="activity-details">${a.details || ''}</div>
            </div>
        </div>
    `).join('');
}

function formatAction(action) {
    const map = {
        login:              '🔑 Login',
        logout:             '🚪 Logout',
        register:           '✅ Registered',
        config_upload:      '📤 Config Uploaded',
        config_download:    '📥 Config Downloaded',
        pci_conflict_check: '🔍 PCI Check',
        report_generated:   '📊 Report Generated',
        profile_update:     '✏️ Profile Updated',
        password_change:    '🔒 Password Changed',
        performance_view:   '📈 Performance Viewed',
    };
    return map[action] || action;
}
