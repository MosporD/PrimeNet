/**
 * NE Comparison — live CM API workflow (vendor → NEs → MO → parameters)
 */

const NOKIA_DEFAULT_MO = {
    MRBTS: ['MRBTS:MRBTS', 'NOKLTE:LNBTS', 'NOKLTE:LNCEL', 'NOKNR:NRBTS', 'NOKNR:NRCELL'],
    RNC: ['NOKRNC:RNC', 'NOKRNC:WBTS', 'NOKRNC:WCEL'],
    BSC: ['NOKBSC:BSC', 'NOKBSC:BCF', 'NOKBSC:BTS', 'NOKBSC:TRX'],
};
const HUAWEI_DEFAULT_MO = ['ENODEBFUNCTION', 'CELL', 'CNOPERATOR'];

const cmState = {
    neItems: [],
    moCatalog: [],
    selectedMo: new Map(),
    parametersByMo: new Map(),
    selectedParamsByMo: new Map(),
    fullMoByItem: new Set(),
    cmDefaults: null,
};

function $(id) {
    return document.getElementById(id);
}

function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function setStatus(id, text, type = '') {
    const el = $(id);
    if (!el) return;
    el.textContent = text;
    el.className = `status-message ${type}`.trim();
    el.style.display = text ? 'block' : 'none';
}

function selectedOptions(selectId) {
    const sel = $(selectId);
    if (!sel) return [];
    return Array.from(sel.selectedOptions).map((opt) => opt.value).filter(Boolean);
}

function currentVendor() {
    return $('cm-vendor')?.value || 'nokia';
}

function currentScope() {
    return $('cm-scope')?.value || 'MRBTS';
}

function isNokia() {
    return currentVendor() === 'nokia';
}

function neKey(item, idx) {
    return `${item.site_id || item.u2020_ne_name || item.ne_name || idx}`;
}

function normalizeNeItem(item, idx) {
    const key = neKey(item, idx);
    const label = item.label || item.site_name || item.ne_name || item.site_id || 'NE';
    return { ...item, _key: key, label };
}

function selectedNe(selectId) {
    const value = $(selectId)?.value || '';
    return cmState.neItems.find((item) => item._key === value) || null;
}

function updateScopeOptions() {
    const scope = $('cm-scope');
    const confGroup = $('cm-conf-group');
    if (!scope) return;
    if (!isNokia()) {
        scope.innerHTML = '<option value="ENODEB">eNodeB</option>';
        if (confGroup) confGroup.style.display = 'none';
    } else {
        scope.innerHTML = `
            <option value="MRBTS">MRBTS</option>
            <option value="RNC">RNC</option>
            <option value="BSC">BSC</option>
        `;
        if (confGroup) confGroup.style.display = '';
    }
    updateCmCredentialStatus();
}

async function loadCmCredentialDefaults() {
    try {
        const res = await fetch('/api/cm-extractor/defaults', { credentials: 'same-origin' });
        const data = await res.json();
        if (!res.ok) return;
        cmState.cmDefaults = data;
        updateCmCredentialStatus();
    } catch {
        /* ignore */
    }
}

function updateCmCredentialStatus() {
    const pill = $('cm-cm-config-status');
    if (!pill) return;
    const vendor = currentVendor();
    const info = vendor === 'nokia' ? cmState.cmDefaults?.nokia : cmState.cmDefaults?.huawei;
    if (!info?.configured) {
        const key = vendor === 'nokia' ? 'NOKIA_CM_*' : 'HUAWEI_CM_*';
        pill.textContent = `${vendor === 'nokia' ? 'Nokia' : 'Huawei'} CM not configured (${key})`;
        pill.className = 'connection-pill connection-bad';
        return;
    }
    const host = info.host || info.base_url || (vendor === 'nokia' ? 'NetAct' : 'U2020');
    const user = info.username || '(user not set)';
    pill.textContent = `Loaded: ${user} @ ${host}`;
    pill.className = 'connection-pill connection-neutral';
}

async function testCmApiConnection() {
    const vendor = currentVendor();
    const btn = $('cm-test-connection-btn');
    const result = $('cm-test-connection-result');
    const pill = $('cm-cm-config-status');
    if (btn) btn.disabled = true;
    if (result) {
        result.textContent = 'Testing live CM API…';
        result.className = 'connection-result';
    }
    try {
        const res = await fetch('/api/cm-extractor/test-connection', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ vendor }),
        });
        const data = await res.json();
        if (!res.ok || !data.success) {
            throw new Error(data.error || `Connection test failed (HTTP ${res.status})`);
        }
        if (pill) {
            pill.textContent = vendor === 'nokia' ? 'Nokia CM API: connected' : 'Huawei CM API: connected';
            pill.className = 'connection-pill connection-ok';
        }
        if (result) {
            result.textContent = data.message || 'Connected';
            result.className = 'connection-result connection-result-ok';
        }
        showNotification(data.message || 'CM API connection OK', 'success');
    } catch (error) {
        if (pill) pill.className = 'connection-pill connection-bad';
        if (result) {
            result.textContent = error.message || 'Connection failed';
            result.className = 'connection-result connection-result-bad';
        }
        showNotification(error.message || 'CM API connection failed', 'error');
    } finally {
        if (btn) btn.disabled = false;
    }
}

async function loadCmNes() {
    const vendor = currentVendor();
    const scope = currentScope();
    const q = ($('cm-ne1-search')?.value || $('cm-ne2-search')?.value || '').trim();
    setStatus('cm-status', 'Loading NEs…', '');
    let items = [];
    if (isNokia()) {
        const params = new URLSearchParams({ scope, q, limit: '500' });
        const res = await fetch(`/api/cm-extractor/nokia/sites?${params}`);
        const data = await res.json();
        if (!data.success) throw new Error(data.error || 'Could not load Nokia NEs');
        items = data.sites || [];
    } else {
        const params = new URLSearchParams({ vendor, scope_level: scope, q, limit: '500' });
        const res = await fetch(`/api/ne-comparison/cm/nes?${params}`);
        const data = await res.json();
        if (!data.success) throw new Error(data.error || 'Could not load Huawei NEs');
        items = data.items || [];
    }
    cmState.neItems = items.map(normalizeNeItem);
    renderNeSelect('cm-ne1');
    renderNeSelect('cm-ne2');
    renderAuditNeSelect();
    setStatus('cm-status', `Loaded ${cmState.neItems.length} ${scope} NE(s).`, 'success');
}

function renderNeSelect(selectId) {
    const sel = $(selectId);
    if (!sel) return;
    const previous = sel.value;
    sel.innerHTML = cmState.neItems.map((item) => {
        const meta = [item.area, item.cluster, item.cell_count ? `${item.cell_count} cells` : '']
            .filter(Boolean)
            .join(' · ');
        return `<option value="${escapeHtml(item._key)}">${escapeHtml(item.label)}${meta ? ` — ${escapeHtml(meta)}` : ''}</option>`;
    }).join('');
    if (previous && Array.from(sel.options).some((opt) => opt.value === previous)) {
        sel.value = previous;
    }
}

function renderAuditNeSelect() {
    const sel = $('audit-nes');
    if (!sel) return;
    const selected = new Set(selectedOptions('audit-nes'));
    sel.innerHTML = cmState.neItems.map((item) => {
        const meta = [item.area, item.cluster].filter(Boolean).join(' · ');
        const isSelected = selected.has(item._key) ? ' selected' : '';
        return `<option value="${escapeHtml(item._key)}"${isSelected}>${escapeHtml(item.label)}${meta ? ` — ${escapeHtml(meta)}` : ''}</option>`;
    }).join('');
}

function filteredMoCatalog() {
    const query = ($('cm-mo-search')?.value || '').trim().toLowerCase();
    return cmState.moCatalog.filter((mo) => {
        if (!query) return true;
        const id = mo.id || mo.mo_id || '';
        const label = mo.label || mo.name || id;
        const group = mo.group || mo.technology || '';
        return `${id} ${label} ${group}`.toLowerCase().includes(query);
    });
}

function moId(mo) {
    return mo.id || mo.mo_id || '';
}

function defaultMoIds() {
    if (isNokia()) {
        return NOKIA_DEFAULT_MO[currentScope()] || NOKIA_DEFAULT_MO.MRBTS;
    }
    return HUAWEI_DEFAULT_MO;
}

async function loadMoCatalog() {
    const loading = $('cm-mo-loading');
    const list = $('cm-mo-list');
    if (loading) loading.hidden = false;
    if (list) list.hidden = true;
    cmState.moCatalog = [];
    cmState.selectedMo.clear();
    cmState.parametersByMo.clear();
    cmState.selectedParamsByMo.clear();
    cmState.fullMoByItem.clear();
    try {
        if (isNokia()) {
            const scope = encodeURIComponent(currentScope());
            const res = await fetch(`/api/cm-extractor/nokia/mo-classes?scope=${scope}`);
            const data = await res.json();
            if (!res.ok || !data.success) throw new Error(data.error || 'Could not load MO classes');
            cmState.moCatalog = data.mo_classes || [];
        } else {
            const res = await fetch('/api/cm-extractor/huawei/mo-objects');
            const data = await res.json();
            if (!res.ok || !data.success) throw new Error(data.error || 'Could not load MO objects');
            cmState.moCatalog = (data.mo_objects || []).map((item) => ({
                ...item,
                id: item.id || item.mo_id,
            }));
        }
        selectRecommendedMo();
        if (list) list.hidden = false;
        renderMoList();
        await refreshParameterPanels();
        updateSelectionSummary();
    } catch (error) {
        setStatus('cm-status', error.message, 'error');
        if (loading) loading.textContent = error.message;
    } finally {
        if (loading) loading.hidden = true;
    }
}

function renderMoList() {
    const list = $('cm-mo-list');
    if (!list) return;
    const filtered = filteredMoCatalog();
    if (!filtered.length) {
        list.innerHTML = '<p class="loading-hint">No MO classes match your search.</p>';
        return;
    }
    if (isNokia()) {
        const byGroup = {};
        filtered.forEach((mo) => {
            const group = mo.group || 'Other';
            if (!byGroup[group]) byGroup[group] = [];
            byGroup[group].push(mo);
        });
        list.innerHTML = Object.keys(byGroup).sort().map((group) => `
            <div class="mo-group">
                <div class="mo-group-title">${escapeHtml(group)}</div>
                <div class="mo-group-items">
                    ${byGroup[group].map((mo) => moListItem(mo)).join('')}
                </div>
            </div>
        `).join('');
    } else {
        list.innerHTML = `<div class="mo-group-items">${filtered.map((mo) => moListItem(mo)).join('')}</div>`;
    }
    list.querySelectorAll('input[type="checkbox"][data-mo-id]').forEach((cb) => {
        cb.addEventListener('change', () => onMoToggle(cb.dataset.moId, cb.checked));
    });
}

function moListItem(mo) {
    const id = moId(mo);
    const label = mo.label || mo.name || id;
    const checked = cmState.selectedMo.has(id) ? 'checked' : '';
    return `
        <label class="mo-class-item">
            <input type="checkbox" data-mo-id="${escapeHtml(id)}" ${checked}>
            <span>${escapeHtml(label)}</span>
        </label>
    `;
}

async function onMoToggle(id, checked) {
    const mo = cmState.moCatalog.find((item) => moId(item) === id);
    if (!mo) return;
    if (checked) {
        cmState.selectedMo.set(id, mo);
        if (!cmState.selectedParamsByMo.has(id)) cmState.selectedParamsByMo.set(id, new Set());
    } else {
        cmState.selectedMo.delete(id);
        cmState.selectedParamsByMo.delete(id);
        cmState.fullMoByItem.delete(id);
        cmState.parametersByMo.delete(id);
    }
    await refreshParameterPanels();
    updateSelectionSummary();
}

async function addMoSelections(mos) {
    for (const mo of mos) {
        const id = moId(mo);
        cmState.selectedMo.set(id, mo);
        if (!cmState.selectedParamsByMo.has(id)) cmState.selectedParamsByMo.set(id, new Set());
        cmState.fullMoByItem.add(id);
    }
    renderMoList();
    await refreshParameterPanels();
    updateSelectionSummary();
}

function selectRecommendedMo() {
    const defaults = new Set(defaultMoIds());
    const recommended = cmState.moCatalog.filter((mo) => defaults.has(moId(mo)));
    return addMoSelections(recommended);
}

function selectVisibleMo() {
    return addMoSelections(filteredMoCatalog());
}

function clearMoSelection() {
    cmState.selectedMo.clear();
    cmState.selectedParamsByMo.clear();
    cmState.fullMoByItem.clear();
    cmState.parametersByMo.clear();
    renderMoList();
    refreshParameterPanels();
    updateSelectionSummary();
}

async function refreshParameterPanels() {
    const section = $('cm-param-section');
    const groups = $('cm-param-groups');
    const loading = $('cm-param-loading');
    if (!section || !groups) return;

    if (!cmState.selectedMo.size) {
        section.hidden = true;
        groups.innerHTML = '';
        updateCompareButton();
        return;
    }
    section.hidden = false;

    const needFetch = [...cmState.selectedMo.keys()].filter((id) => !cmState.parametersByMo.has(id));
    if (needFetch.length) {
        loading.hidden = false;
        try {
            if (isNokia()) {
                const res = await fetch('/api/cm-extractor/nokia/parameters', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        mo_classes: needFetch.map((id) => {
                            const mo = cmState.selectedMo.get(id);
                            return { mo_class_id: id, id, version: mo.version };
                        }),
                    }),
                });
                const data = await res.json();
                if (!data.success) throw new Error(data.error || 'Could not load parameters');
                Object.entries(data.parameters || {}).forEach(([classId, params]) => {
                    cmState.parametersByMo.set(classId, params);
                });
            } else {
                const res = await fetch('/api/cm-extractor/huawei/parameters', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ mo_ids: needFetch }),
                });
                const data = await res.json();
                if (!data.success) throw new Error(data.error || 'Could not load parameters');
                Object.entries(data.parameters || {}).forEach(([moIdKey, params]) => {
                    cmState.parametersByMo.set(moIdKey, params);
                });
            }
        } catch (error) {
            showNotification(error.message, 'error');
        } finally {
            loading.hidden = true;
        }
    }

    groups.innerHTML = '';
    [...cmState.selectedMo.values()].forEach((mo) => {
        const id = moId(mo);
        const group = document.createElement('div');
        group.className = 'param-mo-group';
        const isFull = cmState.fullMoByItem.has(id);
        const label = mo.label || mo.abbreviation || mo.name || id;
        group.innerHTML = `
            <div class="param-mo-head">
                <strong>${escapeHtml(label)}</strong>
                <button type="button" class="link-btn full-mo-btn" data-mo-id="${escapeHtml(id)}">${isFull ? 'Full MO selected' : 'Full MO export'}</button>
                <button type="button" class="link-btn clear-mo-btn" data-mo-id="${escapeHtml(id)}">Clear params</button>
            </div>
            <div class="param-checkboxes" data-mo-id="${escapeHtml(id)}"></div>
        `;
        const grid = group.querySelector('.param-checkboxes');
        const params = cmState.parametersByMo.get(id) || [];
        const selected = cmState.selectedParamsByMo.get(id) || new Set();

        if (isFull) {
            grid.innerHTML = '<p class="loading-hint full-mo-note">Full MO export — all parameters and instances are pulled from CM.</p>';
        } else if (!params.length) {
            grid.innerHTML = '<p class="loading-hint">No parameters returned for this MO.</p>';
        } else {
            params.forEach((param) => {
                const pid = param.id || param.name || param;
                const queryable = param.queryable !== false;
                const labelEl = document.createElement('label');
                labelEl.className = `param-check${queryable ? '' : ' param-structured'}`;
                labelEl.dataset.paramId = pid;
                const cb = document.createElement('input');
                cb.type = 'checkbox';
                cb.value = pid;
                cb.checked = selected.has(pid);
                cb.disabled = !queryable;
                cb.addEventListener('change', () => {
                    const set = cmState.selectedParamsByMo.get(id) || new Set();
                    if (cb.checked) set.add(pid);
                    else set.delete(pid);
                    cmState.selectedParamsByMo.set(id, set);
                    cmState.fullMoByItem.delete(id);
                    updateSelectionSummary();
                    updateCompareButton();
                });
                labelEl.appendChild(cb);
                const text = document.createElement('span');
                text.textContent = typeof param === 'string' ? param : (param.name || pid);
                labelEl.appendChild(text);
                grid.appendChild(labelEl);
            });
        }
        groups.appendChild(group);
    });

    filterParameterList();
    groups.querySelectorAll('.full-mo-btn').forEach((btn) => {
        btn.addEventListener('click', () => {
            const id = btn.dataset.moId;
            if (cmState.fullMoByItem.has(id)) cmState.fullMoByItem.delete(id);
            else {
                cmState.fullMoByItem.add(id);
                cmState.selectedParamsByMo.set(id, new Set());
            }
            refreshParameterPanels();
            updateSelectionSummary();
        });
    });
    groups.querySelectorAll('.clear-mo-btn').forEach((btn) => {
        btn.addEventListener('click', () => {
            const id = btn.dataset.moId;
            cmState.selectedParamsByMo.set(id, new Set());
            cmState.fullMoByItem.delete(id);
            refreshParameterPanels();
            updateSelectionSummary();
        });
    });
    updateCompareButton();
}

function filterParameterList() {
    const query = ($('cm-param-search')?.value || '').trim().toLowerCase();
    document.querySelectorAll('.param-check').forEach((label) => {
        const paramId = (label.dataset.paramId || '').toLowerCase();
        label.hidden = Boolean(query && !paramId.includes(query));
    });
}

function buildSelections() {
    if (isNokia()) {
        return [...cmState.selectedMo.entries()].map(([id, mo]) => {
            const isFull = cmState.fullMoByItem.has(id);
            const params = isFull ? [] : [...(cmState.selectedParamsByMo.get(id) || [])];
            return {
                mo_class_id: id,
                version: mo.version || '',
                parameters: params,
                export_mode: isFull ? 'full' : 'selected',
            };
        });
    }
    return [...cmState.selectedMo.keys()].map((id) => {
        const exportAll = cmState.fullMoByItem.has(id);
        const params = exportAll ? [] : [...(cmState.selectedParamsByMo.get(id) || [])];
        return {
            mo_id: id,
            export_all: exportAll,
            parameters: params,
        };
    });
}

function selectionsValid() {
    const selections = buildSelections();
    return selections.length > 0 && selections.every(
        (s) => s.export_mode === 'full' || s.export_all || (s.parameters && s.parameters.length > 0),
    );
}

function selectionSummaryText() {
    return buildSelections().map((s) => {
        if (isNokia()) {
            const abbr = (s.mo_class_id || '').split(':').pop();
            return s.export_mode === 'full' ? `${abbr}: full MO` : `${abbr}: ${s.parameters.length} param(s)`;
        }
        return s.export_all ? `${s.mo_id}: full MO` : `${s.mo_id}: ${s.parameters.length} param(s)`;
    }).join(' · ');
}

function updateSelectionSummary() {
    const el = $('cm-selection-summary');
    if (!el) return;
    if (!selectionsValid()) {
        el.hidden = true;
        return;
    }
    el.textContent = `Ready to compare: ${selectionSummaryText()}`;
    el.hidden = false;
}

function updateCompareButton() {
    const btn = $('cm-compare-btn');
    if (btn) btn.disabled = !selectionsValid();
    updateSelectionSummary();
}

async function compareCmNes(e) {
    e.preventDefault();
    const ne1 = selectedNe('cm-ne1');
    const ne2 = selectedNe('cm-ne2');
    if (!ne1 || !ne2) {
        showNotification('Select two NEs to compare', 'error');
        return;
    }
    if (ne1._key === ne2._key) {
        showNotification('Select two different NEs', 'error');
        return;
    }
    if (!selectionsValid()) {
        showNotification('Select MO classes and parameters (or full MO export)', 'error');
        return;
    }

    const payload = {
        vendor: currentVendor(),
        scope_level: currentScope(),
        conf_id: Number($('cm-conf-id')?.value || 1),
        ne1,
        ne2,
        selections: buildSelections(),
    };

    const btn = e.target.querySelector('button[type="submit"]');
    if (btn) btn.disabled = true;
    setStatus('cm-status', 'Pulling CM data and comparing NEs…', '');
    try {
        const res = await fetch('/api/ne-comparison/cm/compare', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (!data.success) throw new Error(data.error || 'Comparison failed');
        window.comparisonData = data;
        displayResults(data);
        setStatus('cm-status', 'CM comparison completed.', 'success');
        showNotification('CM comparison completed', 'success');
    } catch (error) {
        setStatus('cm-status', `Error: ${error.message}`, 'error');
        showNotification(error.message, 'error');
    } finally {
        if (btn) btn.disabled = false;
        updateCompareButton();
    }
}

function selectedAuditNes() {
    const values = new Set(selectedOptions('audit-nes'));
    return cmState.neItems.filter((item) => values.has(item._key));
}

async function runNetworkAudit(e) {
    e.preventDefault();
    const nes = selectedAuditNes();
    if (!nes.length) {
        showNotification('Select at least one NE to audit', 'error');
        return;
    }
    if (!selectionsValid()) {
        showNotification('Select MO classes and parameters above first', 'error');
        return;
    }

    const payload = {
        vendor: currentVendor(),
        scope_level: currentScope(),
        conf_id: Number($('cm-conf-id')?.value || 1),
        nes,
        selections: buildSelections(),
    };

    const btn = e.target.querySelector('button[type="submit"]');
    if (btn) btn.disabled = true;
    setStatus('audit-status', `Pulling CM data for ${nes.length} NE(s)…`, '');
    try {
        const res = await fetch('/api/ne-comparison/cm/audit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (!data.success) throw new Error(data.error || 'Audit failed');
        window.comparisonData = data;
        displayAuditResults(data);
        setStatus('audit-status', 'NW audit completed.', 'success');
        showNotification('NW audit completed', 'success');
    } catch (error) {
        setStatus('audit-status', `Error: ${error.message}`, 'error');
        showNotification(error.message, 'error');
    } finally {
        if (btn) btn.disabled = false;
    }
}

function bindCmWorkflow() {
    $('cm-compare-form')?.addEventListener('submit', compareCmNes);
    $('cm-audit-form')?.addEventListener('submit', runNetworkAudit);
    $('audit-select-all')?.addEventListener('click', () => {
        Array.from($('audit-nes')?.options || []).forEach((opt) => { opt.selected = true; });
    });
    $('audit-clear-selection')?.addEventListener('click', () => {
        Array.from($('audit-nes')?.options || []).forEach((opt) => { opt.selected = false; });
    });
    $('cm-vendor')?.addEventListener('change', async () => {
        updateScopeOptions();
        try {
            await Promise.all([loadCmNes(), loadMoCatalog()]);
        } catch (error) {
            setStatus('cm-status', error.message, 'error');
        }
    });
    $('cm-test-connection-btn')?.addEventListener('click', () => testCmApiConnection());
    $('cm-scope')?.addEventListener('change', async () => {
        try {
            await Promise.all([loadCmNes(), loadMoCatalog()]);
        } catch (error) {
            setStatus('cm-status', error.message, 'error');
        }
    });
    let neSearchTimer;
    const onNeSearch = () => {
        clearTimeout(neSearchTimer);
        neSearchTimer = setTimeout(() => {
            loadCmNes().catch((err) => setStatus('cm-status', err.message, 'error'));
        }, 300);
    };
    $('cm-ne1-search')?.addEventListener('input', onNeSearch);
    $('cm-ne2-search')?.addEventListener('input', onNeSearch);
    $('cm-mo-search')?.addEventListener('input', renderMoList);
    $('cm-param-search')?.addEventListener('input', filterParameterList);
    $('cm-mo-select-recommended')?.addEventListener('click', () => selectRecommendedMo());
    $('cm-mo-select-visible')?.addEventListener('click', () => selectVisibleMo());
    $('cm-mo-clear')?.addEventListener('click', () => clearMoSelection());
}

function bindLegacyUpload() {
    $('xml-file1')?.addEventListener('change', (e) => {
        $('file1-text').textContent = e.target.files[0]?.name || 'Choose first XML…';
    });
    $('xml-file2')?.addEventListener('change', (e) => {
        $('file2-text').textContent = e.target.files[0]?.name || 'Choose second XML…';
    });

    $('upload-form')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const file1 = $('xml-file1').files[0];
        const file2 = $('xml-file2').files[0];
        if (!file1 || !file2) {
            showNotification('Please select both files', 'error');
            return;
        }
        const formData = new FormData();
        formData.append('file1', file1);
        formData.append('file2', file2);
        const statusDiv = $('upload-status');
        statusDiv.innerHTML = '<div class="loading-spinner"></div>';
        statusDiv.className = 'status-message';
        statusDiv.style.display = 'block';
        try {
            const response = await fetch('/api/ne-comparison/compare', { method: 'POST', body: formData });
            const contentType = response.headers.get('content-type');
            if (contentType && contentType.includes('spreadsheet')) {
                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                const disposition = response.headers.get('Content-Disposition');
                let filename = 'comparison_report.xlsx';
                if (disposition && disposition.includes('filename=')) {
                    filename = disposition.split('filename=')[1].replace(/"/g, '');
                }
                a.download = filename;
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(url);
                a.remove();
                statusDiv.textContent = 'Comparison completed. File downloaded.';
                statusDiv.className = 'status-message success';
                showNotification('Comparison report downloaded', 'success');
            } else {
                const data = await response.json();
                statusDiv.textContent = `Error: ${data.error}`;
                statusDiv.className = 'status-message error';
                showNotification(data.error, 'error');
            }
        } catch (error) {
            statusDiv.textContent = `Error: ${error.message}`;
            statusDiv.className = 'status-message error';
            showNotification('Comparison failed', 'error');
        }
    });
}

function displayResults(comparison) {
    $('results-section').style.display = 'block';
    const title = $('results-title');
    if (title) title.textContent = 'Comparison Results';

    const stats = comparison.stats;
    $('comparison-stats').innerHTML = `
        <div class="stat-item"><div class="stat-value added">${stats.added || 0}</div><div class="stat-label">Added</div></div>
        <div class="stat-item"><div class="stat-value removed">${stats.removed || 0}</div><div class="stat-label">Removed</div></div>
        <div class="stat-item"><div class="stat-value modified">${stats.modified || 0}</div><div class="stat-label">Modified</div></div>
        <div class="stat-item"><div class="stat-value same">${stats.same || 0}</div><div class="stat-label">Unchanged</div></div>
    `;

    const resultsDiv = $('comparison-results');
    const differences = comparison.differences || [];
    const warnings = comparison.warnings || [];
    const summary = comparison.summary || [];

    if (!differences.length) {
        resultsDiv.innerHTML = [
            renderSummary(summary),
            renderWarnings(warnings),
            '<p class="no-diff-msg">No differences found for the compared CM data.</p>',
        ].join('');
        return;
    }

    let html = renderSummary(summary) + renderWarnings(warnings);
    if (comparison.truncated) {
        html += '<div class="status-message error">Result preview is truncated. Download the report for the full diff.</div>';
    }
    differences.forEach((diff) => {
        const typeClass = diff.type;
        const typeLabel = diff.type.charAt(0).toUpperCase() + diff.type.slice(1);
        const changes = diff.changes || [];
        const valueHtml = changes.length
            ? `<table class="change-table"><thead><tr><th>Parameter</th><th>Baseline</th><th>Compare</th></tr></thead><tbody>${
                changes.slice(0, 12).map((change) => `
                    <tr>
                        <td>${escapeHtml(change.parameter)}</td>
                        <td>${escapeHtml(change.old_value)}</td>
                        <td>${escapeHtml(change.new_value)}</td>
                    </tr>
                `).join('')
            }</tbody></table>${changes.length > 12 ? `<div class="diff-path">+${changes.length - 12} more changed parameter(s)</div>` : ''}`
            : `${diff.old_value !== undefined ? `Old: ${escapeHtml(JSON.stringify(diff.old_value))}<br>` : ''}
               ${diff.new_value !== undefined ? `New: ${escapeHtml(JSON.stringify(diff.new_value))}` : ''}`;
        html += `
            <div class="diff-item ${typeClass}">
                <div class="diff-item-header">${typeLabel}: ${escapeHtml(diff.section || diff.parameter || 'CM object')}</div>
                <div class="diff-item-content">${valueHtml}</div>
                <div class="diff-path">${escapeHtml(diff.path || '')}</div>
            </div>
        `;
    });
    resultsDiv.innerHTML = html;
}

function displayAuditResults(audit) {
    $('results-section').style.display = 'block';
    $('results-title').textContent = 'NW Audit Results';
    const stats = audit.stats || {};
    $('comparison-stats').innerHTML = `
        <div class="stat-item"><div class="stat-value modified">${stats.parameters || 0}</div><div class="stat-label">Parameters</div></div>
        <div class="stat-item"><div class="stat-value high">${stats.high || 0}</div><div class="stat-label">High inconsistency</div></div>
        <div class="stat-item"><div class="stat-value medium">${stats.medium || 0}</div><div class="stat-label">Medium</div></div>
        <div class="stat-item"><div class="stat-value same">${stats.consistent || 0}</div><div class="stat-label">Consistent</div></div>
    `;
    const rows = audit.parameter_summary || [];
    const resultsDiv = $('comparison-results');
    let html = renderAuditSectionSummary(audit.section_summary || []) + renderWarnings(audit.warnings || []);
    if (!rows.length) {
        html += '<p class="no-diff-msg">No parameter samples were returned for this audit.</p>';
        resultsDiv.innerHTML = html;
        return;
    }
    html += `
        <table class="audit-table">
            <thead>
                <tr>
                    <th>MO</th><th>Parameter</th><th>Status</th><th>Inconsistent</th>
                    <th>Distinct</th><th>Most common value</th><th>Samples</th>
                </tr>
            </thead>
            <tbody>
                ${rows.map((row) => `
                    <tr>
                        <td>${escapeHtml(row.section)}</td>
                        <td>${escapeHtml(row.parameter)}</td>
                        <td><span class="audit-badge audit-${escapeHtml(row.status)}">${escapeHtml(row.status)}</span></td>
                        <td>${escapeHtml(row.inconsistency_pct)}%</td>
                        <td>${escapeHtml(row.distinct_values)}</td>
                        <td>${escapeHtml(row.most_common_value)}</td>
                        <td>
                            ${(row.values || []).slice(0, 3).map((v) => `
                                <div class="audit-value-sample">
                                    <strong>${escapeHtml(v.percent)}%</strong> ${escapeHtml(v.value)}
                                    <span>${escapeHtml((v.sample_nes || []).join(', '))}</span>
                                </div>
                            `).join('')}
                        </td>
                    </tr>
                `).join('')}
            </tbody>
        </table>
    `;
    resultsDiv.innerHTML = html;
}

function renderAuditSectionSummary(summary) {
    if (!summary.length) return '';
    return `<div class="section-summary">${summary.map((row) => `
        <div class="section-summary-item">
            <strong>${escapeHtml(row.section)}</strong>
            <span>${row.ne_count || 0} NE pull(s)</span>
            <span>${row.object_count || 0} object sample(s)</span>
        </div>
    `).join('')}</div>`;
}

function renderSummary(summary) {
    if (!summary.length) return '';
    return `<div class="section-summary">${summary.map((row) => `
        <div class="section-summary-item">
            <strong>${escapeHtml(row.section)}</strong>
            <span>${row.left_count || 0} vs ${row.right_count || 0} objects</span>
            <span>${row.modified || 0} modified · ${row.added || 0} added · ${row.removed || 0} removed</span>
        </div>
    `).join('')}</div>`;
}

function renderWarnings(warnings) {
    if (!warnings.length) return '';
    return `<div class="warning-list">${warnings.map((w) => `<div>${escapeHtml(w)}</div>`).join('')}</div>`;
}

async function downloadReport() {
    if (!window.comparisonData) {
        showNotification('No comparison data available', 'error');
        return;
    }
    try {
        const response = await fetch('/api/ne-comparison/download-report', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(window.comparisonData),
        });
        if (response.ok) {
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'comparison_report.xlsx';
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            a.remove();
            showNotification('Download started', 'success');
        } else {
            showNotification('Download failed', 'error');
        }
    } catch (error) {
        showNotification(`Download error: ${error.message}`, 'error');
    }
}

document.addEventListener('DOMContentLoaded', async () => {
    bindLegacyUpload();
    bindCmWorkflow();
    updateScopeOptions();
    updateCompareButton();
    loadCmCredentialDefaults();
    try {
        await Promise.all([loadCmNes(), loadMoCatalog()]);
    } catch (error) {
        setStatus('cm-status', error.message, 'error');
    }
});
