(function () {
    const body = document.body;
    const nokiaConfigured = body.dataset.nokiaConfigured === 'true';
    const huaweiConfigured = body.dataset.huaweiConfigured === 'true';
    const isAdmin = (body.dataset.userRole || '').trim().toLowerCase() === 'admin';

    let vendor = 'nokia';
    let moClasses = [];
    let moCatalog = new Map();
    let parametersByMo = new Map();
    let currentRows = [];
    let parameterSummaries = [];
    let lastExportId = null;
    let selectedMoId = '';
    let selectedParam = '';
    let entireMo = false;
    let selectedSummaryParam = '';
    let sortState = { key: null, dir: 1 };
    let paramSortState = { key: 'inconsistency_pct', dir: -1 };

    const els = {
        scope: document.getElementById('audit-scope'),
        confId: document.getElementById('audit-conf-id'),
        area: document.getElementById('audit-area'),
        moInput: document.getElementById('audit-mo-input'),
        moList: document.getElementById('audit-mo-list'),
        paramInput: document.getElementById('audit-param-input'),
        paramList: document.getElementById('audit-param-list'),
        entireMo: document.getElementById('audit-entire-mo'),
        scan: document.getElementById('audit-scan'),
        status: document.getElementById('audit-status'),
        summary: document.getElementById('audit-summary'),
        parameters: document.getElementById('audit-parameters'),
        paramBody: document.getElementById('audit-param-body'),
        parametersMeta: document.getElementById('audit-parameters-meta'),
        distribution: document.getElementById('audit-distribution'),
        distributionBars: document.getElementById('distribution-bars'),
        distributionNote: document.getElementById('distribution-note'),
        results: document.getElementById('audit-results'),
        resultsBody: document.getElementById('audit-results-body'),
        resultsFilter: document.getElementById('audit-results-filter'),
        resultsMeta: document.getElementById('audit-results-meta'),
        warnings: document.getElementById('audit-warnings'),
        warningsList: document.getElementById('audit-warnings-list'),
        summaryNes: document.getElementById('summary-nes'),
        summaryObjects: document.getElementById('summary-objects'),
        summaryDistinct: document.getElementById('summary-distinct'),
        summaryDominant: document.getElementById('summary-dominant'),
        summaryStatus: document.getElementById('summary-status'),
        exportBtn: document.getElementById('audit-export'),
        exportMoBtn: document.getElementById('audit-export-mo'),
        labelNes: document.querySelector('[data-summary-label="nes"]'),
        labelObjects: document.querySelector('[data-summary-label="objects"]'),
        labelDistinct: document.querySelector('[data-summary-label="distinct"]'),
        labelDominant: document.querySelector('[data-summary-label="dominant"]'),
        labelStatus: document.querySelector('[data-summary-label="status"]'),
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
        els.scan.disabled = !(selectedMoId && (entireMo || selectedParam));
    }

    function setEntireMo(enabled) {
        entireMo = !!enabled;
        if (els.entireMo) els.entireMo.checked = entireMo;
        if (els.paramInput) {
            els.paramInput.disabled = entireMo || !selectedMoId;
            els.paramInput.placeholder = entireMo
                ? 'All queryable parameters'
                : (selectedMoId ? 'Search and select parameter…' : 'Search and select parameter…');
        }
        if (entireMo) {
            els.paramList.hidden = true;
        }
        updateScanButton();
    }

    function scopeLevel() {
        return vendor === 'nokia' ? (els.scope.value || 'MRBTS') : 'ENODEB';
    }

    function closeComboLists(except) {
        [els.moList, els.paramList].forEach((list) => {
            if (list && list !== except) list.hidden = true;
        });
    }

    function renderComboList(listEl, items, { activeValue } = {}) {
        if (!items.length) {
            listEl.innerHTML = '<li class="combo-empty">No matches</li>';
            listEl.hidden = false;
            return;
        }
        listEl.innerHTML = items.map((item) => {
            const active = item.value === activeValue ? ' is-active' : '';
            return `<li class="combo-option${active}" role="option" data-value="${escapeHtml(item.value)}" title="${escapeHtml(item.title || item.label)}">${escapeHtml(item.label)}</li>`;
        }).join('');
        listEl.hidden = false;
    }

    function moComboItems(term) {
        const q = (term || '').trim().toLowerCase();
        return moClasses
            .filter((item) => {
                const hay = `${item.id} ${item.label || ''} ${item.version || ''}`.toLowerCase();
                return !q || hay.includes(q);
            })
            .slice(0, 80)
            .map((item) => ({
                value: item.id,
                label: item.label ? `${item.id} — ${item.label}` : item.id,
                title: item.version ? `${item.id} (${item.version})` : item.id,
            }));
    }

    function paramAbbreviation(item) {
        if (typeof item === 'string') return item;
        if (vendor === 'huawei') return item.param_id || item.id || item.name || '';
        return item.id || item.name || '';
    }

    function paramSearchText(item) {
        const abbr = paramAbbreviation(item);
        const name = item.name || item.id || '';
        const desc = item.description || '';
        return `${abbr} ${name} ${desc}`.trim();
    }

    function paramComboItems(term) {
        if (!selectedMoId) {
            const typed = (term || '').trim();
            if (!typed) return [];
            return [{
                value: typed,
                label: typed,
                title: 'Use this parameter name, then select an MO class',
            }];
        }
        const params = parametersByMo.get(selectedMoId) || [];
        const q = (term || '').trim().toLowerCase();
        return params
            .filter((item) => {
                const hay = paramSearchText(item).toLowerCase();
                return !q || hay.includes(q);
            })
            .slice(0, 100)
            .map((item) => {
                const abbr = paramAbbreviation(item);
                return {
                    value: abbr,
                    label: abbr,
                    title: paramSearchText(item),
                };
            });
    }

    function selectMo(moId) {
        selectedMoId = moId || '';
        const mo = moCatalog.get(selectedMoId);
        els.moInput.value = mo
            ? (mo.label ? `${mo.id} — ${mo.label}` : mo.id)
            : selectedMoId;
        els.moList.hidden = true;
        els.paramList.hidden = true;
        updateScanButton();
        if (selectedMoId) {
            loadParameters(selectedMoId);
        }
    }

    function selectParam(paramId) {
        selectedParam = (paramId || '').trim();
        els.paramInput.value = selectedParam;
        els.paramList.hidden = true;
        updateScanButton();
    }

    function commitTypedParam() {
        const typed = (els.paramInput.value || '').trim();
        if (!typed) {
            selectedParam = '';
            updateScanButton();
            return;
        }
        if (typed !== selectedParam) {
            selectParam(typed);
        }
    }

    async function loadAreas() {
        els.area.innerHTML = '<option value="all">All areas</option>';
        try {
            const res = await fetch(`/api/cm-parameter-audit/areas?vendor=${encodeURIComponent(vendor)}&scope_level=${encodeURIComponent(scopeLevel())}`);
            const data = await res.json();
            if (!data.success) return;
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

    async function loadMoClasses() {
        moClasses = [];
        moCatalog = new Map();
        parametersByMo = new Map();
        selectedMoId = '';
        selectedParam = '';
        els.moInput.disabled = true;
        els.moInput.value = '';
        els.paramInput.disabled = true;
        els.paramInput.value = '';
        els.moList.hidden = true;
        els.paramList.hidden = true;
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
                if (!data.success) throw new Error(data.error || 'Failed to load Nokia MO classes');
                items = data.mo_classes || [];
            } else {
                const res = await fetch('/api/cm-extractor/huawei/mo-objects');
                const data = await res.json();
                if (!data.success) throw new Error(data.error || 'Failed to load Huawei MO objects');
                items = (data.mo_objects || []).map((item) => ({
                    id: item.id || item.mo_id,
                    label: item.label || item.name || item.id,
                    version: '',
                }));
            }
            moClasses = items;
            items.forEach((item) => moCatalog.set(item.id, item));
            const ready = !!items.length;
            els.moInput.disabled = !ready;
            els.paramInput.disabled = !ready || entireMo;
            els.moInput.placeholder = ready ? 'Search and select MO…' : 'No MO classes';
            els.paramInput.placeholder = entireMo
                ? 'All queryable parameters'
                : (ready ? 'Type or select parameter…' : 'No parameters');
            setStatus('');
        } catch (err) {
            setStatus(err.message || 'Failed to load MO classes', 'error');
        }
    }

    async function loadParameters(moId) {
        parametersByMo.set(moId, []);
        updateScanButton();
        if (!moId) return;

        const preservedParam = selectedParam;
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
                if (!data.success) throw new Error(data.error || 'Failed to load parameters');
                params = (data.parameters && data.parameters[moId]) || [];
            } else {
                const res = await fetch('/api/cm-extractor/huawei/parameters', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ mo_ids: [moId] }),
                });
                const data = await res.json();
                if (!data.success) throw new Error(data.error || 'Failed to load parameters');
                params = (data.parameters && data.parameters[moId.toUpperCase()]) || [];
            }
            parametersByMo.set(moId, params);
            els.paramInput.disabled = entireMo || false;
            els.paramInput.placeholder = entireMo
                ? 'All queryable parameters'
                : (params.length ? 'Search and select parameter…' : 'Type parameter name…');
            if (preservedParam) {
                selectedParam = preservedParam;
                els.paramInput.value = preservedParam;
            }
            updateScanButton();
            setStatus('');
        } catch (err) {
            setStatus(err.message || 'Failed to load parameters', 'error');
        }
    }

    function setSummaryLabels(mode) {
        if (els.labelDistinct) {
            els.labelDistinct.textContent = mode === 'mo' ? 'Parameters' : 'Distinct values';
        }
        if (els.labelDominant) {
            els.labelDominant.textContent = mode === 'mo' ? 'Inconsistent parameters' : 'Dominant value';
        }
        if (els.labelStatus) {
            els.labelStatus.textContent = 'Consistency';
        }
    }

    function visibleParameterSummaries() {
        return parameterSummaries;
    }

    function sortedParameterSummaries() {
        const rows = visibleParameterSummaries();
        const key = paramSortState.key;
        const dir = paramSortState.dir;
        return [...rows].sort((left, right) => dir * compareValues(
            left[key] ?? '',
            right[key] ?? '',
        ));
    }

    function renderParameterTable() {
        if (!els.paramBody || !els.parameters) return;
        const rows = sortedParameterSummaries();
        if (els.parametersMeta) {
            els.parametersMeta.textContent = rows.length
                ? `${rows.length} parameter(s) · click a row for value mix`
                : '';
        }
        document.querySelectorAll('#audit-param-table th.sortable-th').forEach((th) => {
            const key = th.dataset.sort;
            const base = th.dataset.label || th.textContent.replace(/\s*[↑↓]$/, '').trim();
            th.dataset.label = base;
            let marker = '';
            if (paramSortState.key === key) {
                marker = paramSortState.dir > 0 ? ' ↑' : ' ↓';
            }
            th.textContent = `${base}${marker}`;
        });
        if (!rows.length) {
            els.paramBody.innerHTML = '<tr><td colspan="6" class="empty-row">No parameters returned for this MO.</td></tr>';
            return;
        }
        els.paramBody.innerHTML = rows.map((item) => {
            const status = item.status || 'consistent';
            const active = item.parameter === selectedSummaryParam ? ' is-selected' : '';
            return `
                <tr class="param-row${active}" data-parameter="${escapeHtml(item.parameter)}">
                    <td><code>${escapeHtml(item.parameter)}</code></td>
                    <td>${escapeHtml(item.distinct_values ?? 0)}</td>
                    <td><code>${escapeHtml(item.most_common_value || '(empty)')}</code></td>
                    <td>${escapeHtml(item.inconsistent_count ?? 0)}</td>
                    <td>${escapeHtml(item.inconsistency_pct ?? 0)}%</td>
                    <td><span class="value-status ${status === 'consistent' ? 'consistent' : 'variant'}">${escapeHtml(status)}</span></td>
                </tr>
            `;
        }).join('');
    }

    function selectSummaryParameter(parameter) {
        selectedSummaryParam = parameter || '';
        const item = parameterSummaries.find((row) => row.parameter === selectedSummaryParam);
        renderParameterTable();
        if (!item) {
            els.distribution.hidden = true;
            return;
        }
        renderDistribution(item.value_distribution || [], item);
        const distTitle = els.distribution.querySelector('h2');
        if (distTitle) distTitle.textContent = `Value distribution — ${item.parameter}`;
    }

    function renderDistribution(items, summary) {
        if (!items || !items.length) {
            els.distribution.hidden = true;
            if (els.distributionNote) els.distributionNote.hidden = true;
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

    function rowSortValue(row, key) {
        if (key === 'object') return row.cell_name || row.object || row.dn || '';
        if (key === 'status') return row.matches_dominant ? 'Dominant' : 'Variant';
        return row[key] ?? '';
    }

    function compareValues(a, b) {
        const sa = String(a ?? '').trim();
        const sb = String(b ?? '').trim();
        const na = Number(sa);
        const nb = Number(sb);
        if (sa !== '' && sb !== '' && Number.isFinite(na) && Number.isFinite(nb)) {
            return na - nb;
        }
        return sa.localeCompare(sb, undefined, { numeric: true, sensitivity: 'base' });
    }

    function filteredSortedRows() {
        const term = (els.resultsFilter.value || '').trim().toLowerCase();
        let rows = currentRows;
        if (term) {
            rows = rows.filter((row) => {
                const hay = [
                    row.ne, row.area, row.cell_name, row.object, row.dn, row.value,
                    row.matches_dominant ? 'dominant' : 'variant',
                ].join(' ').toLowerCase();
                return hay.includes(term);
            });
        }
        if (sortState.key) {
            const key = sortState.key;
            const dir = sortState.dir;
            rows = [...rows].sort((left, right) => dir * compareValues(
                rowSortValue(left, key),
                rowSortValue(right, key),
            ));
        }
        return rows;
    }

    function updateSortHeaders() {
        document.querySelectorAll('#audit-results-table th.sortable-th').forEach((th) => {
            const key = th.dataset.sort;
            const base = th.dataset.label || th.textContent.replace(/\s*[↑↓]$/, '').trim();
            th.dataset.label = base;
            let marker = '';
            if (sortState.key === key) {
                marker = sortState.dir > 0 ? ' ↑' : ' ↓';
            }
            th.textContent = `${base}${marker}`;
        });
    }

    function updateResultsMeta(shown, total) {
        if (!els.resultsMeta) return;
        if (!total) {
            els.resultsMeta.textContent = '';
            return;
        }
        const parts = [`${shown} of ${total}`];
        if (sortState.key) {
            parts.push(`sorted by ${sortState.key} ${sortState.dir > 0 ? '↑' : '↓'}`);
        }
        if ((els.resultsFilter.value || '').trim()) {
            parts.push('filtered');
        }
        els.resultsMeta.textContent = parts.join(' · ');
    }

    function renderRows() {
        const rows = filteredSortedRows();
        updateSortHeaders();
        updateResultsMeta(rows.length, currentRows.length);
        if (!rows.length) {
            els.resultsBody.innerHTML = '<tr><td colspan="5" class="empty-row">No objects match the current filter.</td></tr>';
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

    function showWarnings(warnings, note) {
        const items = [...(warnings || [])];
        if (note) items.unshift(note);
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
        const mode = payload.audit_mode === 'mo' ? 'mo' : 'parameter';

        els.summary.hidden = false;
        setSummaryLabels(mode);

        els.summaryNes.textContent = `${scope.queried || 0}${scope.truncated ? ` / ${scope.available}` : ''}`;
        els.summaryObjects.textContent = summary.object_count ?? 0;
        els.summaryStatus.textContent = summary.status || 'consistent';
        els.summaryStatus.className = `status-pill status-${escapeHtml(summary.status || 'consistent')}`;

        lastExportId = payload.export_id || null;
        if (els.exportBtn) els.exportBtn.disabled = !lastExportId;
        if (els.exportMoBtn) els.exportMoBtn.disabled = !lastExportId;

        if (mode === 'mo') {
            els.summaryDistinct.textContent = summary.parameter_count ?? (payload.parameter_summaries || []).length;
            els.summaryDominant.textContent = summary.inconsistent_parameter_count ?? 0;
            parameterSummaries = payload.parameter_summaries || [];
            currentRows = [];
            selectedSummaryParam = '';
            paramSortState = { key: 'inconsistency_pct', dir: -1 };
            if (els.parameters) els.parameters.hidden = false;
            if (els.results) els.results.hidden = true;
            if (els.exportBtn) els.exportBtn.hidden = true;
            const distTitle = els.distribution.querySelector('h2');
            if (distTitle) distTitle.textContent = 'Value distribution';
            els.distribution.hidden = true;
            renderParameterTable();
            showWarnings(payload.warnings, payload.note);
            return;
        }

        if (els.parameters) els.parameters.hidden = true;
        if (els.exportBtn) els.exportBtn.hidden = false;
        els.results.hidden = false;
        els.summaryDistinct.textContent = summary.distinct_values ?? 0;
        els.summaryDominant.textContent = summary.most_common_value || '(empty)';
        parameterSummaries = [];
        const distTitle = els.distribution.querySelector('h2');
        if (distTitle) distTitle.textContent = 'Value distribution';
        renderDistribution(summary.value_distribution || [], summary);
        currentRows = payload.rows || [];
        sortState = { key: null, dir: 1 };
        if (els.resultsFilter) els.resultsFilter.value = '';
        renderRows();
        showWarnings(payload.warnings, payload.note);
    }

    async function exportReport() {
        if (!lastExportId) {
            setStatus('Run a live scan before exporting.', 'error');
            return;
        }
        if (els.exportBtn) els.exportBtn.disabled = true;
        if (els.exportMoBtn) els.exportMoBtn.disabled = true;
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
                } catch (_err) { /* binary */ }
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
            if (els.exportBtn) els.exportBtn.disabled = !lastExportId;
            if (els.exportMoBtn) els.exportMoBtn.disabled = !lastExportId;
        }
    }

    async function scanNetwork() {
        const moId = selectedMoId;
        const parameter = selectedParam;
        const mo = moCatalog.get(moId) || {};
        if (!moId || !(entireMo || parameter)) return;

        els.scan.disabled = true;
        const target = entireMo ? `all ${moId} parameters` : parameter;
        const modeHint = vendor === 'nokia'
            ? (entireMo ? 'chunked network-wide CM queries' : 'one network-wide CM query')
            : 'chunked U2020 MML';
        setStatus(
            isAdmin ? `Querying live CM for ${target} (${modeHint})…` : 'Querying...',
            'loading',
        );
        els.summary.hidden = true;
        els.distribution.hidden = true;
        els.results.hidden = true;
        els.warnings.hidden = true;
        if (els.parameters) els.parameters.hidden = true;
        lastExportId = null;
        if (els.exportBtn) els.exportBtn.disabled = true;
        if (els.exportMoBtn) els.exportMoBtn.disabled = true;

        try {
            const res = await fetch('/api/cm-parameter-audit/live', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    vendor,
                    scope_level: scopeLevel(),
                    mo_class: moId,
                    mo_version: mo.version || '',
                    parameter: entireMo ? '*' : parameter,
                    entire_mo: entireMo,
                    conf_id: Number(els.confId.value || 1),
                    area: els.area.value || 'all',
                }),
            });
            const data = await res.json();
            if (!data.success) throw new Error(data.error || 'Live scan failed');
            renderResult(data);
            if (data.audit_mode === 'mo') {
                setStatus(
                    `Live MO scan complete — ${data.summary?.parameter_count || 0} parameter(s), `
                    + `${data.summary?.object_count || 0} object(s), `
                    + `${data.summary?.inconsistent_parameter_count || 0} inconsistent `
                    + `(${data.query_mode || 'live'}).`,
                    'success',
                );
            } else {
                setStatus(
                    `Live scan complete — ${data.summary?.object_count || 0} object(s), `
                    + `${data.summary?.ne_count || 0} NE(s) `
                    + `(${data.query_mode || 'live'}).`,
                    'success',
                );
            }
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
        if (nokiaScope) nokiaScope.hidden = vendor !== 'nokia';
        if (huaweiScope) huaweiScope.hidden = vendor !== 'huawei';
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

    els.moInput.addEventListener('focus', () => {
        closeComboLists(els.moList);
        renderComboList(els.moList, moComboItems(els.moInput.value), { activeValue: selectedMoId });
    });
    els.moInput.addEventListener('input', () => {
        if (selectedMoId && els.moInput.value !== selectedMoId) {
            const mo = moCatalog.get(selectedMoId);
            const label = mo ? (mo.label ? `${mo.id} — ${mo.label}` : mo.id) : selectedMoId;
            if (els.moInput.value !== label) {
                selectedMoId = '';
                updateScanButton();
            }
        }
        renderComboList(els.moList, moComboItems(els.moInput.value), { activeValue: selectedMoId });
    });
    els.moList.addEventListener('mousedown', (ev) => {
        const option = ev.target.closest('.combo-option');
        if (!option) return;
        ev.preventDefault();
        selectMo(option.dataset.value || '');
    });

    els.paramInput.addEventListener('focus', () => {
        if (entireMo) return;
        closeComboLists(els.paramList);
        if (!selectedMoId) {
            renderComboList(
                els.paramList,
                paramComboItems(els.paramInput.value),
                { activeValue: selectedParam },
            );
            if (!(els.paramInput.value || '').trim()) {
                els.paramList.innerHTML = '<li class="combo-empty">Type a parameter name, then select an MO</li>';
                els.paramList.hidden = false;
            }
            return;
        }
        renderComboList(els.paramList, paramComboItems(els.paramInput.value), { activeValue: selectedParam });
    });
    els.paramInput.addEventListener('input', () => {
        if (selectedParam && els.paramInput.value !== selectedParam) {
            selectedParam = '';
            updateScanButton();
        }
        renderComboList(els.paramList, paramComboItems(els.paramInput.value), { activeValue: selectedParam });
    });
    els.paramInput.addEventListener('keydown', (ev) => {
        if (ev.key === 'Enter') {
            ev.preventDefault();
            commitTypedParam();
        }
    });
    els.paramInput.addEventListener('blur', () => {
        commitTypedParam();
    });
    els.paramList.addEventListener('mousedown', (ev) => {
        const option = ev.target.closest('.combo-option');
        if (!option) return;
        ev.preventDefault();
        selectParam(option.dataset.value || '');
    });

    document.addEventListener('click', (ev) => {
        if (!ev.target.closest('.combo-wrap')) {
            closeComboLists();
        }
    });

    els.scan.addEventListener('click', scanNetwork);
    if (els.exportBtn) els.exportBtn.addEventListener('click', exportReport);
    if (els.exportMoBtn) els.exportMoBtn.addEventListener('click', exportReport);
    if (els.entireMo) {
        els.entireMo.addEventListener('change', () => setEntireMo(els.entireMo.checked));
    }
    if (els.paramBody) {
        els.paramBody.addEventListener('click', (ev) => {
            const row = ev.target.closest('tr.param-row');
            if (!row) return;
            selectSummaryParameter(row.dataset.parameter || '');
        });
    }
    document.querySelectorAll('#audit-param-table th.sortable-th').forEach((th) => {
        th.tabIndex = 0;
        th.title = 'Click to sort';
        th.addEventListener('click', () => {
            const key = th.dataset.sort;
            if (!key || !parameterSummaries.length) return;
            if (paramSortState.key === key) {
                paramSortState.dir = -paramSortState.dir;
            } else {
                paramSortState = { key, dir: key === 'inconsistency_pct' ? -1 : 1 };
            }
            renderParameterTable();
        });
        th.addEventListener('keydown', (ev) => {
            if (ev.key === 'Enter' || ev.key === ' ') {
                ev.preventDefault();
                th.click();
            }
        });
    });
    els.resultsFilter.addEventListener('input', renderRows);

    document.querySelectorAll('#audit-results-table th.sortable-th').forEach((th) => {
        th.tabIndex = 0;
        th.title = 'Click to sort';
        th.addEventListener('click', () => {
            const key = th.dataset.sort;
            if (!key || !currentRows.length) return;
            if (sortState.key === key) {
                sortState.dir = -sortState.dir;
            } else {
                sortState = { key, dir: 1 };
            }
            renderRows();
        });
        th.addEventListener('keydown', (ev) => {
            if (ev.key === 'Enter' || ev.key === ' ') {
                ev.preventDefault();
                th.click();
            }
        });
    });

    async function applyDeepLink() {
        const params = new URLSearchParams(window.location.search);
        const nextVendor = (params.get('vendor') || '').toLowerCase();
        const mo = (params.get('mo') || '').trim();
        const param = (params.get('param') || '').trim();
        const entire = (params.get('entire') || params.get('entire_mo') || '').trim();
        if (!nextVendor && !mo && !param && !entire) return;
        if (nextVendor === 'huawei' || nextVendor === 'nokia') {
            setVendor(nextVendor);
        }
        await loadMoClasses();
        if (mo) {
            const match = moClasses.find((item) => {
                const id = String(item.id || '');
                const label = String(item.label || '');
                return id === mo || id.endsWith(`/${mo}`) || id.split('/').pop() === mo || label === mo;
            });
            if (match) {
                selectedMoId = match.id;
                els.moInput.value = match.label ? `${match.id} — ${match.label}` : match.id;
                await loadParameters(match.id);
            } else {
                els.moInput.value = mo;
            }
        }
        if (param === '*' || param.toLowerCase() === 'all' || entire === '1' || entire.toLowerCase() === 'true') {
            setEntireMo(true);
        } else if (param) {
            selectedParam = param;
            els.paramInput.value = param;
            updateScanButton();
        }
    }

    async function loadGoldenRules() {
        const list = document.getElementById('rules-list');
        const areaSelect = document.getElementById('rule-area');
        if (!list) return;
        try {
            const res = await fetch('/api/cm-parameter-audit/rules');
            const data = await res.json();
            if (!data.success) throw new Error(data.error || 'Failed to load rules');
            if (areaSelect && Array.isArray(data.areas)) {
                const current = areaSelect.value;
                areaSelect.innerHTML = '<option value="">All areas</option>' + data.areas.map((area) =>
                    `<option value="${escapeHtml(area)}">${escapeHtml(area)}</option>`
                ).join('');
                areaSelect.value = current;
            }
            const rules = data.rules || [];
            if (!rules.length) {
                list.innerHTML = '<p class="section-description">No golden rules yet.</p>';
                return;
            }
            list.innerHTML = rules.map((rule) => {
                const approved = rule.approved_by
                    ? `Approved by ${escapeHtml(rule.approved_by)} ${escapeHtml(rule.approved_at || '')}`
                    : 'Not approved';
                const scope = [rule.technology, rule.band, rule.area].filter(Boolean).join(' / ') || 'all';
                return `<div class="rule-card">
                    <div><strong>${escapeHtml(rule.id)}</strong> · ${escapeHtml(rule.parameter)} · ${escapeHtml(rule.rule_type)} · ${escapeHtml(scope)}</div>
                    <div class="rule-meta">${escapeHtml(rule.description || '')} · v${escapeHtml(rule.version || 1)} · ${approved}</div>
                    <button type="button" class="btn-secondary rule-approve" data-id="${escapeHtml(rule.id)}">Approve</button>
                </div>`;
            }).join('');
            list.querySelectorAll('.rule-approve').forEach((btn) => {
                btn.addEventListener('click', async () => {
                    const baseline = document.getElementById('rule-baseline')?.value || '';
                    const resp = await fetch(`/api/cm-parameter-audit/rules/${encodeURIComponent(btn.dataset.id)}/approve`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ baseline }),
                    });
                    const body = await resp.json();
                    if (!body.success) {
                        setStatus(body.error || 'Approve failed', 'error');
                        return;
                    }
                    loadGoldenRules();
                });
            });
        } catch (err) {
            list.innerHTML = `<p class="section-description">${escapeHtml(err.message || 'Failed to load rules')}</p>`;
        }
    }

    const ruleForm = document.getElementById('rule-form');
    if (ruleForm) {
        ruleForm.addEventListener('submit', async (ev) => {
            ev.preventDefault();
            const payload = {
                id: document.getElementById('rule-id')?.value || '',
                parameter: document.getElementById('rule-parameter')?.value || '',
                mo_class: document.getElementById('rule-mo')?.value || '',
                technology: document.getElementById('rule-tech')?.value || '',
                band: document.getElementById('rule-band')?.value || '',
                area: document.getElementById('rule-area')?.value || '',
                rule_type: document.getElementById('rule-type')?.value || 'equals',
                expected_value: document.getElementById('rule-expected')?.value || '',
                min_value: document.getElementById('rule-min')?.value || null,
                max_value: document.getElementById('rule-max')?.value || null,
                severity: document.getElementById('rule-severity')?.value || 'Medium',
                baseline: document.getElementById('rule-baseline')?.value || '',
                description: document.getElementById('rule-description')?.value || '',
            };
            const resp = await fetch('/api/cm-parameter-audit/rules', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const data = await resp.json();
            if (!data.success) {
                setStatus(data.error || 'Save failed', 'error');
                return;
            }
            ruleForm.reset();
            loadGoldenRules();
        });
    }

    setVendor('nokia');
    applyDeepLink();
    loadGoldenRules();
})();
