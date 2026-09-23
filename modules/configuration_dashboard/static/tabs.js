(function () {
    'use strict';

    function activateTab(tab) {
        const want = tab === 'wncelg' ? 'wncelg' : 'hardware';
        document.querySelectorAll('.cd-tab').forEach(function (btn) {
            const active = btn.dataset.tab === want;
            btn.classList.toggle('active', active);
            btn.setAttribute('aria-selected', active ? 'true' : 'false');
        });
        document.querySelectorAll('.cd-tab-panel').forEach(function (panel) {
            const match = panel.id === 'panel-' + want;
            panel.hidden = !match;
        });
        document.body.dataset.activeTab = want;
        try {
            const url = new URL(window.location.href);
            url.searchParams.set('tab', want);
            window.history.replaceState({}, '', url.pathname + '?' + url.searchParams.toString());
        } catch (_err) {
            /* ignore */
        }
    }

    document.addEventListener('DOMContentLoaded', function () {
        document.querySelectorAll('.cd-tab').forEach(function (btn) {
            btn.addEventListener('click', function () {
                activateTab(btn.dataset.tab);
            });
        });
        const initial = document.body.dataset.activeTab || 'hardware';
        activateTab(initial);
    });
})();
