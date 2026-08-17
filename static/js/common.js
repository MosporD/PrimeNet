/**
 * Common JavaScript utilities shared across all pages
 */

const THEME_STORAGE_KEY = 'primenet-theme';
const BRAND_FAVICON_PATH = '/static/images/favicon.png?v=4';
const PAGE_TRANSITION_STORAGE_KEY = 'primenetPageEnterDirection';
const NAV_SECTIONS_STORAGE_KEY = 'primenetNavSections';
const NAV_ROLE_STORAGE_KEY = 'primenetUserRole';
const PRIMENET_CLOCK_OFFSET_HOURS = 3;
const PRIMENET_CLOCK_LABEL = 'UTC+3';

function formatPrimeNetClock(date = new Date()) {
    try {
        const parts = new Intl.DateTimeFormat('en-GB', {
            timeZone: 'Asia/Amman',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: false,
        }).formatToParts(date);
        const pick = (type) => parts.find((p) => p.type === type)?.value || '00';
        return `${PRIMENET_CLOCK_LABEL} ${pick('hour')}:${pick('minute')}:${pick('second')}`;
    } catch (_) {
        const shifted = new Date(date.getTime() + PRIMENET_CLOCK_OFFSET_HOURS * 3600000);
        return `${PRIMENET_CLOCK_LABEL} ${shifted.toISOString().slice(11, 19)}`;
    }
}

let _featureNavSections = null;
let _featureNavLoadPromise = null;

function _isDashboardPage() {
    const p = String(window.location?.pathname || '').trim();
    return p === '/dashboard' || p === '/dashboard/';
}

function _isPublicAuthPage() {
    const p = String(window.location?.pathname || '').trim();
    return p === '/login' || p === '/login/' || p === '/register' || p === '/register/';
}

function _isPortalPage() {
    const p = String(window.location?.pathname || '').trim().replace(/\/+$/, '') || '/';
    return p === '/portals' || p.startsWith('/portals/');
}

const CONSTELLATION_CSS_VERSION = '1.9';
const CONSTELLATION_JS_VERSION = '1.9';

function _constellationBgExcluded(path) {
    return /^\/(login|register|portals|network-map|neighbor-analysis|performance|performance-analytics|cell-heatmap|conflict-map|fault-management|femto-pm|network-health|son-analytics|drive-test-viewer)(\/|$)/.test(path);
}

function _shouldMountConstellationBackground() {
    if (_isPublicAuthPage()) return false;
    if (document.body.classList.contains('no-constellation-bg')) return false;
    const path = String(window.location?.pathname || '').replace(/\/+$/, '') || '/';
    if (_constellationBgExcluded(path)) return false;
    return Boolean(
        document.body.classList.contains('has-constellation-bg')
        || document.querySelector('.container')
    );
}

function _ensureConstellationStylesheet() {
    if (document.querySelector('link[data-primenet-constellation-css]')) return;
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = `/static/css/constellation.css?v=${CONSTELLATION_CSS_VERSION}`;
    link.setAttribute('data-primenet-constellation-css', '1');
    document.head.appendChild(link);
}

async function _refreshAmbientNetworkActivity() {
    try {
        const res = await fetch('/api/dashboard/network-activity', {
            credentials: 'same-origin',
            cache: 'no-store',
            headers: { Accept: 'application/json' },
        });
        const data = await res.json().catch(() => ({}));
        const bg = window.primeNetAmbientBg || window.dashboardAmbientBg;
        if (res.ok && data.success && data.level != null && bg) {
            bg.setActivity(data.level);
        }
    } catch (_) { /* ignore */ }
}

function _bootConstellationBackground() {
    if (!window.PrimeNetConstellation || window.primeNetAmbientBg) return;
    const canvas = document.getElementById('primenet-bg-canvas') || document.getElementById('dashboard-bg-canvas');
    if (!canvas) return;
    window.primeNetAmbientBg = PrimeNetConstellation.initAmbientBackground(canvas);
    window.dashboardAmbientBg = window.primeNetAmbientBg;
    if (!_isDashboardPage()) {
        _refreshAmbientNetworkActivity();
        setInterval(_refreshAmbientNetworkActivity, 10 * 60 * 1000);
    }
}

function _mountConstellationBackground() {
    if (!_shouldMountConstellationBackground()) return;
    document.body.classList.add('has-constellation-bg');
    _ensureConstellationStylesheet();

    let canvas = document.getElementById('primenet-bg-canvas') || document.getElementById('dashboard-bg-canvas');
    if (!canvas) {
        canvas = document.createElement('canvas');
        canvas.id = 'primenet-bg-canvas';
        canvas.className = 'primenet-bg-canvas';
        canvas.setAttribute('aria-hidden', 'true');
        document.body.insertBefore(canvas, document.body.firstChild);
    }

    if (window.PrimeNetConstellation) {
        _bootConstellationBackground();
        return;
    }

    const existing = document.querySelector('script[data-primenet-constellation-js]');
    if (existing) {
        existing.addEventListener('load', _bootConstellationBackground, { once: true });
        return;
    }

    const script = document.createElement('script');
    script.src = `/static/js/constellation.js?v=${CONSTELLATION_JS_VERSION}`;
    script.setAttribute('data-primenet-constellation-js', '1');
    script.onload = _bootConstellationBackground;
    document.head.appendChild(script);
}

function _showPostLoginIntro() {
    if (_isPublicAuthPage()) return;
    let shouldShow = false;
    try {
        shouldShow = sessionStorage.getItem('primenetPostLoginIntro') === '1';
        if (!shouldShow) {
            document.dispatchEvent(new CustomEvent('primenet:intro:done'));
            return;
        }
        sessionStorage.removeItem('primenetPostLoginIntro');
    } catch (_) {
        document.dispatchEvent(new CustomEvent('primenet:intro:done'));
        return;
    }

    const overlay = document.createElement('div');
    overlay.className = 'post-login-intro';
    overlay.innerHTML = `
        <div class="post-login-intro-card">
            <img src="${BRAND_FAVICON_PATH}" alt="PrimeNet logo" class="post-login-intro-logo">
            <div class="post-login-intro-title">PrimeNet</div>
            <div class="post-login-intro-subtitle">Network Performance & Configuration Platform</div>
        </div>
    `;
    document.body.appendChild(overlay);
    // Trigger CSS transition shortly after mount for smoother perceived entry.
    setTimeout(() => overlay.classList.add('fade-up'), 120);
    setTimeout(() => {
        overlay.remove();
        document.dispatchEvent(new CustomEvent('primenet:intro:done'));
    }, 2000);
}

function _preferredTheme() {
    try {
        const saved = localStorage.getItem(THEME_STORAGE_KEY);
        if (saved === 'dark' || saved === 'light') return saved;
        const legacy = localStorage.getItem('darkMode');
        if (legacy === 'true') return 'dark';
        if (legacy === 'false') return 'light';
    } catch (_) { /* ignore */ }
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function _chartThemeColors(theme) {
    if (theme === 'dark') {
        return {
            text: '#b8c4d6',
            grid: 'rgba(148, 163, 184, 0.12)',
            zero: 'rgba(148, 163, 184, 0.2)',
            legend: '#d8e2ef',
        };
    }
    return {
        text: '#6d7f92',
        grid: 'rgba(127, 166, 194, 0.16)',
        zero: 'rgba(127, 166, 194, 0.28)',
        legend: '#2c3e50',
    };
}

function _applyScaleTheme(scale, colors) {
    if (!scale || typeof scale !== 'object') return;
    scale.ticks = scale.ticks || {};
    scale.grid = scale.grid || {};
    scale.ticks.color = colors.text;
    scale.grid.color = colors.grid;
    scale.grid.borderColor = colors.zero;
}

function _syncChartTheme(theme) {
    if (!window.Chart) return;
    const colors = _chartThemeColors(theme);
    try {
        Chart.defaults.color = colors.text;
        Chart.defaults.borderColor = colors.grid;
        if (Chart.defaults.plugins && Chart.defaults.plugins.legend) {
            Chart.defaults.plugins.legend.labels = Chart.defaults.plugins.legend.labels || {};
            Chart.defaults.plugins.legend.labels.color = colors.legend;
        }
    } catch (_) { /* ignore Chart.js version differences */ }

    const instances = Chart.instances
        ? (typeof Chart.instances.forEach === 'function'
            ? Array.from(Chart.instances.values())
            : Object.values(Chart.instances))
        : [];
    instances.forEach((chart) => {
        if (!chart || !chart.options) return;
        const scales = chart.options.scales || {};
        Object.keys(scales).forEach((key) => _applyScaleTheme(scales[key], colors));
        if (chart.options.plugins && chart.options.plugins.legend) {
            chart.options.plugins.legend.labels = chart.options.plugins.legend.labels || {};
            chart.options.plugins.legend.labels.color = colors.legend;
        }
        try {
            chart.update('none');
        } catch (_) {
            try { chart.update(); } catch (__) { /* ignore */ }
        }
    });
}

function _applyTheme(theme) {
    const t = theme === 'dark' ? 'dark' : 'light';
    document.body.classList.toggle('dark-mode', t === 'dark');
    document.documentElement.setAttribute('data-theme', t);
    try {
        localStorage.setItem(THEME_STORAGE_KEY, t);
        localStorage.setItem('darkMode', t === 'dark' ? 'true' : 'false');
    } catch (_) { /* ignore */ }
    const btn = document.getElementById('dark-mode-btn');
    if (btn) {
        btn.textContent = t === 'dark' ? 'Light Mode' : 'Dark Mode';
        btn.setAttribute('aria-pressed', t === 'dark' ? 'true' : 'false');
        btn.title = t === 'dark' ? 'Switch to light mode' : 'Switch to dark mode';
    }
    _syncChartTheme(t);
    document.dispatchEvent(new CustomEvent('primenet:theme-change', { detail: { theme: t } }));
}

function toggleDarkMode() {
    const dark = document.body.classList.contains('dark-mode');
    _applyTheme(dark ? 'light' : 'dark');
}

function _ensureThemeToggle() {
    if (document.getElementById('dark-mode-btn')) return;
    const btn = document.createElement('button');
    btn.id = 'dark-mode-btn';
    btn.type = 'button';
    btn.className = 'header-theme-btn';
    btn.textContent = 'Dark Mode';
    btn.setAttribute('aria-label', 'Toggle dark mode');
    btn.addEventListener('click', toggleDarkMode);

    const mount = document.querySelector('header .header-actions')
        || document.querySelector('header .header-right')
        || document.querySelector('.map-header .header-right')
        || document.querySelector('.ch-topbar .ch-topbar-actions')
        || document.querySelector('.son-topbar .son-topbar-actions')
        || document.querySelector('.nh-header .nh-header-right')
        || document.querySelector('.nh-select-header')
        || document.querySelector('.login-theme-mount')
        || document.querySelector('.portal-theme-mount');
    if (!mount) return;
    if (mount.classList && mount.classList.contains('header-actions')) {
        btn.classList.add('btn-header', 'btn-header-outline');
    } else if (mount.classList && (mount.classList.contains('login-theme-mount') || mount.classList.contains('portal-theme-mount'))) {
        btn.className = 'login-theme-btn';
    }
    mount.appendChild(btn);
}

function _ensureBrandFavicon() {
    // Pages that declare their own favicon (the NexusCore shell: login and
    // portal pages) keep it; PrimeNet pages get the default brand icon.
    if (document.querySelector('link[rel~="icon"][data-page-favicon]')) return;
    let link = document.querySelector('link[rel~="icon"]');
    if (!link) {
        link = document.createElement('link');
        link.setAttribute('rel', 'icon');
        document.head.appendChild(link);
    }
    link.setAttribute('rel', 'shortcut icon');
    link.setAttribute('href', BRAND_FAVICON_PATH);
    link.setAttribute('type', 'image/png');
}

function _normalizeNavHref(href) {
    try {
        const path = new URL(href, window.location.origin).pathname || '/';
        return path.replace(/\/+$/, '') || '/';
    } catch (_) {
        return String(href || '/').split('?')[0].replace(/\/+$/, '') || '/';
    }
}

function _setFeatureNavSections(sections) {
    _featureNavSections = Array.isArray(sections) ? sections : [];
    try {
        sessionStorage.setItem(NAV_SECTIONS_STORAGE_KEY, JSON.stringify(_featureNavSections));
    } catch (_) { /* ignore */ }
}

function _readCachedFeatureNavSections() {
    try {
        const raw = sessionStorage.getItem(NAV_SECTIONS_STORAGE_KEY);
        if (!raw) return null;
        const parsed = JSON.parse(raw);
        return Array.isArray(parsed) ? parsed : null;
    } catch (_) {
        return null;
    }
}

async function _loadFeatureNavSections(forceRefresh = false) {
    if (_isPublicAuthPage()) return [];
    if (!forceRefresh && Array.isArray(_featureNavSections)) {
        return _featureNavSections;
    }
    if (!forceRefresh) {
        const cached = _readCachedFeatureNavSections();
        if (cached) {
            _featureNavSections = cached;
            return cached;
        }
    }
    if (_featureNavLoadPromise) {
        return _featureNavLoadPromise;
    }
    _featureNavLoadPromise = (async () => {
        try {
            const res = await fetch('/api/navigation/allowed', {
                credentials: 'same-origin',
                cache: 'no-store',
                headers: { Accept: 'application/json' },
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok || !data.success) {
                throw new Error(data.error || 'Could not load navigation');
            }
            _setFeatureNavSections(data.sections || []);
            try {
                if (data.role) sessionStorage.setItem(NAV_ROLE_STORAGE_KEY, String(data.role));
            } catch (_) { /* ignore */ }
            return _featureNavSections;
        } catch (err) {
            console.warn('Feature navigation permissions unavailable', err);
            _featureNavSections = [];
            return _featureNavSections;
        } finally {
            _featureNavLoadPromise = null;
        }
    })();
    return _featureNavLoadPromise;
}

function _invalidateFeatureNavPanel() {
    const overlay = document.getElementById('feature-nav-overlay');
    if (overlay) overlay.remove();
}

function _buildFeatureNavPanel(sections) {
    _invalidateFeatureNavPanel();

    const overlay = document.createElement('div');
    overlay.id = 'feature-nav-overlay';
    overlay.className = 'feature-nav-overlay';
    overlay.setAttribute('aria-hidden', 'true');
    overlay.innerHTML = `
        <div class="feature-nav-panel" role="dialog" aria-modal="true" aria-label="Main feature navigation">
            <div class="feature-nav-head">
                <h3>Feature Navigation</h3>
                <button type="button" id="feature-nav-close" class="feature-nav-close" aria-label="Close navigation">x</button>
            </div>
            <div id="feature-nav-grid" class="feature-nav-grid" role="list"></div>
        </div>
    `;

    const grid = overlay.querySelector('#feature-nav-grid');
    const navSections = Array.isArray(sections) ? sections : [];
    if (!navSections.length) {
        grid.innerHTML = '<p class="feature-nav-empty">No features are available for your account.</p>';
    } else {
        navSections.forEach((section) => {
            const block = document.createElement('section');
            block.className = 'feature-nav-section';
            const links = (section.links || [])
                .map((item) => `<a href="${item.href}" class="feature-nav-link" role="listitem">${item.label}</a>`)
                .join('');
            block.innerHTML = `
                <h4>${section.title}</h4>
                ${links}
            `;
            grid.appendChild(block);
        });
    }

    overlay.addEventListener('click', (event) => {
        if (event.target === overlay) {
            _closeFeatureNav();
        }
    });
    overlay.querySelector('#feature-nav-close').addEventListener('click', _closeFeatureNav);
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') _closeFeatureNav();
    });

    document.body.appendChild(overlay);
}

async function _openFeatureNav() {
    const sections = await _loadFeatureNavSections();
    _buildFeatureNavPanel(sections);
    const overlay = document.getElementById('feature-nav-overlay');
    if (!overlay) return;
    overlay.classList.add('open');
    overlay.setAttribute('aria-hidden', 'false');
}

function _closeFeatureNav() {
    const overlay = document.getElementById('feature-nav-overlay');
    if (!overlay) return;
    overlay.classList.remove('open');
    overlay.setAttribute('aria-hidden', 'true');
}

function _runFeatureNavTransition(direction, href) {
    // Navigate immediately — delayed slide-outs caused a flash of the previous
    // page / light theme and felt like a remembered hop through the dashboard.
    try {
        sessionStorage.removeItem(PAGE_TRANSITION_STORAGE_KEY);
    } catch (_) { /* ignore */ }
    window.location.href = href;
}

function _clearPageTransitionClasses() {
    document.body.classList.remove(
        'page-transition-out',
        'page-transition-out-left',
        'page-transition-out-right',
        'page-transition-enter-from-left',
        'page-transition-enter-from-right',
        'page-transition-enter-active'
    );
}

function _wirePageLinkTransitions() {
    document.addEventListener('click', (event) => {
        const link = event.target && event.target.closest ? event.target.closest('a[href]') : null;
        if (!link) return;
        if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        if ((link.getAttribute('target') || '').toLowerCase() === '_blank') return;
        if (link.hasAttribute('download')) return;
        if ((link.getAttribute('rel') || '').toLowerCase().includes('external')) return;
        if (link.dataset && link.dataset.noTransition === 'true') return;

        const rawHref = link.getAttribute('href');
        if (!rawHref || rawHref.startsWith('#') || rawHref.startsWith('javascript:')) return;

        let url;
        try {
            url = new URL(rawHref, window.location.origin);
        } catch (_) {
            return;
        }
        if (url.origin !== window.location.origin) return;

        const href = url.pathname + url.search + url.hash;
        const targetPath = String(url.pathname).replace(/\/+$/, '') || '/';
        const currentPath = String(window.location.pathname || '').replace(/\/+$/, '') || '/';
        if (targetPath === currentPath) {
            if (link.classList.contains('feature-nav-link')) _closeFeatureNav();
            return;
        }
        event.preventDefault();
        if (link.classList.contains('feature-nav-link')) _closeFeatureNav();
        _runFeatureNavTransition(null, href);
    });
}

function _runPageEnterTransition() {
    // Clear any leftover transition state from older clients; no enter animation.
    try {
        sessionStorage.removeItem(PAGE_TRANSITION_STORAGE_KEY);
    } catch (_) { /* ignore */ }
    _clearPageTransitionClasses();
    document.dispatchEvent(new CustomEvent('primenet:page-enter-done'));
}

function _wirePageTransitionRestoreGuards() {
    window.addEventListener('pagehide', () => {
        _clearPageTransitionClasses();
    });

    window.addEventListener('pageshow', (event) => {
        if (event.persisted || document.body.classList.contains('page-transition-out')) {
            _clearPageTransitionClasses();
            document.dispatchEvent(new CustomEvent('primenet:page-enter-done'));
        }
    });
}

function _ensureFeatureNavButton() {
    if (_isDashboardPage() || _isPublicAuthPage() || _isPortalPage()) return;
    if (document.getElementById('feature-nav-btn')) return;
    const headerContent = document.querySelector('header .header-content');
    const mapHeaderLeft = document.querySelector('.map-header .header-left');
    const customTopbar = document.querySelector('.ch-topbar')
        || document.querySelector('.son-topbar')
        || document.querySelector('.nh-select-header')
        || document.querySelector('.nh-header');
    const mount = headerContent || mapHeaderLeft || customTopbar;
    if (!mount) return;
    const btn = document.createElement('button');
    btn.id = 'feature-nav-btn';
    btn.type = 'button';
    btn.className = 'feature-nav-btn';
    btn.setAttribute('aria-label', 'Open main feature navigation');
    btn.title = 'Features';
    btn.innerHTML = '<span class="feature-nav-btn-label">Features</span>';
    btn.addEventListener('click', () => { _openFeatureNav(); });
    mount.appendChild(btn);
}

function _ensureHeaderNavCluster() {
    if (_isDashboardPage() || _isPublicAuthPage() || _isPortalPage()) return;
    const headerContent = document.querySelector('header .header-content');
    if (!headerContent) return;

    let cluster = headerContent.querySelector('.header-nav-left');
    if (!cluster) {
        cluster = document.createElement('div');
        cluster.className = 'header-nav-left';
        headerContent.insertBefore(cluster, headerContent.firstChild);
    }

    const featureBtn = document.getElementById('feature-nav-btn');
    if (featureBtn && featureBtn.parentElement !== cluster) {
        cluster.appendChild(featureBtn);
    }

    const backLink = headerContent.querySelector(':scope > .back-link')
        || headerContent.querySelector('.header-left > .back-link')
        || headerContent.querySelector('.header-left .back-link');
    if (backLink && backLink.parentElement !== cluster) {
        cluster.appendChild(backLink);
    }
}

function _injectModuleAdminLink(actions) {
    if (!actions || actions.querySelector('[data-nav="admin"]')) return;
    const role = String(sessionStorage.getItem(NAV_ROLE_STORAGE_KEY) || '').toLowerCase();
    if (!['admin', 'noc_sys'].includes(role)) return;
    const admin = document.createElement('a');
    admin.href = '/admin-panel?section=user-admin';
    admin.className = 'btn-header btn-header-admin';
    admin.dataset.nav = 'admin';
    admin.textContent = 'Admin';
    const settings = actions.querySelector('[data-nav="settings"]');
    if (settings && settings.nextSibling) {
        actions.insertBefore(admin, settings.nextSibling);
    } else {
        actions.appendChild(admin);
    }
}

function _ensureModuleHeaderActions() {
    if (_isDashboardPage() || _isPublicAuthPage() || _isPortalPage()) return;
    const headerRight = document.querySelector('header .header-right');
    if (!headerRight || headerRight.querySelector('.header-actions')) return;

    let actions = document.createElement('div');
    actions.className = 'header-actions module-header-actions';

    const settings = document.createElement('a');
    settings.href = '/profile';
    settings.className = 'btn-header';
    settings.dataset.nav = 'settings';
    settings.textContent = 'Settings';
    actions.appendChild(settings);

    _injectModuleAdminLink(actions);

    const logoutBtn = headerRight.querySelector('.btn-logout');
    if (logoutBtn) {
        logoutBtn.classList.remove('btn-logout');
        logoutBtn.classList.add('btn-header', 'btn-header-outline');
        actions.appendChild(logoutBtn);
    }

    const userName = headerRight.querySelector('.user-name, .user-greeting');
    if (userName) {
        userName.insertAdjacentElement('afterend', actions);
    } else {
        headerRight.prepend(actions);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    _runPageEnterTransition();
    _wirePageTransitionRestoreGuards();
    _ensureBrandFavicon();
    _ensureFeatureNavButton();
    _ensureHeaderNavCluster();
    _ensureModuleHeaderActions();
    _wirePageLinkTransitions();
    _ensureThemeToggle();
    _applyTheme(_preferredTheme());
    _mountConstellationBackground();
    _showPostLoginIntro();
    if (!_isPublicAuthPage()) {
        _loadFeatureNavSections().then(() => {
            const actions = document.querySelector('header .module-header-actions');
            if (actions) _injectModuleAdminLink(actions);
        });
    }
});

// Apply theme as soon as this file runs (body already exists when common.js is at page end).
try {
    if (document.body) _applyTheme(_preferredTheme());
} catch (_) { /* ignore */ }
// Logout function
async function logout() {
    if (confirm('Are you sure you want to logout?')) {
        try {
            const response = await fetch('/api/logout', { method: 'POST' });
            if (response.ok) {
                try {
                    sessionStorage.removeItem(NAV_SECTIONS_STORAGE_KEY);
                    sessionStorage.removeItem(NAV_ROLE_STORAGE_KEY);
                } catch (_) { /* ignore */ }
                window.location.href = '/login';
            }
        } catch (error) {
            console.error('Logout error:', error);
            window.location.href = '/login';
        }
    }
}

// Show notification
function showNotification(message, type = 'info') {
    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.textContent = message;
    notification.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        padding: 15px 25px;
        border-radius: 8px;
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.2);
        z-index: 10000;
        font-weight: 600;
        animation: slideIn 0.3s ease;
    `;

    if (type === 'success') {
        notification.style.background = '#27ae60';
        notification.style.color = 'white';
    } else if (type === 'error') {
        notification.style.background = '#e74c3c';
        notification.style.color = 'white';
    } else {
        notification.style.background = '#3498db';
        notification.style.color = 'white';
    }

    document.body.appendChild(notification);

    setTimeout(() => {
        notification.style.animation = 'slideOut 0.3s ease';
        setTimeout(() => notification.remove(), 300);
    }, 3000);
}

// Add animation styles
const style = document.createElement('style');
style.textContent = `
    @keyframes slideIn {
        from {
            transform: translateX(400px);
            opacity: 0;
        }
        to {
            transform: translateX(0);
            opacity: 1;
        }
    }
    @keyframes slideOut {
        from {
            transform: translateX(0);
            opacity: 1;
        }
        to {
            transform: translateX(400px);
            opacity: 0;
        }
    }
    .post-login-intro {
        position: fixed;
        inset: 0;
        z-index: 10020;
        display: flex;
        align-items: center;
        justify-content: center;
        background: rgba(8, 16, 28, 0.9);
        opacity: 1;
        transition: opacity 2s ease, transform 2s ease;
        pointer-events: none;
    }
    .post-login-intro-card {
        width: 100vw;
        height: 100vh;
        text-align: center;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        background: linear-gradient(135deg, rgba(180,205,224,0.98) 0%, rgba(127,166,194,0.96) 100%);
        color: #fff;
        border-radius: 0;
        padding: 26px 28px;
        box-shadow: none;
    }
    .post-login-intro-logo {
        width: 56px;
        height: 56px;
        border-radius: 50%;
        background: rgba(255,255,255,0.92);
        padding: 6px;
        margin-bottom: 8px;
    }
    .post-login-intro-title {
        font-size: 2rem;
        font-weight: 800;
        letter-spacing: 0.01em;
    }
    .post-login-intro-subtitle {
        font-size: 1rem;
        opacity: 0.95;
        margin-top: 4px;
    }
    .post-login-intro.fade-up {
        opacity: 0;
        transform: translateY(-120px);
    }
    body.page-transition-out {
        transition: transform 420ms cubic-bezier(0.22, 1, 0.36, 1), opacity 420ms ease;
        will-change: transform, opacity;
    }
    body.page-transition-out-right {
        transform: translateX(110px);
        opacity: 0;
    }
    body.page-transition-out-left {
        transform: translateX(-110px);
        opacity: 0;
    }
    body.page-transition-enter-from-right {
        transform: translateX(110px);
        opacity: 0;
    }
    body.page-transition-enter-from-left {
        transform: translateX(-110px);
        opacity: 0;
    }
    body.page-transition-enter-active {
        transition: transform 460ms cubic-bezier(0.22, 1, 0.36, 1), opacity 460ms ease;
        transform: translateX(0);
        opacity: 1;
    }
`;
document.head.appendChild(style);

// Show loading spinner
function showLoading(elementId) {
    const element = document.getElementById(elementId);
    if (element) {
        element.innerHTML = '<div class="loading-spinner"></div>';
        element.style.display = 'block';
    }
}

// Hide loading spinner
function hideLoading(elementId) {
    const element = document.getElementById(elementId);
    if (element) {
        element.style.display = 'none';
    }
}

/** CSS --ui-zoom scale factor (PrimeNet global UI scale). */
function getUiZoom() {
    const raw = getComputedStyle(document.documentElement).getPropertyValue('--ui-zoom').trim();
    const z = parseFloat(raw);
    return z > 0 && Number.isFinite(z) ? z : 1;
}

/**
 * Map pointer client coordinates to element-local layout space.
 * Fixes click/drag offset when ancestors use CSS zoom or transform scale.
 */
function pointerLocalXY(event, element) {
    const rect = element.getBoundingClientRect();
    if (!rect.width || !rect.height) {
        return { x: 0, y: 0 };
    }
    const scaleX = element.offsetWidth / rect.width;
    const scaleY = element.offsetHeight / rect.height;
    return {
        x: (event.clientX - rect.left) * scaleX,
        y: (event.clientY - rect.top) * scaleY,
    };
}

function _escapeLoadingText(text) {
    return String(text || 'Loading…')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

/** Show animated spinner on a button while an async action runs. */
function setButtonLoading(button, loading, labelWhileLoading) {
    if (!button) return;
    if (loading) {
        if (!button.dataset.pnLoadingActive) {
            button.dataset.pnLoadingOriginalHtml = button.innerHTML;
            button.dataset.pnLoadingOriginalDisabled = button.disabled ? '1' : '0';
            button.dataset.pnLoadingActive = '1';
        }
        button.disabled = true;
        button.classList.add('is-loading');
        button.setAttribute('aria-busy', 'true');
        const label = _escapeLoadingText(labelWhileLoading || 'Loading…');
        button.innerHTML = `<span class="btn-loading-spinner" aria-hidden="true"></span><span class="btn-loading-label">${label}</span>`;
        return;
    }
    if (button.dataset.pnLoadingActive) {
        button.innerHTML = button.dataset.pnLoadingOriginalHtml || button.innerHTML;
        button.disabled = button.dataset.pnLoadingOriginalDisabled === '1';
        delete button.dataset.pnLoadingOriginalHtml;
        delete button.dataset.pnLoadingOriginalDisabled;
        delete button.dataset.pnLoadingActive;
    }
    button.classList.remove('is-loading');
    button.removeAttribute('aria-busy');
}

async function withButtonLoading(button, fn, labelWhileLoading) {
    setButtonLoading(button, true, labelWhileLoading);
    try {
        return await fn();
    } finally {
        setButtonLoading(button, false);
    }
}

/** Semi-transparent overlay with spinner over a panel/section. */
function showPanelLoading(panelEl, message) {
    if (!panelEl) return;
    panelEl.classList.add('pn-loading-host');
    let overlay = panelEl.querySelector(':scope > .pn-loading-overlay');
    if (!overlay) {
        overlay = document.createElement('div');
        overlay.className = 'pn-loading-overlay';
        overlay.innerHTML = (
            '<div class="pn-loading-overlay-inner">'
            + '<div class="loading-spinner" aria-hidden="true"></div>'
            + '<p class="pn-loading-message"></p>'
            + '</div>'
        );
        panelEl.appendChild(overlay);
    }
    const msg = overlay.querySelector('.pn-loading-message');
    if (msg) msg.textContent = message || 'Loading…';
    overlay.hidden = false;
    panelEl.setAttribute('aria-busy', 'true');
}

function hidePanelLoading(panelEl) {
    if (!panelEl) return;
    const overlay = panelEl.querySelector(':scope > .pn-loading-overlay');
    if (overlay) overlay.hidden = true;
    panelEl.removeAttribute('aria-busy');
}

/**
 * Chart.js maps pointer coords using layout width but getBoundingClientRect is
 * visual width under CSS zoom — hover/tooltip points drift.
 *
 * Important: Chart 4.x calls getRelativePosition (minified ve) internally as a
 * closed-over function, so patching Chart.helpers.getRelativePosition alone
 * does NOT fix hover. We register a global beforeEvent plugin instead.
 */
function _chartPointerFromNative(chart, native) {
    const canvas = chart?.canvas;
    if (!canvas || !native) return null;
    const pt = native.touches?.length ? native.touches[0] : native;
    if (!pt || typeof pt.clientX !== 'number') return null;

    const rect = canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;

    const dpr = chart.currentDevicePixelRatio || 1;
    const bufW = canvas.width / dpr;
    const bufH = canvas.height / dpr;
    if (!bufW || !bufH) return null;

    return {
        x: Math.round(((pt.clientX - rect.left) / rect.width) * bufW),
        y: Math.round(((pt.clientY - rect.top) / rect.height) * bufH),
    };
}

function _chartHelpersTarget() {
    if (typeof Chart === 'undefined') return null;
    const helpers = Chart.helpers;
    if (!helpers) return null;
    if (typeof helpers.getRelativePosition === 'function') return helpers;
    if (helpers.dom && typeof helpers.dom.getRelativePosition === 'function') return helpers.dom;
    return null;
}

function _canvasUiZoomScale(canvas) {
    const rect = canvas.getBoundingClientRect();
    const z = getUiZoom();
    let scaleX = 1;
    let scaleY = 1;
    if (rect.width > 0 && rect.height > 0) {
        scaleX = canvas.offsetWidth / rect.width;
        scaleY = canvas.offsetHeight / rect.height;
    }
    if (!Number.isFinite(scaleX) || scaleX <= 0) scaleX = 1;
    if (!Number.isFinite(scaleY) || scaleY <= 0) scaleY = 1;
    if (Math.abs(scaleX - 1) < 0.015 && Math.abs(z - 1) > 0.015) {
        scaleX = 1 / z;
    }
    if (Math.abs(scaleY - 1) < 0.015 && Math.abs(z - 1) > 0.015) {
        scaleY = 1 / z;
    }
    return { scaleX, scaleY };
}

const PN_UI_ZOOM_CHART_PLUGIN = {
    id: 'pnUiZoomFix',
    beforeEvent(chart, args) {
        if (Math.abs(getUiZoom() - 1) < 0.001) return;
        const evt = args?.event;
        if (!evt) return;
        const native = evt.native || evt;
        const pos = _chartPointerFromNative(chart, native);
        if (!pos) return;
        evt.x = pos.x;
        evt.y = pos.y;
        if (typeof chart.isPointInArea === 'function') {
            args.inChartArea = chart.isPointInArea(evt);
        }
    },
};

function registerChartJsUiZoomPlugin() {
    if (typeof Chart === 'undefined' || typeof Chart.register !== 'function') return false;
    if (Chart.registry?.plugins?.get('pnUiZoomFix')) return true;
    Chart.register(PN_UI_ZOOM_CHART_PLUGIN);
    return true;
}

function patchChartJsForUiZoom() {
    registerChartJsUiZoomPlugin();

    const target = _chartHelpersTarget();
    if (!target?.getRelativePosition || target._pnUiZoomPatched) {
        return registerChartJsUiZoomPlugin();
    }
    const original = target.getRelativePosition.bind(target);
    target.getRelativePosition = function (event, chart) {
        if (event && 'native' in event) return event;
        const native = event?.native || event;
        const pos = _chartPointerFromNative(chart, native);
        if (pos) return pos;
        return original(event, chart);
    };
    target._pnUiZoomPatched = true;
    return true;
}

/** Attach to each Chart config — guarantees zoom fix even if global register ran late. */
function pnChartPlugins() {
    patchChartJsForUiZoom();
    return [PN_UI_ZOOM_CHART_PLUGIN];
}

function ensureChartJsUiZoomPatch() {
    if (patchChartJsForUiZoom()) return;
    let tries = 0;
    const timer = setInterval(() => {
        if (patchChartJsForUiZoom() || ++tries > 100) {
            clearInterval(timer);
        }
    }, 50);
}

window.getUiZoom = getUiZoom;
window.pointerLocalXY = pointerLocalXY;
window.setButtonLoading = setButtonLoading;
window.withButtonLoading = withButtonLoading;
window.showPanelLoading = showPanelLoading;
window.hidePanelLoading = hidePanelLoading;
window.patchChartJsForUiZoom = patchChartJsForUiZoom;
window.registerChartJsUiZoomPlugin = registerChartJsUiZoomPlugin;
window.PN_UI_ZOOM_CHART_PLUGIN = PN_UI_ZOOM_CHART_PLUGIN;
window.pnChartPlugins = pnChartPlugins;

ensureChartJsUiZoomPatch();

// Format file size
function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
}

// Format date
function formatDate(dateString) {
    const date = new Date(dateString);
    return date.toLocaleString();
}
