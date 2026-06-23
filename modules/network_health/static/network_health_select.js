(function () {
    'use strict';

    let vendor = '{{ default_vendor }}';
    let rat = '{{ default_rat }}';

    function bindCardGroup(containerId, attr, onSelect) {
        const grid = document.getElementById(containerId);
        if (!grid) return;
        grid.addEventListener('click', function (ev) {
            const card = ev.target.closest('[data-' + attr + ']');
            if (!card) return;
            const value = card.getAttribute('data-' + attr);
            grid.querySelectorAll('[data-' + attr + ']').forEach(function (el) {
                const sel = el === card;
                el.classList.toggle('selected', sel);
                el.setAttribute('aria-pressed', sel ? 'true' : 'false');
            });
            onSelect(value);
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        document.querySelectorAll('.nh-select-lead').forEach(function (el) {
            el.remove();
        });
        bindCardGroup('nh-vendor-grid', 'vendor', function (v) { vendor = v; });
        bindCardGroup('nh-rat-grid', 'rat', function (r) { rat = r; });

        document.getElementById('nh-continue-btn')?.addEventListener('click', function () {
            const url = '/network-health/view?vendor=' + encodeURIComponent(vendor) +
                '&rat=' + encodeURIComponent(rat);
            window.location.href = url;
        });
    });
})();
