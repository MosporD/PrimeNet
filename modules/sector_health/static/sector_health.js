/**
 * Sector Health — 2G/3G/5G counts; LTE pie = band share of LTE sectors (L35 excluded).
 */

let _allAreas = [];
let _loadTimer = null;
const _charts = {};

const SH_BAND_COLOR = '#6c3483';
const SH_OTHER_LTE_COLOR = '#dfe6e9';
const SH_OTHER_LTE_BORDER = '#bdc3c7';

const SH_PIE_OPTIONS = {
    responsive: true,
    maintainAspectRatio: true,
    plugins: {
        legend: {
            position: 'bottom',
            labels: { boxWidth: 10, padding: 8, font: { size: 11 } },
        },
        tooltip: {
            callbacks: {
                label(ctx) {
                    const total = ctx.dataset.data.reduce((a, b) => a + b, 0);
                    const pct = total ? ((ctx.raw / total) * 100).toFixed(1) : '0';
                    return `${ctx.label}: ${Number(ctx.raw).toLocaleString()} (${pct}%)`;
                },
            },
        },
    },
};

function esc(v) {
    return String(v ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function destroyCharts() {
    Object.keys(_charts).forEach((id) => {
        try { _charts[id].destroy(); } catch (_) { /* ignore */ }
        delete _charts[id];
    });
}

function createLteBandPie(canvasId, bandLabel, withBand, withoutBand) {
    if (typeof Chart === 'undefined') return null;
    const canvas = document.getElementById(canvasId);
    if (!canvas) return null;

    const has = Math.max(0, Number(withBand) || 0);
    const other = Math.max(0, Number(withoutBand) || 0);
    const total = has + other;

    if (_charts[canvasId]) {
        _charts[canvasId].destroy();
        delete _charts[canvasId];
    }

    if (total === 0) {
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        return null;
    }

    const chart = new Chart(canvas.getContext('2d'), {
        type: 'pie',
        data: {
            labels: [`With ${bandLabel}`, 'Other LTE'],
            datasets: [{
                data: [has, other],
                backgroundColor: [SH_BAND_COLOR, SH_OTHER_LTE_COLOR],
                borderColor: ['#512e5f', SH_OTHER_LTE_BORDER],
                borderWidth: 1,
            }],
        },
        options: SH_PIE_OPTIONS,
    });
    _charts[canvasId] = chart;
    return chart;
}

function shortBandLabel(techBand) {
    const s = String(techBand || '');
    const idx = s.indexOf(' / ');
    return idx >= 0 ? s.slice(idx + 3) : s;
}

function buildQueryParams() {
    const p = new URLSearchParams();
    const area = document.getElementById('sh-area')?.value || '';
    const rat = document.getElementById('sh-rat')?.value || '';
    const q = document.getElementById('sh-search')?.value?.trim() || '';
    if (area) p.set('area', area);
    if (rat) p.set('rat', rat);
    if (q) p.set('q', q);
    return p;
}

function renderSummary(data) {
    const el = document.getElementById('sh-summary');
    if (!el) return;

    destroyCharts();

    const hs = data.health_summary || {};
    const total = data.sector_count ?? 0;
    const shown = data.filtered_sector_count ?? 0;
    const lteTotal = hs.lte_sector_count ?? 0;
    const ratCounts = hs.rat_counts || {};
    const lteLayers = hs.lte_layer_pct || [];
    const excluded = (data.lte_excluded_bands || []).join(', ');

    const ratCountsHtml = ['2G', '3G', '5G'].map((rat) => {
        const n = (ratCounts[rat] || {}).sector_count ?? 0;
        return `
        <div class="sh-count-box">
            <div class="sh-count-value">${n.toLocaleString()}</div>
            <div class="sh-count-label">${rat} sectors</div>
        </div>`;
    }).join('');

    const lteCharts = lteLayers.length
        ? lteLayers.map((layer, i) => {
            const pct = layer.layer_pct ?? 0;
            const n = layer.sector_count ?? 0;
            const other = layer.without_count ?? Math.max(0, lteTotal - n);
            const full = layer.tech_band || '';
            const band = shortBandLabel(full);
            const id = `sh-chart-lte-${i}`;
            return `
        <div class="sh-chart-box sh-chart-box--lte">
            <div class="sh-chart-title" title="${esc(full)}">${esc(band)}</div>
            <div class="sh-chart-subtitle">% of LTE sectors (${lteTotal.toLocaleString()})</div>
            <div class="sh-chart-canvas-wrap">
                <canvas id="${id}" aria-label="${esc(band)} share of LTE sectors"></canvas>
            </div>
            <div class="sh-chart-caption">${pct}% · ${n.toLocaleString()} with · ${other.toLocaleString()} other LTE</div>
        </div>`;
        }).join('')
        : '<p class="sh-empty">No LTE bands in scope.</p>';

    const excludedNote = excluded
        ? `<p class="sh-scope-note">LTE totals exclude: ${esc(excluded)}</p>`
        : '';

    el.innerHTML = `
        <div class="sh-overview">
            <span><strong>${total.toLocaleString()}</strong> total sectors</span>
            <span><strong>${shown.toLocaleString()}</strong> in view</span>
            <span><strong>${lteTotal.toLocaleString()}</strong> LTE sectors in view</span>
        </div>
        ${excludedNote}
        <div class="sh-summary-block">
            <div class="sh-summary-heading">2G / 3G / 5G — sector count</div>
            <div class="sh-counts-row">${ratCountsHtml}</div>
        </div>
        <div class="sh-summary-block sh-summary-block--lte">
            <div class="sh-summary-heading">LTE — layer % per band (of LTE sectors in view)</div>
            <div class="sh-charts-grid">${lteCharts}</div>
        </div>
    `;
    el.hidden = false;

    if (typeof Chart === 'undefined') {
        const status = document.getElementById('sh-status');
        if (status) status.textContent += ' Chart.js failed to load — refresh the page.';
        return;
    }

    requestAnimationFrame(() => {
        lteLayers.forEach((layer, i) => {
            const band = shortBandLabel(layer.tech_band || '');
            createLteBandPie(
                `sh-chart-lte-${i}`,
                band,
                layer.sector_count ?? 0,
                layer.without_count ?? Math.max(0, lteTotal - (layer.sector_count ?? 0)),
            );
        });
    });
}

function populateAreaFilter(areas) {
    const sel = document.getElementById('sh-area');
    if (!sel || !areas?.length) return;
    if (_allAreas.length === areas.length && _allAreas.every((a, i) => a === areas[i])) return;
    _allAreas = areas;
    const cur = sel.value;
    sel.innerHTML = '<option value="">All areas</option>' + areas.map(a =>
        `<option value="${esc(a)}">${esc(a)}</option>`
    ).join('');
    if (cur) sel.value = cur;
}

async function loadSectorHealth() {
    const status = document.getElementById('sh-status');
    if (status) {
        status.className = 'sh-status';
        status.textContent = 'Loading sector coverage…';
    }

    try {
        const res = await fetch(`/api/sector-health/data?${buildQueryParams()}`);
        const data = await res.json();
        if (!data.success) {
            throw new Error(data.error || 'Failed to load data');
        }
        populateAreaFilter(data.areas || []);
        renderSummary(data);
        const gen = data.generated_at ? new Date(data.generated_at).toLocaleString() : '';
        const lteN = (data.health_summary || {}).lte_sector_count ?? 0;
        if (status) {
            status.textContent = `Coverage snapshot${gen ? ` · ${gen}` : ''} · ${(data.filtered_sector_count ?? 0).toLocaleString()} in view · ${lteN.toLocaleString()} LTE (excl. L35).`;
        }
    } catch (e) {
        destroyCharts();
        if (status) {
            status.className = 'sh-status error';
            status.textContent = e.message || 'Load failed';
        }
        document.getElementById('sh-summary')?.setAttribute('hidden', '');
    }
}

function scheduleLoad() {
    clearTimeout(_loadTimer);
    _loadTimer = setTimeout(loadSectorHealth, 280);
}

document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('sh-refresh')?.addEventListener('click', loadSectorHealth);
    document.getElementById('sh-area')?.addEventListener('change', scheduleLoad);
    document.getElementById('sh-rat')?.addEventListener('change', scheduleLoad);
    document.getElementById('sh-search')?.addEventListener('input', scheduleLoad);
    loadSectorHealth();
});
