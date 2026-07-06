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

const CONSTELLATION_CSS_VERSION = '1.9';
const CONSTELLATION_JS_VERSION = '1.4';

function _constellationBgExcluded(path) {
    return /^\/(login|register|network-map|neighbor-analysis|performance|performance-analytics|cell-heatmap|conflict-map|fault-management|femto-pm|network-health|son-analytics|drive-test-viewer)(\/|$)/.test(path);
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
    if (_isPublicAuthPage()) return;
    if (document.getElementById('dark-mode-btn')) return;
    const btn = document.createElement('button');
    btn.id = 'dark-mode-btn';
    btn.type = 'button';
    btn.className = 'header-theme-btn';
    btn.textContent = 'Dark Mode';
    btn.setAttribute('aria-label', 'Toggle dark mode');
    btn.addEventListener('click', toggleDarkMode);

    // The dashboard groups its header buttons inside `.header-actions`; on
    // module pages the same selector also exists. Map pages use a custom
    // `.map-header .header-right` container instead.
    const mount = document.querySelector('header .header-actions')
        || document.querySelector('header .header-right')
        || document.querySelector('.map-header .header-right')
        || document.querySelector('.ch-topbar .ch-topbar-actions')
        || document.querySelector('.son-topbar .son-topbar-actions')
        || document.querySelector('.nh-header .nh-header-right')
        || document.querySelector('.nh-select-header');
    if (!mount) return;
    if (mount && mount.classList && mount.classList.contains('header-actions')) {
        btn.classList.add('btn-header', 'btn-header-outline');
    }
    mount.appendChild(btn);
}

function _ensureBrandFavicon() {
    let link = document.querySelector('link[rel="icon"]');
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
    const dir = direction === 'left' ? 'left' : 'right';
    try {
        sessionStorage.setItem(PAGE_TRANSITION_STORAGE_KEY, dir);
    } catch (_) { /* ignore */ }
    document.body.classList.add('page-transition-out', dir === 'left' ? 'page-transition-out-left' : 'page-transition-out-right');
    setTimeout(() => {
        window.location.href = href;
    }, 420);
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
        const direction = (targetPath === '/dashboard') ? 'left' : 'right';
        _runFeatureNavTransition(direction, href);
    });
}

function _runPageEnterTransition() {
    let direction = null;
    try {
        direction = sessionStorage.getItem(PAGE_TRANSITION_STORAGE_KEY);
        if (direction) sessionStorage.removeItem(PAGE_TRANSITION_STORAGE_KEY);
    } catch (_) {
        direction = null;
    }
    if (!direction) {
        document.dispatchEvent(new CustomEvent('primenet:page-enter-done'));
        return;
    }

    const enterClass = direction === 'left' ? 'page-transition-enter-from-left' : 'page-transition-enter-from-right';
    document.body.classList.add(enterClass);
    setTimeout(() => {
        document.body.classList.add('page-transition-enter-active');
    }, 40);

    const done = () => {
        document.body.classList.remove(enterClass, 'page-transition-enter-active');
        document.dispatchEvent(new CustomEvent('primenet:page-enter-done'));
    };
    setTimeout(done, 500);
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
    if (_isDashboardPage() || _isPublicAuthPage()) return;
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

document.addEventListener('DOMContentLoaded', () => {
    _runPageEnterTransition();
    _wirePageTransitionRestoreGuards();
    _ensureBrandFavicon();
    _ensureFeatureNavButton();
    _wirePageLinkTransitions();
    _ensureThemeToggle();
    _applyTheme(_preferredTheme());
    _mountConstellationBackground();
    _showPostLoginIntro();
    if (!_isPublicAuthPage()) {
        _loadFeatureNavSections();
    }
});

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
