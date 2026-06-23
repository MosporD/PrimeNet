/**
 * Common JavaScript utilities shared across all pages
 */

const THEME_STORAGE_KEY = 'primenet-theme';
const BRAND_FAVICON_PATH = '/static/images/favicon.png?v=4';
const PAGE_TRANSITION_STORAGE_KEY = 'primenetPageEnterDirection';
const FEATURE_NAV_SECTIONS = [
    {
        title: 'Main',
        links: [
            { label: 'Dashboard', href: '/dashboard' },
            { label: 'Analytics', href: '/performance' },
            { label: 'Network Map', href: '/network-map' },
            { label: 'Neighbor Analysis', href: '/neighbor-analysis' },
            { label: 'Report Generation', href: '/reports' },
            { label: 'Conflict Map', href: '/conflict-map' },
            { label: 'Femto PM', href: '/femto-pm' },
        ],
    },
    {
        title: 'Configuration',
        links: [
            { label: 'Parameter Dictionary', href: '/parameter-dictionary' },
            { label: 'XML Parser', href: '/xml-parser' },
            { label: 'XML Generator', href: '/excel-generator' },
            { label: 'NE Comparison', href: '/ne-comparison' },
            { label: 'Config Task Scheduler', href: '/config-task-scheduler' },
            { label: 'Config History', href: '/config-history' },
            { label: 'Network Management', href: '/network-management' },
            { label: 'Drive Test Viewer', href: '/drive-test-viewer' },
        ],
    },
    {
        title: 'Administration',
        links: [
            { label: 'Admin Panel', href: '/admin-panel?section=user-admin' },
            { label: 'User Profile', href: '/profile' },
        ],
    },
];

function _isDashboardPage() {
    const p = String(window.location?.pathname || '').trim();
    return p === '/dashboard' || p === '/dashboard/';
}

function _isPublicAuthPage() {
    const p = String(window.location?.pathname || '').trim();
    return p === '/login' || p === '/login/' || p === '/register' || p === '/register/';
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
    } catch (_) { /* ignore */ }
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function _applyTheme(theme) {
    const t = theme === 'dark' ? 'dark' : 'light';
    document.body.classList.toggle('dark-mode', t === 'dark');
    document.documentElement.setAttribute('data-theme', t);
    try {
        localStorage.setItem(THEME_STORAGE_KEY, t);
    } catch (_) { /* ignore */ }
    const btn = document.getElementById('dark-mode-btn');
    if (btn) {
        btn.textContent = t === 'dark' ? 'Light Mode' : 'Dark Mode';
        btn.setAttribute('aria-pressed', t === 'dark' ? 'true' : 'false');
        btn.title = t === 'dark' ? 'Switch to light mode' : 'Switch to dark mode';
    }
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
        || document.querySelector('.map-header .header-right');
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

function _buildFeatureNavPanel() {
    if (document.getElementById('feature-nav-overlay')) return;

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
            <div id="feature-nav-grid" class="feature-nav-grid"></div>
        </div>
    `;

    const grid = overlay.querySelector('#feature-nav-grid');
    FEATURE_NAV_SECTIONS.forEach((section) => {
        const block = document.createElement('section');
        block.className = 'feature-nav-section';
        const links = section.links
            .map((item) => `<a href="${item.href}" class="feature-nav-link">${item.label}</a>`)
            .join('');
        block.innerHTML = `
            <h4>${section.title}</h4>
            ${links}
        `;
        grid.appendChild(block);
    });

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

function _openFeatureNav() {
    _buildFeatureNavPanel();
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

function _ensureFeatureNavButton() {
    if (_isDashboardPage() || _isPublicAuthPage()) return;
    if (document.getElementById('feature-nav-btn')) return;
    const headerContent = document.querySelector('header .header-content');
    const mapHeaderLeft = document.querySelector('.map-header .header-left');
    const mount = headerContent || mapHeaderLeft;
    if (!mount) return;
    const btn = document.createElement('button');
    btn.id = 'feature-nav-btn';
    btn.type = 'button';
    btn.className = 'feature-nav-btn';
    btn.setAttribute('aria-label', 'Open main feature navigation');
    btn.title = 'All features';
    btn.innerHTML = `<span class="feature-arrow-icon" aria-hidden="true">&gt;</span><span class="feature-nav-btn-label">Features</span>`;
    btn.addEventListener('click', _openFeatureNav);
    mount.appendChild(btn);
}

document.addEventListener('DOMContentLoaded', () => {
    _runPageEnterTransition();
    _ensureBrandFavicon();
    _ensureFeatureNavButton();
    _wirePageLinkTransitions();
    _ensureThemeToggle();
    _applyTheme(_preferredTheme());
    _showPostLoginIntro();
});

// Logout function
async function logout() {
    if (confirm('Are you sure you want to logout?')) {
        try {
            const response = await fetch('/api/logout', { method: 'POST' });
            if (response.ok) {
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
