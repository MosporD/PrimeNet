(function () {
    const body = document.body;
    const nokiaConfigured = body.dataset.nokiaConfigured === 'true';
    const huaweiConfigured = body.dataset.huaweiConfigured === 'true';

    let vendor = 'nokia';
    let moClasses = [];
    let moCatalog = new Map();
    let parametersByMo = new Map();
    let currentRows = [];
    let lastExportId = null;

    const els = {
        scope: document.getElementById('audit-scope'),
        confId: document.getElementById('audit-conf-id'),
        area: document.getElementById('audit-area'),
        moSearch: document.getElementById('audit-mo-search'),
        mo: document.getElementById('audit-mo'),
        paramSearch: document.getElementById('audit-param-search'),
        param: document.getElementById('audit-param'),
        scan: document.getElementById('audit-scan'),
        status: document.getElementById('audit-status'),
        summary: document.getElementById('audit-summary'),
        distribution: document.getElementById('audit-distribution'),
        distributionBars: document.getElementById('distribution-bars'),
        distributionNote: document.getElementById('distribution-note'),
        results: document.getElementById('audit-results'),
        resultsBody: document.getElementById('audit-results-body'),
        resultsFilter: document.getElementById('audit-results-filter'),
        warnings: document.getElementById('audit-warnings'),
        warningsList: document.getElementById('audit-warnings-list'),
        summaryNes: document.getElementById('summary-nes'),
        summaryObjects: document.getElementById('summary-objects'),
        summaryDistinct: document.getElementById('summary-distinct'),
        summaryDominant: document.getElementById('summary-dominant'),
        summaryStatus: document.getElementById('summary-status'),
        exportBtn: document.getElementById('audit-export'),
    };

    function escapeHtml(value) {
        return String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function setStatus(message, kind) {
        els.status.hidden = !message;
        els.status.textContent = message || '';
        els.status.className = `cm-audit-status${kind ? ` is-${kind}` : ''}`;
    }

    function updateScanButton() {
        const ready = Boolean(els.mo.value && els.param.value);
        els.scan.disabled = !ready;
    }

    function scopeLevel() {
        return vendor === 'nokia' ? (els.scope.value || 'MRBTS') : 'ENODEB';
    }

    async function loadAreas() {
        els.area.innerHTML = '<option value="all">All areas</option>';
        try {
            const res = await fetch(`/api/cm-parameter-audit/areas?vendor=${encodeURIComponent(vendor)}&scope_level=${encodeURIComponent(scopeLevel())}`);
            const data = await res.json();
            if (!data.success) {
                return;
            }
            (data.areas || []).forEach((item) => {
                const option = document.createElement('option');
                option.value = item.area;
                option.textContent = `${item.area} (${item.site_count})`;
                els.area.appendChild(option);
            });
        } catch (_err) {
            /* optional */
        }
    }

    function renderMoOptions(filterText) {
        const term = (filterText || '').trim().toLowerCase();
        const filtered = moClasses.filter((item) => {
            const hay = `${item.id} ${item.label || ''} ${item.version || ''}`.toLowerCase();
            return !term || hay.includes(term);
        });
        els.mo.innerHTML = '<option value="">Select MO class</option>';
        filtered.forEach((item) => {
            const option = document.createElement('option');
            option.value = item.id;
            option.dataset.version = item.version || '';
            option.textContent = item.label ? `${item.id} — ${item.label}` : item.id;
            els.mo.appendChild(option);
        });
        els.mo.disabled = !filtered.length;
    }

    function paramAbbreviation(item) {
        if (typeof item === 'string') {
            return item;
        }
        if (vendor === 'huawei') {
            return item.param_id || item.id || item.name || '';
        }
        return item.id || item.name || '';
    }

    function paramLabel(item) {
        return paramAbbreviation(item);
    }

    function paramSearchText(item) {
        const abbr = paramAbbreviation(item);
        const name = item.name || item.id || '';
        const desc = item.description || '';
        return `${abbr} ${name} ${desc}`.trim();
    }

    function renderParamOptions(params, filterText) {
        const term = (filterText || '').trim().toLowerCase();
        const filtered = (params || []).filter((item) => {
            const hay = paramSearchText(item).toLowerCase();
            return !term || hay.includes(term);
        });
        els.param.innerHTML = '<option value="">Select parameter</option>';
        filtered.forEach((item) => {
            const abbr = paramAbbreviation(item);
            const option = document.createElement('option');
            option.value = abbr;
            option.textContent = paramLabel(item);
            els.param.appendChild(option);
        });
        els.param.disabled = !filtered.length;
        els.paramSearch.disabled = !params.length;
    }

    async function loadMoClasses() {
        moClasses = [];
        moCatalog = new Map();
        parametersByMo = new Map();
        els.mo.disabled = true;
        els.param.disabled = true;
        els.paramSearch.disabled = true;
        els.param.innerHTML = '<option value="">Select MO class first</option>';
        updateScanButton();

        if (vendor === 'nokia' && !nokiaConfigured) {
            setStatus('Nokia CM credentials are not configured on the server.', 'error');
            return;
        }
        if (vendor === 'huawei' && !huaweiConfigured) {
            setStatus('Huawei CM credentials are not configured on the server.', 'error');
            return;
        }

        setStatus('Loading MO classes from CM API…', 'loading');
        try {
            let items = [];
            if (vendor === 'nokia') {
                const res = await fetch(`/api/cm-extractor/nokia/mo-classes?scope=${encodeURIComponent(scopeLevel())}`);
                const data = await res.json();
                if (!data.success) {
                    throw new Error(data.error || 'Failed to load Nokia MO classes');
                }
                items = data.mo_classes || [];
            } else {
                const res = await fetch('/api/cm-extractor/huawei/mo-objects');
                const data = await res.json();
                if (!data.success) {
                    throw new Error(data.error || 'Failed to load Huawei MO objects');
                }
                items = (data.mo_objects || []).map((item) => ({
                    id: item.id || item.mo_id,
                    label: item.label || item.name || item.id,
                    version: '',
                }));
            }
            moClasses = items;
            items.forEach((item) => moCatalog.set(item.id, item));
            renderMoOptions(els.moSearch.value);
            setStatus('');
        } catch (err) {
            setStatus(err.message || 'Failed to load MO classes', 'error');
        }
    }

    async function loadParameters(moId) {
        parametersByMo.set(moId, []);
        renderParamOptions([], els.paramSearch.value);
        updateScanButton();
        if (!moId) {
            return;
        }

        setStatus('Loading parameters…', 'loading');
        try {
            let params = [];
            if (vendor === 'nokia') {
                const mo = moCatalog.get(moId) || {};
                const res = await fetch('/api/cm-extractor/nokia/parameters', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        mo_classes: [{ mo_class_id: moId, version: mo.version || '' }],
                    }),
                });
                const data = await res.json();
                if (!data.success) {
                    throw new Error(data.error || 'Failed to load parameters');
                }
                params = (data.parameters && data.parameters[moId]) || [];
            } else {
                const res = await fetch('/api/cm-extractor/huawei/parameters', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ mo_ids: [moId] }),
                });
                const data = await res.json();
                if (!data.success) {
                    throw new Error(data.error || 'Failed to load parameters');
                }
                params = (data.parameters && data.parameters[moId.toUpperCase()]) || [];
            }
            parametersByMo.set(moId, params);
            renderParamOptions(params, els.paramSearch.value);
            setStatus('');
        } catch (err) {
            setStatus(err.message || 'Failed to load parameters', 'error');
        }
    }

    function renderDistribution(items, summary) {
        if (!items || !items.length) {
            els.distribution.hidden = true;
            if (els.distributionNote) {
                els.distributionNote.hidden = true;
            }
            return;
        }
        els.distribution.hidden = false;
        const distinct = Number(summary?.distinct_values || items.length);
        const capped = distinct > items.length;
        if (els.distributionNote) {
            els.distributionNote.hidden = !capped;
            els.distributionNote.textContent = capped
                ? `Showing top ${items.length} of ${distinct} distinct values. Export includes every value.`
                : '';
        }
        els.distributionBars.innerHTML = items.map((item) => `
            <div class="distribution-row">
                <div class="distribution-label" title="${escapeHtml(item.value)}">${escapeHtml(item.value || '(empty)')}</div>
                <div class="distribution-track">
                    <div class="distribution-fill" style="width:${Math.max(4, item.percent)}%"></div>
                </div>
                <div class="distribution-meta">${escapeHtml(item.count)} (${escapeHtml(item.percent)}%)</div>
            </div>
        `).join('');
    }

    function renderRows(rows) {
        if (!rows.length) {
            els.resultsBody.innerHTML = '<tr><td colspan="5" class="empty-row">No objects returned for this parameter in the selected scope.</td></tr>';
            return;
        }
        els.resultsBody.innerHTML = rows.map((row) => {
            const objectLabel = row.cell_name || row.object || row.dn || '-';
            const statusClass = row.matches_dominant ? 'consistent' : 'variant';
            const statusLabel = row.matches_dominant ? 'Dominant' : 'Variant';
            return `
                <tr>
                    <td>${escapeHtml(row.ne)}</td>
                    <td>${escapeHtml(row.area || '-')}</td>
                    <td title="${escapeHtml(row.dn || row.object || '')}">${escapeHtml(objectLabel)}</td>
                    <td><code>${escapeHtml(row.value || '(empty)')}</code></td>
                    <td><span class="value-status ${statusClass}">${statusLabel}</span></td>
                </tr>
            `;
        }).join('');
    }

    function applyResultsFilter() {
        const term = (els.resultsFilter.value || '').trim().toLowerCase();
        if (!term) {
            renderRows(currentRows);
            return;
        }
        const filtered = currentRows.filter((row) => {
            const hay = [
                row.ne, row.area, row.cell_name, row.object, row.dn, row.value,
            ].join(' ').toLowerCase();
            return hay.includes(term);
        });
        renderRows(filtered);
    }

    function showWarnings(warnings, note) {
        const items = [...(warnings || [])];
        if (note) {
            items.unshift(note);
        }
        if (!items.length) {
            els.warnings.hidden = true;
            els.warningsList.innerHTML = '';
            return;
        }
        els.warnings.hidden = false;
        els.warningsList.innerHTML = items.map((item) => `<li>${escapeHtml(item)}</li>`).join('');
    }

    function renderResult(payload) {
        const summary = payload.summary || {};
        const scope = payload.ne_scope || {};

        els.summary.hidden = false;
        els.results.hidden = false;

        els.summaryNes.textContent = `${scope.queried || 0}${scope.truncated ? ` / ${scope.available}` : ''}`;
        els.summaryObjects.textContent = summary.object_count ?? 0;
        els.summaryDistinct.textContent = summary.distinct_values ?? 0;
        els.summaryDominant.textContent = summary.most_common_value || '(empty)';
        els.summaryStatus.textContent = summary.status || 'consistent';
        els.summaryStatus.className = `status-pill status-${escapeHtml(summary.status || 'consistent')}`;

        renderDistribution(summary.value_distribution || [], summary);
        currentRows = payload.rows || [];
        lastExportId = payload.export_id || null;
        if (els.exportBtn) {
            els.exportBtn.disabled = !lastExportId;
        }
        applyResultsFilter();
        showWarnings(payload.warnings, payload.note);
    }

    async function exportReport() {
        if (!lastExportId) {
            setStatus('Run a live scan before exporting.', 'error');
            return;
        }

        if (els.exportBtn) {
            els.exportBtn.disabled = true;
        }
        setStatus('Building Excel report…', 'loading');
        try {
            const res = await fetch(`/api/cm-parameter-audit/export/${encodeURIComponent(lastExportId)}`, {
                credentials: 'same-origin',
            });
            if (!res.ok) {
                let message = 'Export failed';
                try {
                    const data = await res.json();
                    message = data.error || message;
                } catch (_err) {
                    /* binary or empty body */
                }
                throw new Error(message);
            }
            const blob = await res.blob();
            const disposition = res.headers.get('Content-Disposition') || '';
            const match = disposition.match(/filename=\"?([^\";]+)\"?/i);
            const filename = match ? match[1] : 'CM_Parameter_Audit.xlsx';
            const url = URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = url;
            link.download = filename;
            document.body.appendChild(link);
            link.click();
            link.remove();
            URL.revokeObjectURL(url);
            setStatus('Excel report downloaded.', 'success');
        } catch (err) {
            setStatus(err.message || 'Export failed', 'error');
        } finally {
            if (els.exportBtn) {
                els.exportBtn.disabled = !lastExportId;
            }
        }
    }

    async function scanNetwork() {
        const moId = els.mo.value;
        const parameter = els.param.value;
        const mo = moCatalog.get(moId) || {};
        if (!moId || !parameter) {
            return;
        }

        els.scan.disabled = true;
        const modeHint = vendor === 'nokia'
            ? 'one network-wide CM query'
            : 'chunked U2020 MML';
        setStatus(`Querying live CM for ${parameter} (${modeHint})…`, 'loading');
        els.summary.hidden = true;
        els.distribution.hidden = true;
        els.results.hidden = true;
        els.warnings.hidden = true;
        lastExportId = null;
        if (els.exportBtn) {
            els.exportBtn.disabled = true;
        }

        try {
            const res = await fetch('/api/cm-parameter-audit/live', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    vendor,
                    scope_level: scopeLevel(),
                    mo_class: moId,
                    mo_version: mo.version || '',
                    parameter,
                    conf_id: Number(els.confId.value || 1),
                    area: els.area.value || 'all',
                }),
            });
            const data = await res.json();
            if (!data.success) {
                throw new Error(data.error || 'Live scan failed');
            }
            renderResult(data);
            setStatus(
                `Live scan complete — ${data.summary?.object_count || 0} object(s), `
                + `${data.summary?.ne_count || 0} NE(s) `
                + `(${data.query_mode || 'live'}).`,
                'success',
            );
        } catch (err) {
            setStatus(err.message || 'Live scan failed', 'error');
        } finally {
            updateScanButton();
        }
    }

    function setVendor(nextVendor) {
        vendor = nextVendor;
        document.querySelectorAll('.vendor-tab').forEach((tab) => {
            tab.classList.toggle('active', tab.dataset.vendor === vendor);
        });
        const nokiaScope = document.getElementById('nokia-scope-block');
        const huaweiScope = document.getElementById('huawei-scope-block');
        if (nokiaScope) {
            nokiaScope.hidden = vendor !== 'nokia';
        }
        if (huaweiScope) {
            huaweiScope.hidden = vendor !== 'huawei';
        }
        loadAreas();
        loadMoClasses();
    }

    document.querySelectorAll('.vendor-tab').forEach((tab) => {
        tab.addEventListener('click', () => setVendor(tab.dataset.vendor));
    });

    els.scope.addEventListener('change', () => {
        loadAreas();
        loadMoClasses();
    });

    els.area.addEventListener('change', updateScanButton);

    els.moSearch.addEventListener('input', () => renderMoOptions(els.moSearch.value));

    els.mo.addEventListener('change', () => {
        loadParameters(els.mo.value);
        updateScanButton();
    });

    els.paramSearch.addEventListener('input', () => {
        renderParamOptions(parametersByMo.get(els.mo.value) || [], els.paramSearch.value);
    });

    els.param.addEventListener('change', updateScanButton);
    els.scan.addEventListener('click', scanNetwork);
    if (els.exportBtn) {
        els.exportBtn.addEventListener('click', exportReport);
    }
    els.resultsFilter.addEventListener('input', applyResultsFilter);

    setVendor('nokia');
})();
