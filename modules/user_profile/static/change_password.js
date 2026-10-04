(function () {
    'use strict';

    function calcStrength(pw) {
        let score = 0;
        if (!pw) return 0;
        if (pw.length >= 6) score += 1;
        if (pw.length >= 10) score += 1;
        if (/[A-Z]/.test(pw) && /[a-z]/.test(pw)) score += 1;
        if (/\d/.test(pw)) score += 1;
        if (/[^A-Za-z0-9]/.test(pw)) score += 1;
        return Math.min(score, 5);
    }

    function updateStrength() {
        const pw = document.getElementById('newPassword')?.value || '';
        const fill = document.getElementById('strengthFill');
        const label = document.getElementById('strengthLabel');
        if (!fill || !label) return;
        const score = calcStrength(pw);
        const pct = (score / 5) * 100;
        const colors = ['#e74c3c', '#e67e22', '#f1c40f', '#2ecc71', '#27ae60'];
        const labels = ['Very Weak', 'Weak', 'Fair', 'Strong', 'Very Strong'];
        fill.style.width = pct + '%';
        fill.style.background = pw ? (colors[score - 1] || colors[0]) : '';
        label.textContent = pw ? (labels[score - 1] || labels[0]) : '';
    }

    function showError(msg) {
        const el = document.getElementById('error-message');
        const ok = document.getElementById('success-message');
        if (ok) {
            ok.style.display = 'none';
            ok.textContent = '';
        }
        if (!el) return;
        el.textContent = msg || '';
        el.style.display = msg ? 'block' : 'none';
    }

    function showSuccess(msg) {
        const el = document.getElementById('success-message');
        const err = document.getElementById('error-message');
        if (err) {
            err.style.display = 'none';
            err.textContent = '';
        }
        if (!el) return;
        el.textContent = msg || '';
        el.style.display = msg ? 'block' : 'none';
    }

    async function submitChange(ev) {
        ev.preventDefault();
        const btn = document.getElementById('submit-btn');
        const currentPassword = document.getElementById('currentPassword')?.value || '';
        const newPassword = document.getElementById('newPassword')?.value || '';
        const confirmPassword = document.getElementById('confirmPassword')?.value || '';

        if (!currentPassword || !newPassword || !confirmPassword) {
            showError('All password fields are required.');
            return;
        }
        if (newPassword !== confirmPassword) {
            showError('New passwords do not match.');
            return;
        }
        if (newPassword.length < 6) {
            showError('Password must be at least 6 characters.');
            return;
        }

        if (btn) btn.disabled = true;
        showError('');
        try {
            const res = await fetch('/api/profile/change-password', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    current_password: currentPassword,
                    new_password: newPassword,
                    confirm_password: confirmPassword,
                }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok || !data.success) {
                showError(data.error || 'Password change failed.');
                if (btn) btn.disabled = false;
                return;
            }
            showSuccess(data.message || 'Password changed. Redirecting…');
            const dest = (document.body.dataset.postChangeRedirect || '').trim() || '/';
            window.setTimeout(() => {
                window.location.href = dest;
            }, 700);
        } catch (_) {
            showError('Connection error. Please try again.');
            if (btn) btn.disabled = false;
        }
    }

    async function logout() {
        try {
            await fetch('/api/logout', { method: 'POST' });
        } catch (_) { /* ignore */ }
        window.location.href = '/login';
    }

    document.addEventListener('DOMContentLoaded', () => {
        PrimeNetConstellation?.initLoginScene?.(document.getElementById('constellation-canvas'));
        document.getElementById('newPassword')?.addEventListener('input', updateStrength);
        document.getElementById('change-password-form')?.addEventListener('submit', submitChange);
        document.getElementById('logout-btn')?.addEventListener('click', logout);
        updateStrength();
    });
})();
