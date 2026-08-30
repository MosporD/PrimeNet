(function () {
    'use strict';

    function esc(s) {
        if (window.escapeHtml) return window.escapeHtml(s);
        const d = document.createElement('div');
        d.textContent = s == null ? '' : String(s);
        return d.innerHTML;
    }

    function sevClass(sev) {
        const s = String(sev || '').toLowerCase();
        if (s === 'high') return 'son-sev-high';
        if (s === 'medium') return 'son-sev-medium';
        return 'son-sev-low';
    }

    function queryParams() {
        const cat = document.getElementById('filter-category')?.value || 'all';
        const sev = document.getElementById('filter-severity')?.value || 'all';
        const area = document.getElementById('filter-area')?.value || 'all';
        const ven = document.getElementById('filter-vendor')?.value || 'all';
        const tech = document.getElementById('filter-technology')?.value || 'all';
        const p = new URLSearchParams();
        if (cat !== 'all') p.set('category', cat);
        if (sev !== 'all') p.set('severity', sev);
        if (area !== 'all') p.set('area', area);
        if (ven !== 'all') p.set('vendor', ven);
        if (tech !== 'all') p.set('technology', tech);
        p.set('limit', '100');
        return p.toString();
    }

    function mlLine(ml) {
        if (!ml || ml.disabled) return 'ML off (SON_DISABLE_ML)';
        if (!ml.available) return 'ML store empty — showing week-over-week rules only';
        const age = ml.built_at || '—';
        const extra = ml.is_stale ? ' (stale vs PM)' : '';
        return 'ML ' + (ml.score_count || 0) + ' cells · built ' + age + extra;
    }

    async function loadAreas() {
        const sel = document.getElementById('filter-area');
        if (!sel) return;
        try {
            const res = await fetch('/api/son/areas', { credentials: 'same-origin' });
            const data = await res.json();
            if (!data.success) return;
            (data.areas || []).forEach(function (a) {
                const opt = document.createElement('option');
                opt.value = a;
                opt.textContent = a;
                sel.appendChild(opt);
            });
        } catch (e) { /* ignore */ }
    }

    async function loadSummary() {
        const res = await fetch('/api/son/summary?' + queryParams(), { credentials: 'same-origin' });
        const data = await res.json();
        if (!data.success) throw new Error(data.error || 'Summary failed');
        const s = data.summary || {};
        document.getElementById('sum-cluster').textContent = s.cluster ?? 0;
        const anom = document.getElementById('sum-anomaly');
        if (anom) anom.textContent = s.anomaly ?? 0;
        const topo = document.getElementById('sum-topology');
        if (topo) topo.textContent = s.topology ?? 0;
        document.getElementById('sum-degraded').textContent = s.degraded_cells ?? 0;
        document.getElementById('sum-total').textContent = s.total ?? 0;
        document.getElementById('son-generated').textContent =
            'Generated: ' + (data.generated_at || '—') +
            ' · Daily PM vs 7-day avg · ' + mlLine(data.ml);
    }

    async function loadRecommendations() {
        const tbody = document.getElementById('son-tbody');
        tbody.innerHTML = '<tr><td colspan="7" class="son-empty">Loading…</td></tr>';
        const res = await fetch('/api/son/recommendations?' + queryParams(), { credentials: 'same-origin' });
        const data = await res.json();
        if (!data.success) {
            tbody.innerHTML = '<tr><td colspan="7" class="son-empty">' + esc(data.error || 'Failed') + '</td></tr>';
            return;
        }
        const rows = data.recommendations || [];
        if (!rows.length) {
            tbody.innerHTML = '<tr><td colspan="7" class="son-empty">No recommendations for current filters.</td></tr>';
            return;
        }
        tbody.innerHTML = rows.map(function (r) {
            const cellCount = (r.cells || []).length;
            const score = r.anomaly_score != null ? Number(r.anomaly_score).toFixed(0) : '—';
            return '<tr data-id="' + esc(r.id) + '">' +
                '<td class="' + sevClass(r.severity) + '">' + esc(r.severity) + '</td>' +
                '<td>' + esc(r.category) + '</td>' +
                '<td>' + esc(r.title) + '</td>' +
                '<td>' + esc(r.area || '—') + '</td>' +
                '<td>' + esc(cellCount) + '</td>' +
                '<td>' + esc(score) + '</td>' +
                '<td>' + esc(r.vendor) + '</td></tr>';
        }).join('');
        tbody.querySelectorAll('tr[data-id]').forEach(function (tr) {
            tr.addEventListener('click', function () {
                tbody.querySelectorAll('tr.selected').forEach(function (x) { x.classList.remove('selected'); });
                tr.classList.add('selected');
                showDetail(tr.getAttribute('data-id'));
            });
        });
    }

    async function sendFeedback(recId, label) {
        try {
            const res = await fetch('/api/son/feedback', {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ rec_id: recId, label: label })
            });
            const data = await res.json();
            const el = document.getElementById('son-feedback-status');
            if (el) el.textContent = data.success ? ('Saved: ' + label) : (data.error || 'Failed');
        } catch (e) {
            const el = document.getElementById('son-feedback-status');
            if (el) el.textContent = e.message || 'Failed';
        }
    }

    async function showDetail(id) {
        const placeholder = document.querySelector('.son-detail-placeholder');
        const body = document.getElementById('son-detail-body');
        if (!id) return;
        const res = await fetch('/api/son/recommendations/' + encodeURIComponent(id), { credentials: 'same-origin' });
        const data = await res.json();
        if (!data.success || !data.recommendation) {
            if (placeholder) placeholder.hidden = false;
            if (body) body.hidden = true;
            return;
        }
        const r = data.recommendation;
        if (placeholder) placeholder.hidden = true;
        if (body) {
            body.hidden = false;
            const links = (r.links || []).map(function (l) {
                return '<a href="' + esc(l.url) + '" target="_blank" rel="noopener">' + esc(l.label) + '</a>';
            }).join('');
            const ev = r.evidence || {};
            const causes = ev.cause_probs || {};
            const causeBits = Object.keys(causes).sort(function (a, b) {
                return (causes[b] || 0) - (causes[a] || 0);
            }).slice(0, 3).map(function (k) {
                return esc(k) + ' ' + Math.round((causes[k] || 0) * 100) + '%';
            }).join(' · ');
            const kpis = (ev.top_kpis || []).map(function (k) {
                return esc(k.kpi) + ' (' + esc(k.contribution) + ')';
            }).join(', ');
            body.innerHTML =
                '<p><strong>' + esc(r.title) + '</strong></p>' +
                '<p>' + esc(r.summary) + '</p>' +
                (causeBits ? '<p class="son-cause">Cause mix: ' + causeBits + '</p>' : '') +
                (kpis ? '<p>Top KPIs: ' + kpis + '</p>' : '') +
                '<p>Cells: ' + esc((r.cells || []).join(', ')) + '</p>' +
                '<div class="son-feedback">' +
                    '<button type="button" class="son-btn son-btn-primary" data-fb="up">Helpful</button> ' +
                    '<button type="button" class="son-btn son-btn-ghost son-btn-dark" data-fb="down">Not helpful</button>' +
                    '<span id="son-feedback-status" class="son-feedback-status"></span>' +
                '</div>' +
                '<pre class="son-evidence-pre">' + esc(JSON.stringify(ev, null, 2)) + '</pre>' +
                (links ? '<div class="son-detail-links">' + links + '</div>' : '');
            body.querySelectorAll('[data-fb]').forEach(function (btn) {
                btn.addEventListener('click', function () {
                    sendFeedback(r.id, btn.getAttribute('data-fb'));
                });
            });
        }
    }

    async function refreshCache() {
        const btn = document.getElementById('son-refresh-btn');
        if (btn) btn.disabled = true;
        try {
            const res = await fetch('/api/son/refresh', { method: 'POST', credentials: 'same-origin' });
            const data = await res.json();
            if (!data.success) alert(data.error || 'Refresh failed');
            await loadSummary();
            await loadRecommendations();
        } catch (e) {
            alert(e.message || 'Refresh failed');
        } finally {
            if (btn) btn.disabled = false;
        }
    }

    document.addEventListener('DOMContentLoaded', function () {
        loadAreas().then(function () {
            loadSummary().catch(function () {});
            loadRecommendations().catch(function () {});
        });

        document.getElementById('son-apply-filters')?.addEventListener('click', function () {
            loadSummary().catch(function () {});
            loadRecommendations().catch(function () {});
        });

        document.getElementById('son-refresh-btn')?.addEventListener('click', refreshCache);

        document.querySelectorAll('.son-summary-card[data-cat]').forEach(function (card) {
            card.addEventListener('click', function () {
                const cat = card.getAttribute('data-cat');
                const sel = document.getElementById('filter-category');
                if (sel && cat) {
                    if (cat.toLowerCase() === 'cluster') sel.value = 'Cluster';
                    else if (cat.toLowerCase() === 'anomaly') sel.value = 'Anomaly';
                    else if (cat.toLowerCase() === 'topology') sel.value = 'Topology';
                    else sel.value = cat;
                    loadSummary().catch(function () {});
                    loadRecommendations().catch(function () {});
                }
            });
        });
    });
})();
