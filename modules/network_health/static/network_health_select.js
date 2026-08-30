(function () {
    'use strict';

    function selectedAttr(containerId, attr, fallback) {
        const grid = document.getElementById(containerId);
        const sel = grid && grid.querySelector('.selected, [aria-pressed="true"]');
        if (sel && sel.getAttribute('data-' + attr)) {
            return sel.getAttribute('data-' + attr);
        }
        return fallback;
    }

    function bindCardGroup(containerId, attr, onSelect) {
        const grid = document.getElementById(containerId);
        if (!grid) return;
        grid.addEventListener('click', function (ev) {
            const card = ev.target.closest('[data-' + attr + ']');
            if (!card) return;
            grid.querySelectorAll('[data-' + attr + ']').forEach(function (el) {
                const sel = el === card;
                el.classList.toggle('selected', sel);
                el.setAttribute('aria-pressed', sel ? 'true' : 'false');
            });
            onSelect(card.getAttribute('data-' + attr));
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        let vendor = document.body.dataset.defaultVendor || selectedAttr('nh-vendor-grid', 'vendor', 'nokia');
        let rat = document.body.dataset.defaultRat || selectedAttr('nh-rat-grid', 'rat', '3G');

        bindCardGroup('nh-vendor-grid', 'vendor', function (v) { vendor = v; });
        bindCardGroup('nh-rat-grid', 'rat', function (r) { rat = r; });

        document.getElementById('nh-continue-btn')?.addEventListener('click', function () {
            vendor = selectedAttr('nh-vendor-grid', 'vendor', vendor);
            rat = selectedAttr('nh-rat-grid', 'rat', rat);
            window.location.href = '/network-health/view?vendor=' +
                encodeURIComponent(vendor) + '&rat=' + encodeURIComponent(rat);
        });
    });
})();
