(function () {
    'use strict';

    const vendor = document.body.dataset.vendor || 'nokia';
    const rat = document.body.dataset.rat || '3G';
    let kpiList = [];
    let dailyChart = null;
    let hourlyChart = null;

    function esc(s) {
        return String(s ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/"/g, '&quot;');
    }

    function openDetail(kpi) {
        const qs = new URLSearchParams({ vendor, rat, kpi: kpi || '' });
        window.location.href = '/network-health/view?' + qs.toString();
    }

    async function loadHub() {
        const grid = document.getElementById('nh-hub-kpi-grid');
        try {
            const [kpiRes, metaRes] = await Promise.all([
                fetch(`/api/network-health/kpis?vendor=${encodeURIComponent(vendor)}&rat=${encodeURIComponent(rat)}`),
                fetch(`/api/network-health/meta?vendor=${encodeURIComponent(vendor)}&rat=${encodeURIComponent(rat)}`),
            ]);
            const kpiData = await kpiRes.json();
            const metaData = await metaRes.json().catch(() => ({}));

            if (!kpiData.success) {
                grid.innerHTML = `<p class="nh-hub-loading">${esc(kpiData.error || 'Failed to load KPIs')}</p>`;
                return;
            }

            const preferred = Array.isArray(kpiData.precomputed_kpis) ? kpiData.precomputed_kpis : [];
            const columns = Array.isArray(kpiData.columns) ? kpiData.columns : [];
            const ordered = [];
            preferred.forEach((k) => { if (columns.includes(k) && !ordered.includes(k)) ordered.push(k); });
            columns.forEach((k) => { if (!ordered.includes(k)) ordered.push(k); });
            kpiList = ordered.slice(0, 24);

            if (!kpiList.length) {
                grid.innerHTML = '<p class="nh-hub-loading">No KPIs available for this vendor / RAT yet.</p>';
            } else {
                grid.innerHTML = kpiList.map((name) =>
                    `<button type="button" class="nh-hub-kpi-btn" data-kpi="${esc(name)}" title="${esc(name)}">${esc(name)}</button>`
                ).join('');
            }

            const dailyEl = document.getElementById('nh-hub-daily-date');
            const hourlyEl = document.getElementById('nh-hub-hourly-date');
            if (dailyEl) dailyEl.textContent = metaData.daily_latest || metaData.built_at || '—';
            if (hourlyEl) hourlyEl.textContent = metaData.hourly_latest || '—';

            const sel = document.getElementById('nh-checker-kpi');
            if (sel) {
                sel.innerHTML = kpiList.map((n) => `<option value="${esc(n)}">${esc(n)}</option>`).join('');
            }
        } catch (e) {
            grid.innerHTML = `<p class="nh-hub-loading">${esc(e.message || 'Network error')}</p>`;
        }
    }

    function setCheckerOpen(open) {
        const modal = document.getElementById('nh-checker-modal');
        if (!modal) return;
        modal.hidden = !open;
        if (open) document.getElementById('nh-checker-q')?.focus();
    }

    function destroyCharts() {
        if (dailyChart) { try { dailyChart.destroy(); } catch (_) {} dailyChart = null; }
        if (hourlyChart) { try { hourlyChart.destroy(); } catch (_) {} hourlyChart = null; }
    }

    function renderTrend(canvasId, labels, values, label) {
        const canvas = document.getElementById(canvasId);
        if (!canvas || typeof Chart === 'undefined') return null;
        return new Chart(canvas.getContext('2d'), {
            type: 'line',
            data: {
                labels: labels || [],
                datasets: [{
                    label: label || 'KPI',
                    data: values || [],
                    borderColor: '#6d95b3',
                    backgroundColor: 'rgba(127,166,194,0.15)',
                    tension: 0.2,
                    pointRadius: 2,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: { x: { ticks: { maxTicksLimit: 6 } } },
            },
        });
    }

    async function runCellChecker() {
        const cell = (document.getElementById('nh-checker-q')?.value || '').trim();
        const kpi = document.getElementById('nh-checker-kpi')?.value || '';
        const status = document.getElementById('nh-checker-status');
        if (!cell || !kpi) {
            if (status) status.textContent = 'Enter a cell name and choose a KPI.';
            return;
        }
        if (status) status.textContent = 'Loading…';
        destroyCharts();
        try {
            const qs = new URLSearchParams({ vendor, rat, cell_name: cell, kpi });
            const res = await fetch('/api/network-health/cell-trend?' + qs.toString());
            const data = await res.json();
            if (!data.success) {
                if (status) status.textContent = data.error || 'No trend data';
                return;
            }
            if (status) status.textContent = data.cell_name || cell;
            const dailyRows = Array.isArray(data.daily) ? data.daily : [];
            const hourlyRows = Array.isArray(data.hourly) ? data.hourly : [];
            dailyChart = renderTrend(
                'nh-checker-daily',
                dailyRows.map((r) => r.day || r.timestamp || ''),
                dailyRows.map((r) => r.value),
                'Daily',
            );
            hourlyChart = renderTrend(
                'nh-checker-hourly',
                hourlyRows.map((r) => r.timestamp || r.day || ''),
                hourlyRows.map((r) => r.value),
                'Hourly',
            );
        } catch (e) {
            if (status) status.textContent = e.message || 'Network error';
        }
    }

    document.addEventListener('DOMContentLoaded', function () {
        document.getElementById('nh-hub-kpi-grid')?.addEventListener('click', function (ev) {
            const btn = ev.target.closest('[data-kpi]');
            if (!btn) return;
            openDetail(btn.getAttribute('data-kpi'));
        });
        document.getElementById('nh-hub-cell-checker')?.addEventListener('click', () => setCheckerOpen(true));
        document.getElementById('nh-checker-close')?.addEventListener('click', () => setCheckerOpen(false));
        document.getElementById('nh-checker-modal')?.addEventListener('click', function (ev) {
            if (ev.target === ev.currentTarget) setCheckerOpen(false);
        });
        document.getElementById('nh-checker-go')?.addEventListener('click', runCellChecker);
        document.getElementById('nh-checker-q')?.addEventListener('keydown', function (ev) {
            if (ev.key === 'Enter') runCellChecker();
        });
        loadHub();
    });
})();
