/**
 * CM Extractor — Nokia MO class + parameter pickers (backend builds queries).
 */

let activeVendor = 'nokia';
let lastFileId = null;
let bulkExportSshConfigured = false;
let bulkExportTimeoutSec = 3600;
let bulkPhaseTimer = null;

/** @type {Array<{id, adaptation, abbreviation, version, label, group}>} */
let moClassCatalog = [];

/** @type {Map<string, object>} */
const selectedMoClasses = new Map();

/** @type {Map<string, Array<{id, name, description}>>} */
const parametersByClass = new Map();

/** @type {Map<string, Set<string>>} */
const selectedParamsByClass = new Map();

/** @type {Set<string>} MO classes exported via queryMOLites + getManagedObjects */
const fullMoByClass = new Set();

/** @type {Array<{site_id, site_name, label, cell_count}>} */
let nokiaSiteCatalog = [];

/** @type {Array<{area, site_count}>} */
let nokiaAreas = [];

/** @type {Set<string>} */
const selectedSiteIds = new Set();

/** @type {Array<{site_id, site_name, ne_name, label, cell_count}>} */
let huaweiNeCatalog = [];

/** @type {Set<string>} */
const selectedHuaweiSiteIds = new Set();

/** @type {Array<{id, label, technology, command, group}>} */
let huaweiMoCatalog = [];

/** @type {Map<string, object>} */
const selectedHuaweiMoObjects = new Map();

/** @type {Map<string, Array<{id, name}>>} */
const huaweiParametersByMo = new Map();

/** @type {Map<string, Set<string>>} */
const selectedHuaweiParamsByMo = new Map();

/** @type {Set<string>} */
const fullMoByHuaweiObject = new Set();

let huaweiCatalogLoaded = false;

/** @type {Array<{area, site_count}>} */
let huaweiAreas = [];

const QUERY_PARAM_MAX = 250;

const isCmAdmin = (document.body.dataset.userRole || '').trim().toLowerCase() === 'admin';

function nokiaSiteDisplay(site) {
    if (isCmAdmin) {
        return {
            title: site.label || `${site.site_name} (${site.site_id})`,
            meta: site.area
                ? (site.cluster ? `${site.area} · cl ${site.cluster}` : site.area)
                : (site.cell_count ? `${site.cell_count} cell(s)` : null),
        };
    }
    const title = (site.site_name || String(site.site_id)).trim();
    const metaParts = [];
    if (site.cluster) metaParts.push(`cl ${site.cluster}`);
    else if (site.area) metaParts.push(site.area);
    else if (site.cell_count) metaParts.push(`${site.cell_count} cells`);
    return { title, meta: metaParts.join(' · ') || null };
}

function huaweiSiteDisplay(site) {
    if (isCmAdmin) {
        const unresolved = site.u2020_resolved === false;
        const areaTag = site.area
            ? `${site.area}${site.cluster ? ` · cl ${site.cluster}` : ''} · `
            : '';
        let meta = `${areaTag}${site.cell_count || 0} cell(s)`;
        if (unresolved) meta = `${areaTag}not in U2020 catalog`;
        else if (site.u2020_source === 'metadata') meta = `${areaTag}meName from metadata (not in FM catalog)`;
        return { title: site.label, meta, unresolved };
    }
    const title = (site.site_name || String(site.site_id)).trim();
    const metaParts = [];
    if (site.cluster) metaParts.push(`cl ${site.cluster}`);
    else if (site.area) metaParts.push(site.area);
    else if (site.cell_count) metaParts.push(`${site.cell_count} cells`);
    return { title, meta: metaParts.join(' · ') || null, unresolved: false };
}

function huaweiMoDisplay(mo) {
    if (isCmAdmin) {
        const rec = mo.recommended ? ' · recommended' : '';
        const perm = mo.permission_denied ? ' · needs MML rights' : '';
        let disc = '';
        if (mo.discovered) disc = ' · on NE';
        else if (mo.source === 'dictionary') disc = ' · dictionary';
        else disc = ' · static';
        return {
            title: mo.label || mo.id,
            meta: `${mo.technology} · ${mo.command}${rec}${perm}${disc}`,
        };
    }
    return { title: mo.id || mo.label, meta: null, titleIsId: true };
}

function schedSiteDisplay(site) {
    if (schedState.vendor === 'huawei') return huaweiSiteDisplay(site);
    return nokiaSiteDisplay(site);
}

function getScopeLevel() {
    return document.querySelector('input[name="nokia-scope-level"]:checked')?.value || 'MRBTS';
}

document.querySelectorAll('.vendor-tab').forEach((btn) => {
    btn.addEventListener('click', () => setVendor(btn.dataset.vendor));
});

document.querySelectorAll('input[name="nokia-scope-level"]').forEach((radio) => {
    radio.addEventListener('change', onScopeLevelChanged);
});
document.getElementById('nokia-site-search').addEventListener('input', renderSiteList);
document.getElementById('nokia-site-select-all').addEventListener('click', selectAllSites);
document.getElementById('nokia-site-select-visible').addEventListener('click', selectVisibleSites);
document.getElementById('nokia-site-clear').addEventListener('click', clearSiteSelection);
document.getElementById('nokia-site-apply-paste').addEventListener('click', applyPastedSiteIds);
document.getElementById('nokia-mo-search').addEventListener('input', renderMoClassList);
document.getElementById('nokia-mo-select-all').addEventListener('click', () => { selectAllMoClasses(); });
document.getElementById('nokia-mo-select-visible').addEventListener('click', () => { selectVisibleMoClasses(); });
document.getElementById('nokia-mo-clear').addEventListener('click', clearMoClassSelection);
document.getElementById('nokia-param-search').addEventListener('input', filterParameterList);
document.getElementById('nokia-preview-btn').addEventListener('click', previewNokia);
document.getElementById('nokia-extract-btn').addEventListener('click', () => extract('nokia'));
const nokiaWritePanel = document.getElementById('nokia-write-panel');
if (nokiaWritePanel) {
    document.getElementById('nokia-reimport-file').addEventListener('change', onNokiaReimportFileChanged);
    document.getElementById('nokia-reimport-preview-btn').addEventListener('click', previewNokiaReimport);
    document.getElementById('nokia-reimport-execute-btn').addEventListener('click', executeNokiaReimport);
    document.getElementById('nokia-reimport-confirm').addEventListener('input', updateNokiaReimportExecuteState);
}
// Wire Huawei workflow when the tab is present (all users when CM_HUAWEI_ENABLED).
const huaweiEnabled = Boolean(document.getElementById('huawei-workflow'));
if (huaweiEnabled) {
    document.getElementById('huawei-ne-search').addEventListener('input', renderHuaweiNeList);
    document.getElementById('huawei-ne-select-all').addEventListener('click', selectAllHuaweiNes);
    document.getElementById('huawei-ne-select-visible').addEventListener('click', selectVisibleHuaweiNes);
    document.getElementById('huawei-ne-clear').addEventListener('click', clearHuaweiNeSelection);
    document.getElementById('huawei-ne-apply-paste').addEventListener('click', applyPastedHuaweiNeIds);
    document.querySelectorAll('input[name="huawei-scope-level"]').forEach((radio) => {
        radio.addEventListener('change', onHuaweiScopeLevelChanged);
    });
    const huaweiSyncBtn = document.getElementById('huawei-sync-u2020-btn');
    if (huaweiSyncBtn) huaweiSyncBtn.addEventListener('click', syncHuaweiFromU2020);
    document.getElementById('huawei-area-add-btn').addEventListener('click', addHuaweiAreaSites);
    document.getElementById('huawei-area-filter-list').addEventListener('change', renderHuaweiNeList);
    document.getElementById('huawei-area-select').addEventListener('change', () => {
        if (document.getElementById('huawei-area-filter-list')?.checked) renderHuaweiNeList();
    });
    document.getElementById('huawei-mo-search').addEventListener('input', renderHuaweiMoList);
    document.getElementById('huawei-mo-select-all').addEventListener('click', () => { selectAllHuaweiMoObjects(); });
    document.getElementById('huawei-mo-select-visible').addEventListener('click', () => { selectVisibleHuaweiMoObjects(); });
    document.getElementById('huawei-mo-clear').addEventListener('click', clearHuaweiMoSelection);
    document.getElementById('huawei-param-search').addEventListener('input', filterHuaweiParameterList);
    document.getElementById('huawei-preview-btn').addEventListener('click', previewHuawei);
    document.getElementById('huawei-extract-btn').addEventListener('click', () => extract('huawei'));
}
document.getElementById('download-btn').addEventListener('click', downloadFile);

document.getElementById('nokia-mo-retry').addEventListener('click', loadMoClasses);
document.getElementById('nokia-area-add-btn').addEventListener('click', addNokiaAreaSites);
document.getElementById('nokia-area-filter-list').addEventListener('change', renderSiteList);
document.getElementById('nokia-area-select').addEventListener('change', () => {
    if (document.getElementById('nokia-area-filter-list')?.checked) renderSiteList();
});
loadCmExtractorDefaults();
initNokiaCatalog();
loadMoClasses();

async function initNokiaCatalog() {
    await reconcileNokiaInventory();
    await loadNokiaSites();
}

async function reconcileNokiaInventory() {
    try {
        const response = await fetch('/api/cm-extractor/nokia/reconcile', {
            method: 'POST',
            credentials: 'same-origin',
        });
        const data = await response.json();
        if (!response.ok || !data.success) {
            console.warn('Nokia inventory reconcile skipped:', data.error || response.status);
        }
    } catch (error) {
        console.warn('Nokia inventory reconcile failed:', error);
    }
}

const SCOPE_PASTE_PLACEHOLDER = {
    MRBTS: 'Paste MRBTS ids (comma, space, or new line)\ne.g. 101, 102, 1211',
    RNC: 'Paste RNC ids (comma, space, or new line)\ne.g. 2012, 2013 (NetAct PLMN instance ids)',
    BSC: 'Paste BSC ids (comma, space, or new line)\ne.g. 408025, 408026',
};

function isControllerScope(level = getScopeLevel()) {
    return level === 'RNC' || level === 'BSC';
}

async function loadCmExtractorDefaults() {
    try {
        const response = await fetch('/api/cm-extractor/defaults', { credentials: 'same-origin' });
        const data = await response.json();
        if (response.ok && data.nokia) {
            bulkExportSshConfigured = Boolean(data.nokia.bulk_export_ssh);
            bulkExportTimeoutSec = Number(data.nokia.bulk_operation_timeout_sec) || 3600;
            updateNokiaConnectionStatus(data.nokia);
        }
        if (response.ok && data.huawei) {
            updateHuaweiConnectionStatus(data.huawei);
        }
    } catch {
        bulkExportSshConfigured = false;
    }
    updateScopeHint();
}

function updateNokiaConnectionStatus(nokia) {
    const pill = document.getElementById('nokia-cm-config-status');
    if (!pill) return;
    if (!nokia?.configured) {
        pill.textContent = 'Nokia CM API not configured in .env';
        pill.className = 'connection-pill connection-bad';
        return;
    }
    const host = nokia.host || nokia.base_url || 'NetAct';
    const user = nokia.username || '(user not set)';
    pill.textContent = `Loaded: ${user} @ ${host}`;
    pill.className = 'connection-pill connection-neutral';
}

function updateHuaweiConnectionStatus(huawei) {
    const pill = document.getElementById('huawei-cm-config-status');
    if (!pill) return;
    if (!huawei?.configured) {
        pill.textContent = 'Huawei CM API not configured in .env';
        pill.className = 'connection-pill connection-bad';
        return;
    }
    const host = huawei.host || 'U2020';
    const user = huawei.username || '(user not set)';
    pill.textContent = `Loaded: ${user} @ ${host}`;
    pill.className = 'connection-pill connection-neutral';
}

async function testCmApiConnection(vendor) {
    const btnId = vendor === 'huawei' ? 'huawei-test-connection-btn' : 'nokia-test-connection-btn';
    const resultId = vendor === 'huawei' ? 'huawei-test-connection-result' : 'nokia-test-connection-result';
    const pillId = vendor === 'huawei' ? 'huawei-cm-config-status' : 'nokia-cm-config-status';
    const btn = document.getElementById(btnId);
    const result = document.getElementById(resultId);
    const pill = document.getElementById(pillId);
    if (btn) btn.disabled = true;
    if (result) {
        result.textContent = 'Testing live CM API…';
        result.className = 'connection-result';
    }
    try {
        const response = await fetch('/api/cm-extractor/test-connection', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ vendor }),
        });
        const data = await response.json();
        if (!response.ok || !data.success) {
            throw new Error(data.error || `Connection test failed (HTTP ${response.status})`);
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

document.getElementById('nokia-test-connection-btn')?.addEventListener('click', () => testCmApiConnection('nokia'));
document.getElementById('huawei-test-connection-btn')?.addEventListener('click', () => testCmApiConnection('huawei'));

function updateScopeHint() {
    const level = getScopeLevel();
    const show = isControllerScope(level);
    const hint = document.getElementById('nokia-scope-hint');
    const warning = document.getElementById('nokia-scope-sftp-warning');

    if (hint) hint.hidden = !show;
    if (!show) {
        if (warning) {
            warning.hidden = true;
            warning.textContent = '';
        }
        return;
    }

    if (warning) {
        if (!bulkExportSshConfigured) {
            warning.hidden = false;
            warning.textContent =
                'SFTP is not configured. Set NOKIA_CM_SSH_* or NOKIA_PM_HOST / NOKIA_PM_USER / '
                + 'NOKIA_PM_PASSWORD in .env (OMC ftpuser — not the CM REST login) so Extract '
                + 'can pull the RAML file after Import_Export.';
        } else {
            warning.hidden = true;
            warning.textContent = '';
        }
    }
}

function onScopeLevelChanged() {
    const level = getScopeLevel();
    document.getElementById('nokia-site-picker-title').textContent = `Sites (${level})`;
    document.getElementById('nokia-site-paste').placeholder = SCOPE_PASTE_PLACEHOLDER[level] || SCOPE_PASTE_PLACEHOLDER.MRBTS;
    updateScopeHint();
    selectedSiteIds.clear();
    selectedMoClasses.clear();
    selectedParamsByClass.clear();
    parametersByClass.clear();
    fullMoByClass.clear();
    document.getElementById('nokia-param-section').hidden = true;
    document.getElementById('nokia-site-paste').value = '';
    const pasteStatus = document.getElementById('nokia-site-paste-status');
    pasteStatus.hidden = true;
    pasteStatus.textContent = '';
    const areaFilter = document.getElementById('nokia-area-filter-list');
    if (areaFilter) areaFilter.checked = false;
    loadNokiaSites();
    loadNokiaAreas();
    loadMoClasses();
    updateActionState();
}

function parsePastedSiteIds(text) {
    return [...new Set(
        String(text || '')
            .split(/[\s,;]+/)
            .map((token) => token.trim())
            .filter(Boolean),
    )];
}

function resolveNokiaCatalogSiteId(id) {
    const token = String(id || '').trim();
    if (!token) return token;
    const direct = nokiaSiteCatalog.find((site) => site.site_id === token);
    if (direct) return direct.site_id;
    const byMetadata = nokiaSiteCatalog.find((site) => site.metadata_site_id === token);
    return byMetadata ? byMetadata.site_id : token;
}

function applyPastedSiteIds() {
    const ids = parsePastedSiteIds(document.getElementById('nokia-site-paste').value);
    const statusEl = document.getElementById('nokia-site-paste-status');
    if (!ids.length) {
        statusEl.hidden = false;
        statusEl.textContent = 'No site IDs found in pasted text.';
        return;
    }

    const known = new Set(nokiaSiteCatalog.map((site) => site.site_id));
    const unknown = [];
    ids.forEach((id) => {
        const resolvedId = resolveNokiaCatalogSiteId(id);
        selectedSiteIds.add(resolvedId);
        if (!known.has(resolvedId)) unknown.push(id);
    });

    renderSiteList();
    updateActionState();
    statusEl.hidden = false;
    if (unknown.length) {
        const preview = unknown.slice(0, 8).join(', ');
        statusEl.textContent = `Selected ${ids.length} id(s). ${unknown.length} not in the database list but will still be used: ${preview}${unknown.length > 8 ? '…' : ''}`;
    } else {
        statusEl.textContent = `Selected ${ids.length} site id(s) from pasted text.`;
    }
}

async function loadNokiaSites() {
    const loading = document.getElementById('nokia-site-loading');
    const errorEl = document.getElementById('nokia-site-error');
    const listEl = document.getElementById('nokia-site-list');

    errorEl.hidden = true;
    errorEl.textContent = '';
    loading.hidden = false;
    loading.textContent = `Loading ${getScopeLevel()} ids from NetAct inventory…`;
    listEl.hidden = true;

    try {
        const scope = encodeURIComponent(getScopeLevel());
        const response = await fetch(`/api/cm-extractor/nokia/sites?scope=${scope}&limit=3000&v=2`, {
            credentials: 'same-origin',
        });
        const data = await response.json();
        if (!response.ok || !data.success) {
            throw new Error(data.error || 'Failed to load Nokia sites');
        }
        nokiaSiteCatalog = data.sites || [];
        if (!nokiaSiteCatalog.length) {
            throw new Error(`No ${getScopeLevel()} entries found in the database. Run metadata sync first.`);
        }
        await loadNokiaAreas();
        listEl.hidden = false;
        renderSiteList();
    } catch (error) {
        errorEl.hidden = false;
        errorEl.textContent = error.message || 'Failed to load Nokia sites';
    } finally {
        loading.hidden = true;
    }
}

async function loadNokiaAreas() {
    const select = document.getElementById('nokia-area-select');
    const row = document.getElementById('nokia-area-row');
    if (!select || !row) return;
    try {
        const scope = encodeURIComponent(getScopeLevel());
        const response = await fetch(`/api/cm-extractor/nokia/areas?scope=${scope}&v=2`, {
            credentials: 'same-origin',
        });
        const data = await response.json();
        if (!response.ok || !data.success) {
            throw new Error(data.error || 'Failed to load areas');
        }
        nokiaAreas = data.areas || [];
    } catch (error) {
        nokiaAreas = [];
    }
    row.hidden = !nokiaAreas.length;
    const previous = select.value;
    select.innerHTML = '<option value="">All areas</option>' +
        nokiaAreas.map((a) =>
            `<option value="${escapeHtml(a.area)}">${escapeHtml(a.area)} (${a.site_count})</option>`
        ).join('');
    if (previous && nokiaAreas.some((a) => a.area === previous)) {
        select.value = previous;
    }
}

function selectedNokiaArea() {
    return document.getElementById('nokia-area-select')?.value || '';
}

function addNokiaAreaSites() {
    const area = selectedNokiaArea();
    const statusEl = document.getElementById('nokia-site-paste-status');
    if (!area) {
        statusEl.hidden = false;
        statusEl.textContent = 'Pick an area first, then click Add all sites in area.';
        return;
    }
    const matches = nokiaSiteCatalog.filter((site) => site.area === area);
    if (!matches.length) {
        statusEl.hidden = false;
        statusEl.textContent = `No sites found for area "${area}" in the current list.`;
        return;
    }
    matches.forEach((site) => selectedSiteIds.add(site.site_id));
    renderSiteList();
    updateActionState();
    statusEl.hidden = false;
    statusEl.textContent = `Added ${matches.length} site(s) from area "${area}".`;
}

function filteredSites() {
    const query = document.getElementById('nokia-site-search').value.trim().toLowerCase();
    const areaFilterOn = document.getElementById('nokia-area-filter-list')?.checked;
    const area = areaFilterOn ? selectedNokiaArea() : '';
    return nokiaSiteCatalog.filter((site) => {
        if (area && site.area !== area) return false;
        if (!query) return true;
        const hay = `${site.site_id} ${site.metadata_site_id || ''} ${site.site_name} ${site.label} ${site.area || ''} ${site.cluster || ''}`.toLowerCase();
        return hay.includes(query);
    });
}

function renderSiteList() {
    const listEl = document.getElementById('nokia-site-list');
    const hintEl = document.getElementById('nokia-site-selection-hint');
    const filtered = filteredSites();

    const fragment = document.createDocumentFragment();
    filtered.forEach((site) => {
        const label = document.createElement('label');
        label.className = 'mo-class-item site-item';
        label.dataset.siteId = site.site_id;
        const cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.value = site.site_id;
        cb.checked = selectedSiteIds.has(site.site_id);
        cb.addEventListener('change', () => {
            if (cb.checked) selectedSiteIds.add(site.site_id);
            else selectedSiteIds.delete(site.site_id);
            updateSiteSelectionHint();
            updateActionState();
        });
        label.appendChild(cb);
        const display = nokiaSiteDisplay(site);
        const text = document.createElement('span');
        text.textContent = display.title;
        if (isCmAdmin && site.cell_count) {
            text.title = `${site.cell_count} cell(s) in database`;
        }
        label.appendChild(text);
        if (display.meta) {
            const meta = document.createElement('span');
            meta.className = 'mo-class-meta';
            meta.textContent = display.meta;
            label.appendChild(meta);
        }
        fragment.appendChild(label);
    });

    listEl.innerHTML = '';
    if (!filtered.length) {
        listEl.innerHTML = '<p class="loading-hint">No sites match your search.</p>';
    } else {
        listEl.appendChild(fragment);
    }

    hintEl.hidden = false;
    updateSiteSelectionHint();
}

function updateSiteSelectionHint() {
    const hintEl = document.getElementById('nokia-site-selection-hint');
    if (!selectedSiteIds.size) {
        hintEl.textContent = `${nokiaSiteCatalog.length} ${getScopeLevel()} id(s) available — select manually or paste a list.`;
        return;
    }
    hintEl.textContent = `${selectedSiteIds.size} ${getScopeLevel()} id(s) selected.`;
}

function selectAllSites() {
    nokiaSiteCatalog.forEach((site) => selectedSiteIds.add(site.site_id));
    renderSiteList();
    updateActionState();
}

function selectVisibleSites() {
    filteredSites().forEach((site) => selectedSiteIds.add(site.site_id));
    renderSiteList();
    updateActionState();
}

function clearSiteSelection() {
    selectedSiteIds.clear();
    document.getElementById('nokia-site-paste').value = '';
    const pasteStatus = document.getElementById('nokia-site-paste-status');
    pasteStatus.hidden = true;
    pasteStatus.textContent = '';
    renderSiteList();
    updateActionState();
}

const HUAWEI_SCOPE_PASTE_PLACEHOLDER = {
    ENODEB: 'Paste 4G eNodeB site IDs (comma, space, or new line)\ne.g. 1001, 1002, 1211',
    RNC: 'Paste RNC ids (comma, space, or new line)\ne.g. 1, 2 or RNC01',
    BSC: 'Paste BSC ids (comma, space, or new line)\ne.g. HQ_01, BSC_HQ_01',
};

const HUAWEI_SCOPE_TITLES = {
    ENODEB: 'Sites (4G eNodeB)',
    RNC: 'RNCs (3G)',
    BSC: 'BSCs (2G)',
};

function getHuaweiScopeLevel() {
    return document.querySelector('input[name="huawei-scope-level"]:checked')?.value || 'ENODEB';
}

function isHuaweiControllerScope(level = getHuaweiScopeLevel()) {
    return level === 'RNC' || level === 'BSC';
}

function onHuaweiScopeLevelChanged() {
    const level = getHuaweiScopeLevel();
    const title = document.getElementById('huawei-ne-picker-title');
    if (title) title.textContent = HUAWEI_SCOPE_TITLES[level] || HUAWEI_SCOPE_TITLES.ENODEB;
    const paste = document.getElementById('huawei-ne-paste');
    if (paste) paste.placeholder = HUAWEI_SCOPE_PASTE_PLACEHOLDER[level] || HUAWEI_SCOPE_PASTE_PLACEHOLDER.ENODEB;
    const areaRow = document.getElementById('huawei-area-row');
    if (areaRow) areaRow.hidden = isHuaweiControllerScope(level);
    selectedHuaweiSiteIds.clear();
    selectedHuaweiMoObjects.clear();
    selectedHuaweiParamsByMo.clear();
    huaweiParametersByMo.clear();
    fullMoByHuaweiObject.clear();
    document.getElementById('huawei-param-section').hidden = true;
    if (paste) paste.value = '';
    const pasteStatus = document.getElementById('huawei-ne-paste-status');
    if (pasteStatus) {
        pasteStatus.hidden = true;
        pasteStatus.textContent = '';
    }
    const areaFilter = document.getElementById('huawei-area-filter-list');
    if (areaFilter) areaFilter.checked = false;
    loadHuaweiNeCatalog();
    loadHuaweiAreas();
    loadHuaweiMoObjects();
    updateHuaweiActionState();
}

function setVendor(vendor) {
    activeVendor = vendor;
    document.querySelectorAll('.vendor-tab').forEach((btn) => {
        const active = btn.dataset.vendor === vendor;
        btn.classList.toggle('active', active);
        btn.setAttribute('aria-selected', active ? 'true' : 'false');
    });
    document.getElementById('nokia-workflow').hidden = vendor !== 'nokia';
    const huaweiWorkflow = document.getElementById('huawei-workflow');
    if (huaweiWorkflow) huaweiWorkflow.hidden = vendor !== 'huawei';
    if (vendor === 'huawei' && huaweiWorkflow && !huaweiCatalogLoaded) {
        loadHuaweiNeCatalog();
        loadHuaweiAreas();
        loadHuaweiMoObjects();
        huaweiCatalogLoaded = true;
    }
    if (schedJobsCache.jobs.length) {
        renderScheduledJobs(schedJobsCache.jobs, schedJobsCache.isAdmin);
    }
}

async function loadHuaweiNeCatalog({ refreshU2020 = false } = {}) {
    const loading = document.getElementById('huawei-ne-loading');
    const errorEl = document.getElementById('huawei-ne-error');
    const listEl = document.getElementById('huawei-ne-list');
    const syncStatus = document.getElementById('huawei-u2020-sync-status');

    errorEl.hidden = true;
    errorEl.textContent = '';
    loading.hidden = false;
    loading.textContent = refreshU2020
        ? 'Discovering NE names from U2020 (FM alarms)…'
        : `Loading ${HUAWEI_SCOPE_TITLES[getHuaweiScopeLevel()] || 'Huawei NEs'} from database…`;
    listEl.hidden = true;

    try {
        const scope = encodeURIComponent(getHuaweiScopeLevel());
        const refresh = refreshU2020 ? '&refresh=1' : '';
        const response = await fetch(`/api/cm-extractor/huawei/sites?scope=${scope}&limit=3000${refresh}`, {
            credentials: 'same-origin',
        });
        const data = await response.json();
        if (!response.ok || !data.success) {
            throw new Error(data.error || 'Failed to load Huawei NEs');
        }
        huaweiNeCatalog = data.sites || [];
        if (!huaweiNeCatalog.length) {
            throw new Error(`No ${getHuaweiScopeLevel()} entries found in the database. Run metadata sync first.`);
        }
        if (syncStatus) {
            const catalogSize = data.u2020_catalog_size || 0;
            const resolved = data.u2020_resolved_in_list || 0;
            let text = `U2020 catalog: ${catalogSize} NE name(s); ${resolved} visible site(s) mapped to OSS meName.`;
            if (data.discovery) {
                text = `Synced ${data.discovery.ne_count} NE name(s) from U2020. ${text}`;
            }
            syncStatus.textContent = text;
        }
        listEl.hidden = false;
        renderHuaweiNeList();
    } catch (error) {
        errorEl.hidden = false;
        errorEl.textContent = error.message || 'Failed to load Huawei NEs';
    } finally {
        loading.hidden = true;
    }
}

async function syncHuaweiFromU2020({ silent = false } = {}) {
    const btn = document.getElementById('huawei-sync-u2020-btn');
    if (btn) btn.disabled = true;
    if (!silent) {
        showNotification('Discovering NE names from U2020… this can take ~30 seconds.', 'info');
    }
    try {
        const response = await fetch('/api/cm-extractor/huawei/discover', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ...huaweiPayload(), discover_mos: !silent }),
        });
        const data = await response.json();
        if (!response.ok || !data.success) {
            if (silent) {
                await loadHuaweiNeCatalog();
                return;
            }
            throw new Error(data.error || 'U2020 discovery failed');
        }
        await loadHuaweiNeCatalog();
        await loadHuaweiMoObjects();
        if (!silent) {
            showNotification(data.message || 'U2020 discovery complete', 'success');
        }
    } catch (error) {
        if (!silent) {
            showNotification(error.message || 'U2020 sync failed', 'error');
        } else {
            await loadHuaweiNeCatalog();
        }
    } finally {
        if (btn) btn.disabled = false;
    }
}

async function loadHuaweiAreas() {
    const select = document.getElementById('huawei-area-select');
    if (!select) return;
    try {
        const scope = encodeURIComponent(getHuaweiScopeLevel());
        const response = await fetch(`/api/cm-extractor/huawei/areas?scope=${scope}`, {
            credentials: 'same-origin',
        });
        const data = await response.json();
        if (!response.ok || !data.success) {
            throw new Error(data.error || 'Failed to load areas');
        }
        huaweiAreas = data.areas || [];
    } catch (error) {
        huaweiAreas = [];
    }
    const previous = select.value;
    select.innerHTML = '<option value="">All areas</option>' +
        huaweiAreas.map((a) =>
            `<option value="${escapeHtml(a.area)}">${escapeHtml(a.area)} (${a.site_count})</option>`
        ).join('');
    if (previous && huaweiAreas.some((a) => a.area === previous)) {
        select.value = previous;
    }
}

function selectedHuaweiArea() {
    return document.getElementById('huawei-area-select')?.value || '';
}

function addHuaweiAreaSites() {
    const area = selectedHuaweiArea();
    const statusEl = document.getElementById('huawei-ne-paste-status');
    if (!area) {
        statusEl.hidden = false;
        statusEl.textContent = 'Pick an area first, then click Add all sites in area.';
        return;
    }
    const matches = huaweiNeCatalog.filter((site) => site.area === area);
    if (!matches.length) {
        statusEl.hidden = false;
        statusEl.textContent = `No sites found for area "${area}" in the current list.`;
        return;
    }
    matches.forEach((site) => selectedHuaweiSiteIds.add(site.site_id));
    renderHuaweiNeList();
    updateHuaweiActionState();
    statusEl.hidden = false;
    statusEl.textContent = `Added ${matches.length} site(s) from area "${area}".`;
}

function filteredHuaweiNes() {
    const query = document.getElementById('huawei-ne-search').value.trim().toLowerCase();
    const areaFilterOn = document.getElementById('huawei-area-filter-list')?.checked;
    const area = areaFilterOn ? selectedHuaweiArea() : '';
    return huaweiNeCatalog.filter((site) => {
        if (area && site.area !== area) return false;
        if (!query) return true;
        const hay = `${site.site_id} ${site.site_name} ${site.ne_name} ${site.label} ${site.area || ''} ${site.cluster || ''}`.toLowerCase();
        return hay.includes(query);
    });
}

function renderHuaweiNeList() {
    const listEl = document.getElementById('huawei-ne-list');
    const hintEl = document.getElementById('huawei-ne-selection-hint');
    const sites = filteredHuaweiNes();
    listEl.innerHTML = sites.map((site) => {
        const checked = selectedHuaweiSiteIds.has(site.site_id) ? 'checked' : '';
        const display = huaweiSiteDisplay(site);
        const metaHtml = display.meta
            ? `<span class="mo-class-meta">${escapeHtml(display.meta)}</span>`
            : '';
        return `
            <label class="mo-class-item${display.unresolved ? ' site-unresolved' : ''}">
                <input type="checkbox" data-site-id="${escapeHtml(site.site_id)}" ${checked}>
                <span class="mo-class-label">${escapeHtml(display.title)}</span>
                ${metaHtml}
            </label>`;
    }).join('');

    listEl.querySelectorAll('input[type="checkbox"]').forEach((input) => {
        input.addEventListener('change', () => {
            const siteId = input.dataset.siteId;
            if (input.checked) selectedHuaweiSiteIds.add(siteId);
            else selectedHuaweiSiteIds.delete(siteId);
            updateHuaweiActionState();
        });
    });

    hintEl.hidden = !selectedHuaweiSiteIds.size;
    hintEl.textContent = `${selectedHuaweiSiteIds.size} NE(s) selected.`;
}

function selectAllHuaweiNes() {
    huaweiNeCatalog.forEach((site) => selectedHuaweiSiteIds.add(site.site_id));
    renderHuaweiNeList();
    updateHuaweiActionState();
}

function selectVisibleHuaweiNes() {
    filteredHuaweiNes().forEach((site) => selectedHuaweiSiteIds.add(site.site_id));
    renderHuaweiNeList();
    updateHuaweiActionState();
}

function clearHuaweiNeSelection() {
    selectedHuaweiSiteIds.clear();
    document.getElementById('huawei-ne-paste').value = '';
    const pasteStatus = document.getElementById('huawei-ne-paste-status');
    pasteStatus.hidden = true;
    pasteStatus.textContent = '';
    renderHuaweiNeList();
    updateHuaweiActionState();
}

function applyPastedHuaweiNeIds() {
    const ids = parsePastedSiteIds(document.getElementById('huawei-ne-paste').value);
    const statusEl = document.getElementById('huawei-ne-paste-status');
    if (!ids.length) {
        statusEl.hidden = false;
        statusEl.textContent = 'No site IDs found in pasted text.';
        return;
    }

    const known = new Set(huaweiNeCatalog.map((site) => site.site_id));
    const unknown = [];
    ids.forEach((id) => {
        selectedHuaweiSiteIds.add(id);
        if (!known.has(id)) unknown.push(id);
    });

    renderHuaweiNeList();
    updateHuaweiActionState();
    statusEl.hidden = false;
    if (unknown.length) {
        const preview = unknown.slice(0, 8).join(', ');
        statusEl.textContent = `Selected ${ids.length} id(s). ${unknown.length} not in the database list but will still be used: ${preview}${unknown.length > 8 ? '…' : ''}`;
    } else {
        statusEl.textContent = `Selected ${ids.length} NE id(s) from pasted text.`;
    }
}

async function loadHuaweiMoObjects() {
    const loading = document.getElementById('huawei-mo-loading');
    const errorEl = document.getElementById('huawei-mo-error');
    const listEl = document.getElementById('huawei-mo-list');

    errorEl.hidden = true;
    errorEl.textContent = '';
    loading.hidden = false;
    listEl.hidden = true;

    try {
        const scope = encodeURIComponent(getHuaweiScopeLevel());
        const response = await fetch(`/api/cm-extractor/huawei/mo-objects?scope=${scope}`, { credentials: 'same-origin' });
        const data = await response.json();
        if (!response.ok || !data.success) {
            throw new Error(data.error || 'Failed to load MML object catalog');
        }
        huaweiMoCatalog = data.mo_objects || [];
        listEl.hidden = false;
        renderHuaweiMoList();
    } catch (error) {
        errorEl.hidden = false;
        errorEl.textContent = error.message || 'Failed to load MML object catalog';
    } finally {
        loading.hidden = true;
    }
}

function filteredHuaweiMoObjects() {
    const query = document.getElementById('huawei-mo-search').value.trim().toLowerCase();
    return huaweiMoCatalog.filter((mo) => {
        if (!query) return true;
        const hay = `${mo.id} ${mo.label} ${mo.technology} ${mo.group} ${mo.command}`.toLowerCase();
        return hay.includes(query);
    });
}

function renderHuaweiMoList() {
    const listEl = document.getElementById('huawei-mo-list');
    const objects = filteredHuaweiMoObjects();
    listEl.innerHTML = objects.map((mo) => {
        const checked = selectedHuaweiMoObjects.has(mo.id) ? 'checked' : '';
        const display = huaweiMoDisplay(mo);
        const metaHtml = display.meta
            ? `<span class="mo-class-meta">${escapeHtml(display.meta)}</span>`
            : '';
        return `
            <label class="mo-class-item">
                <input type="checkbox" data-mo-id="${escapeHtml(mo.id)}" ${checked}>
                <span class="mo-class-label">${escapeHtml(display.title)}</span>
                ${metaHtml}
            </label>`;
    }).join('');

    listEl.querySelectorAll('input[type="checkbox"]').forEach((input) => {
        input.addEventListener('change', async () => {
            const moId = input.dataset.moId;
            if (input.checked) {
                const mo = huaweiMoCatalog.find((item) => item.id === moId);
                if (mo) selectedHuaweiMoObjects.set(moId, mo);
                await ensureHuaweiParametersLoaded(moId);
            } else {
                selectedHuaweiMoObjects.delete(moId);
                selectedHuaweiParamsByMo.delete(moId);
                fullMoByHuaweiObject.delete(moId);
            }
            renderHuaweiParameterGroups();
            updateHuaweiActionState();
        });
    });
}

async function fetchHuaweiParametersBatch(moIds) {
    const ids = [...new Set((moIds || []).filter(Boolean))].filter((id) => !huaweiParametersByMo.has(id));
    if (!ids.length) return;
    const loading = document.getElementById('huawei-param-loading');
    if (loading) loading.hidden = false;
    try {
        const response = await fetch('/api/cm-extractor/huawei/parameters', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mo_ids: ids }),
        });
        const data = await response.json();
        if (!response.ok || !data.success) {
            throw new Error(data.error || 'Failed to load parameters');
        }
        Object.entries(data.parameters || {}).forEach(([id, params]) => {
            huaweiParametersByMo.set(id, params);
        });
    } finally {
        if (loading) loading.hidden = true;
    }
}

async function ensureHuaweiParametersLoaded(moId) {
    if (huaweiParametersByMo.has(moId)) return;
    await fetchHuaweiParametersBatch([moId]);
}

async function addHuaweiMoSelections(mos) {
    mos.forEach((mo) => {
        selectedHuaweiMoObjects.set(mo.id, mo);
        if (!selectedHuaweiParamsByMo.has(mo.id)) {
            selectedHuaweiParamsByMo.set(mo.id, new Set());
        }
    });
    renderHuaweiMoList();
    await fetchHuaweiParametersBatch(mos.map((mo) => mo.id));
    renderHuaweiParameterGroups();
    updateHuaweiActionState();
}

async function selectAllHuaweiMoObjects() {
    await addHuaweiMoSelections(huaweiMoCatalog);
}

async function selectVisibleHuaweiMoObjects() {
    await addHuaweiMoSelections(filteredHuaweiMoObjects());
}

function clearHuaweiMoSelection() {
    selectedHuaweiMoObjects.clear();
    selectedHuaweiParamsByMo.clear();
    fullMoByHuaweiObject.clear();
    renderHuaweiMoList();
    renderHuaweiParameterGroups();
    updateHuaweiActionState();
}

function renderHuaweiParameterGroups() {
    const section = document.getElementById('huawei-param-section');
    const groupsEl = document.getElementById('huawei-param-groups');
    if (!selectedHuaweiMoObjects.size) {
        section.hidden = true;
        groupsEl.innerHTML = '';
        return;
    }
    section.hidden = false;
    groupsEl.innerHTML = '';

    [...selectedHuaweiMoObjects.entries()].forEach(([moId, mo]) => {
        const block = document.createElement('div');
        block.className = 'param-group-block';
        const isFull = fullMoByHuaweiObject.has(moId);
        const moTitle = huaweiMoDisplay(mo).title;
        block.innerHTML = `
            <div class="param-group-head">
                <strong>${escapeHtml(moTitle)}</strong>
                <label class="checkbox-row compact-checkbox">
                    <input type="checkbox" data-full-mo="${escapeHtml(moId)}" ${isFull ? 'checked' : ''}>
                    All columns (full MML report)
                </label>
            </div>
            <div class="param-checkboxes" data-mo-id="${escapeHtml(moId)}"></div>`;
        groupsEl.appendChild(block);

        const fullCb = block.querySelector(`input[data-full-mo="${moId}"]`);
        fullCb.addEventListener('change', () => {
            if (fullCb.checked) fullMoByHuaweiObject.add(moId);
            else fullMoByHuaweiObject.delete(moId);
            renderHuaweiParameterGroups();
            updateHuaweiActionState();
        });

        if (isFull) return;

        const container = block.querySelector('.param-checkboxes');
        const params = huaweiParametersByMo.get(moId) || [];
        const selected = selectedHuaweiParamsByMo.get(moId) || new Set();
        container.innerHTML = params.map((param) => {
            const pid = param.id || param.name;
            const checked = selected.has(pid) ? 'checked' : '';
            return `
                <label class="param-checkbox" data-param-id="${escapeHtml(pid)}">
                    <input type="checkbox" data-mo-id="${escapeHtml(moId)}" data-param-id="${escapeHtml(pid)}" ${checked}>
                    ${escapeHtml(param.name || pid)}
                </label>`;
        }).join('');

        container.querySelectorAll('input[type="checkbox"]').forEach((input) => {
            input.addEventListener('change', () => {
                const set = selectedHuaweiParamsByMo.get(moId) || new Set();
                if (input.checked) set.add(input.dataset.paramId);
                else set.delete(input.dataset.paramId);
                selectedHuaweiParamsByMo.set(moId, set);
                updateHuaweiActionState();
            });
        });
    });
    filterHuaweiParameterList();
}

function _paramLabelMatchesQuery(label, query) {
    if (!query) return true;
    const paramId = (label.dataset.paramId || '').toLowerCase();
    const title = (label.getAttribute('title') || '').toLowerCase();
    const text = (label.textContent || '').replace(/\s+/g, ' ').trim().toLowerCase();
    return paramId.includes(query) || title.includes(query) || text.includes(query);
}

function _applyParamGroupVisibility(groupsRoot) {
    if (!groupsRoot) return;
    groupsRoot.querySelectorAll('.param-mo-group, .param-group-block').forEach((block) => {
        if (block.querySelector('.full-mo-note')) {
            block.hidden = false;
            return;
        }
        const checks = block.querySelectorAll('.param-check, .param-checkbox');
        if (!checks.length) {
            block.hidden = false;
            return;
        }
        const anyVisible = [...checks].some((el) => !el.hidden);
        block.hidden = !anyVisible;
    });
}

function filterHuaweiParameterList() {
    const query = (document.getElementById('huawei-param-search')?.value || '').trim().toLowerCase();
    const groupsEl = document.getElementById('huawei-param-groups');
    if (!groupsEl) return;
    groupsEl.querySelectorAll('.param-checkbox').forEach((label) => {
        label.hidden = Boolean(query && !_paramLabelMatchesQuery(label, query));
    });
    _applyParamGroupVisibility(groupsEl);
}

function buildHuaweiSelections() {
    return [...selectedHuaweiMoObjects.keys()].map((moId) => {
        const exportAll = fullMoByHuaweiObject.has(moId);
        const params = exportAll ? [] : [...(selectedHuaweiParamsByMo.get(moId) || [])];
        return {
            mo_id: moId,
            export_all: exportAll,
            parameters: params,
        };
    });
}

function huaweiSelectionSummary(selection) {
    if (selection.export_all) {
        return `${selection.mo_id}: all columns`;
    }
    return `${selection.mo_id}: ${selection.parameters.length} column(s)`;
}

function updateHuaweiActionState() {
    const selections = buildHuaweiSelections();
    const nesOk = selectedHuaweiSiteIds.size > 0;
    const valid = nesOk && selections.length > 0 && selections.every(
        (s) => s.export_all || s.parameters.length > 0,
    );
    document.getElementById('huawei-preview-btn').disabled = !valid;
    document.getElementById('huawei-extract-btn').disabled = !valid;

    const info = document.getElementById('huawei-output-info');
    const desc = document.getElementById('huawei-output-desc');
    if (!valid) {
        info.hidden = true;
        return;
    }
    const parts = selections.map(huaweiSelectionSummary);
    const scopeLabel = { ENODEB: '4G eNodeB', RNC: '3G RNC', BSC: '2G BSC' }[getHuaweiScopeLevel()]
        || getHuaweiScopeLevel();
    const batchNote = selectedHuaweiSiteIds.size > 100
        ? ' Runs MML in chunks of 100 NEs per request.'
        : '';
    desc.textContent = `${scopeLabel} — ${selectedHuaweiSiteIds.size} ${isHuaweiControllerScope() ? 'controller(s)' : 'site(s)'}, ${selections.length} object type(s) — ${parts.join('; ')}.${batchNote}`;
    info.hidden = false;
}

function catalogNeNameForSite(site) {
    if (!site) return '';
    const neName = String(site.u2020_ne_name || site.ne_name || '').trim();
    if (neName) return neName;
    const siteName = String(site.site_name || '').trim();
    const siteId = String(site.site_id || '').trim();
    if (siteId && siteName.startsWith(`${siteId}-`)) return siteName;
    return '';
}

function buildHuaweiNeNamesFromSelection() {
    return [...selectedHuaweiSiteIds].map((siteId) => {
        const site = huaweiNeCatalog.find((row) => row.site_id === siteId);
        return catalogNeNameForSite(site);
    }).filter(Boolean);
}

function buildHuaweiPayload() {
    return {
        ...huaweiPayload(),
        scope_level: getHuaweiScopeLevel(),
        site_ids: [...selectedHuaweiSiteIds],
        selections: buildHuaweiSelections(),
    };
}

async function previewHuawei() {
    const panel = document.getElementById('huawei-preview');
    const countEl = document.getElementById('huawei-preview-count');
    panel.hidden = false;
    countEl.textContent = 'Loading preview…';

    try {
        const response = await fetch('/api/cm-extractor/huawei/preview', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(buildHuaweiPayload()),
        });
        const data = await response.json();
        if (!data.success) {
            countEl.textContent = data.error || 'Preview failed';
            return;
        }
        let summary = `Total ${data.count} row(s) across ${(data.sheet_names || []).join(', ')}`;
        if (data.warnings?.length) {
            summary += `. ${data.warnings.join(' ')}`;
        }
        countEl.textContent = summary;
        const wrap = document.getElementById('huawei-preview-tables');
        wrap.innerHTML = '';
        renderPreviewTablesInto(wrap, data.sheets);
    } catch (error) {
        countEl.textContent = error.message;
    }
}

function renderPreviewTablesInto(wrap, sheets) {
    Object.entries(sheets || {}).forEach(([sheetName, sheet]) => {
        const block = document.createElement('div');
        block.className = 'preview-sheet-block';
        block.innerHTML = `<div class="preview-sheet-title">${escapeHtml(sheetName)} (${sheet.count} rows)</div>`;
        const tableWrap = document.createElement('div');
        tableWrap.className = 'preview-table-wrap';

        let html = '<table class="preview-table"><thead><tr>';
        (sheet.columns || []).forEach((col) => { html += `<th>${escapeHtml(col)}</th>`; });
        html += '</tr></thead><tbody>';
        (sheet.rows || []).forEach((row) => {
            html += '<tr>';
            row.forEach((cell) => { html += `<td>${escapeHtml(cell == null ? '' : String(cell))}</td>`; });
            html += '</tr>';
        });
        html += '</tbody></table>';
        tableWrap.innerHTML = html;
        block.appendChild(tableWrap);
        wrap.appendChild(block);
    });
}

async function loadMoClasses() {
    const loading = document.getElementById('nokia-mo-loading');
    const errorEl = document.getElementById('nokia-mo-error');
    const retryBtn = document.getElementById('nokia-mo-retry');
    const listEl = document.getElementById('nokia-mo-list');

    errorEl.hidden = true;
    retryBtn.hidden = true;
    errorEl.textContent = '';
    loading.hidden = false;
    loading.textContent = 'Loading MO classes from NetAct…';
    listEl.hidden = true;

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 90000);

    try {
        const scope = encodeURIComponent(getScopeLevel());
        const response = await fetch(`/api/cm-extractor/nokia/mo-classes?scope=${scope}`, {
            credentials: 'same-origin',
            signal: controller.signal,
        });
        let data;
        try {
            data = await response.json();
        } catch {
            throw new Error(`Invalid server response (HTTP ${response.status}). Try refreshing or re-login.`);
        }
        if (!response.ok || !data.success) {
            throw new Error(data.error || `Failed to load MO classes (HTTP ${response.status})`);
        }
        moClassCatalog = data.mo_classes || [];
        if (!moClassCatalog.length) {
            throw new Error('NetAct returned no MO classes. Check CM API access.');
        }
        listEl.hidden = false;
        renderMoClassList();
    } catch (error) {
        errorEl.hidden = false;
        retryBtn.hidden = false;
        if (error.name === 'AbortError') {
            errorEl.textContent = 'Timed out loading MO classes from NetAct (90s). Check network/VPN and restart the app.';
        } else {
            errorEl.textContent = error.message || 'Failed to load MO classes';
        }
    } finally {
        clearTimeout(timeoutId);
        loading.hidden = true;
    }
}

function filteredMoClasses() {
    const query = document.getElementById('nokia-mo-search').value.trim().toLowerCase();
    return moClassCatalog.filter((mo) => {
        if (!query) return true;
        const hay = `${mo.label} ${mo.group} ${mo.id}`.toLowerCase();
        return hay.includes(query);
    });
}

async function addMoClassSelections(mos) {
    mos.forEach((mo) => {
        selectedMoClasses.set(mo.id, mo);
        if (!selectedParamsByClass.has(mo.id)) {
            selectedParamsByClass.set(mo.id, new Set());
        }
    });
    renderMoClassList();
    await refreshParameterPanels();
    updateActionState();
}

async function selectAllMoClasses() {
    await addMoClassSelections(moClassCatalog);
}

async function selectVisibleMoClasses() {
    await addMoClassSelections(filteredMoClasses());
}

function clearMoClassSelection() {
    selectedMoClasses.clear();
    selectedParamsByClass.clear();
    fullMoByClass.clear();
    renderMoClassList();
    refreshParameterPanels();
    updateActionState();
}

function renderMoClassList() {
    const listEl = document.getElementById('nokia-mo-list');
    const filtered = filteredMoClasses();

    const byGroup = {};
    filtered.forEach((mo) => {
        if (!byGroup[mo.group]) byGroup[mo.group] = [];
        byGroup[mo.group].push(mo);
    });

    const fragment = document.createDocumentFragment();
    Object.keys(byGroup).sort().forEach((group) => {
        const groupEl = document.createElement('div');
        groupEl.className = 'mo-group';
        groupEl.innerHTML = `<div class="mo-group-title">${escapeHtml(group)}</div>`;
        const itemsEl = document.createElement('div');
        itemsEl.className = 'mo-group-items';

        byGroup[group].forEach((mo) => {
            const label = document.createElement('label');
            label.className = 'mo-class-item';
            const cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.value = mo.id;
            cb.checked = selectedMoClasses.has(mo.id);
            cb.addEventListener('change', () => onMoClassToggle(mo, cb.checked));
            label.appendChild(cb);
            label.appendChild(document.createTextNode(mo.label));
            itemsEl.appendChild(label);
        });

        groupEl.appendChild(itemsEl);
        fragment.appendChild(groupEl);
    });
    listEl.innerHTML = '';
    listEl.appendChild(fragment);

    if (!filtered.length) {
        listEl.innerHTML = '<p class="loading-hint">No MO classes match your search.</p>';
    }
}

async function onMoClassToggle(mo, checked) {
    if (checked) {
        selectedMoClasses.set(mo.id, mo);
        if (!selectedParamsByClass.has(mo.id)) {
            selectedParamsByClass.set(mo.id, new Set());
        }
    } else {
        selectedMoClasses.delete(mo.id);
        selectedParamsByClass.delete(mo.id);
        parametersByClass.delete(mo.id);
        fullMoByClass.delete(mo.id);
    }
    await refreshParameterPanels();
    updateActionState();
}

async function refreshParameterPanels() {
    const section = document.getElementById('nokia-param-section');
    const groupsEl = document.getElementById('nokia-param-groups');
    const loading = document.getElementById('nokia-param-loading');

    if (!selectedMoClasses.size) {
        section.hidden = true;
        groupsEl.innerHTML = '';
        return;
    }

    section.hidden = false;
    const needFetch = [...selectedMoClasses.keys()].filter((id) => !parametersByClass.has(id));

    if (needFetch.length) {
        loading.hidden = false;
        try {
            const response = await fetch('/api/cm-extractor/nokia/parameters', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    mo_classes: needFetch.map((id) => {
                        const mo = selectedMoClasses.get(id);
                        return { mo_class_id: id, id, version: mo.version };
                    }),
                }),
            });
            const data = await response.json();
            if (!data.success) throw new Error(data.error || 'Failed to load parameters');
            Object.entries(data.parameters || {}).forEach(([classId, params]) => {
                parametersByClass.set(classId, params);
            });
        } catch (error) {
            showNotification(error.message, 'error');
        } finally {
            loading.hidden = true;
        }
    }

    groupsEl.innerHTML = '';
    [...selectedMoClasses.values()].forEach((mo) => {
        const params = parametersByClass.get(mo.id) || [];
        const group = document.createElement('div');
        group.className = 'param-mo-group';
        group.dataset.moId = mo.id;

        const head = document.createElement('div');
        head.className = 'param-mo-head';
        const isFullMo = fullMoByClass.has(mo.id);
        head.innerHTML = `
            <strong>${escapeHtml(mo.abbreviation)}</strong>
            <span class="field-hint">${escapeHtml(mo.group)}</span>
            <button type="button" class="link-btn full-mo-params" data-mo-id="${escapeHtml(mo.id)}">${isFullMo ? 'Full MO selected' : 'Full MO export'}</button>
            <button type="button" class="link-btn clear-all-params" data-mo-id="${escapeHtml(mo.id)}">Clear</button>
        `;
        group.appendChild(head);

        const grid = document.createElement('div');
        grid.className = 'param-checkboxes';
        const selected = selectedParamsByClass.get(mo.id) || new Set();

        if (isFullMo) {
            grid.innerHTML = '<p class="loading-hint full-mo-note">Full MO export — NetAct returns every instance with all parameters (including structured/list fields).</p>';
        } else if (!params.length) {
            grid.innerHTML = '<p class="loading-hint">No parameters returned for this MO class.</p>';
        } else {
            params.forEach((param) => {
                const queryable = param.queryable !== false;
                const label = document.createElement('label');
                label.className = `param-check${queryable ? '' : ' param-structured'}`;
                label.dataset.paramId = param.id;
                const hint = param.description || (queryable ? '' : 'Structured parameter — use Full MO export');
                if (hint) label.title = hint;
                const cb = document.createElement('input');
                cb.type = 'checkbox';
                cb.value = param.id;
                cb.checked = selected.has(param.id);
                cb.disabled = !queryable;
                cb.addEventListener('change', () => {
                    const set = selectedParamsByClass.get(mo.id) || new Set();
                    if (cb.checked) set.add(param.id);
                    else set.delete(param.id);
                    selectedParamsByClass.set(mo.id, set);
                    updateActionState();
                });
                label.appendChild(cb);
                const text = document.createElement('span');
                text.textContent = param.id;
                label.appendChild(text);
                grid.appendChild(label);
            });
        }

        group.appendChild(grid);
        groupsEl.appendChild(group);
    });

    filterParameterList();

    groupsEl.querySelectorAll('.full-mo-params').forEach((btn) => {
        btn.addEventListener('click', () => {
            const moId = btn.dataset.moId;
            if (fullMoByClass.has(moId)) {
                fullMoByClass.delete(moId);
            } else {
                fullMoByClass.add(moId);
                selectedParamsByClass.set(moId, new Set());
            }
            refreshParameterPanels();
            updateActionState();
        });
    });
    groupsEl.querySelectorAll('.clear-all-params').forEach((btn) => {
        btn.addEventListener('click', () => {
            const moId = btn.dataset.moId;
            selectedParamsByClass.set(moId, new Set());
            fullMoByClass.delete(moId);
            refreshParameterPanels();
            updateActionState();
        });
    });
}

function filterParameterList() {
    const query = (document.getElementById('nokia-param-search')?.value || '').trim().toLowerCase();
    const groupsEl = document.getElementById('nokia-param-groups');
    if (!groupsEl) return;
    groupsEl.querySelectorAll('.param-check').forEach((label) => {
        label.hidden = Boolean(query && !_paramLabelMatchesQuery(label, query));
    });
    _applyParamGroupVisibility(groupsEl);
}

function buildNokiaSelections() {
    return [...selectedMoClasses.entries()].map(([moId, mo]) => {
        const isFullMo = fullMoByClass.has(moId);
        const params = isFullMo ? [] : [...(selectedParamsByClass.get(moId) || [])];
        return {
            mo_class_id: moId,
            version: mo.version,
            parameters: params,
            export_mode: isFullMo ? 'full' : 'selected',
        };
    });
}

function selectionSummary(selection) {
    const abbr = selection.mo_class_id.split(':').pop();
    if (selection.export_mode === 'full') {
        return `${abbr}: full MO export`;
    }
    const count = selection.parameters.length;
    if (count > QUERY_PARAM_MAX) {
        return `${abbr}: ${count} parameters (will use full MO export)`;
    }
    return `${abbr}: ${count} parameter(s)`;
}

function updateActionState() {
    const selections = buildNokiaSelections();
    const sitesOk = selectedSiteIds.size > 0;
    const valid = sitesOk && selections.length > 0 && selections.every(
        (s) => s.export_mode === 'full' || s.parameters.length > 0,
    );
    document.getElementById('nokia-preview-btn').disabled = !valid;
    document.getElementById('nokia-extract-btn').disabled = !valid;

    const parts = selections.map(selectionSummary);

    const info = document.getElementById('nokia-output-info');
    const desc = document.getElementById('nokia-output-desc');
    if (!valid) {
        info.hidden = true;
        return;
    }
    const level = getScopeLevel();
    const viaOps = isControllerScope(level);
    const heavyNeighbor = selections.some((s) => {
        const abbr = String(s.mo_class_id || '').split(':').pop().toUpperCase();
        return abbr.startsWith('LNREL') || abbr.startsWith('LNADJ') || abbr.startsWith('LNHOIF');
    });
    const methodNote = viaOps
        ? (bulkExportSshConfigured
            ? 'via CM Operations Import_Export'
            : 'via CM Open API (SFTP not configured — partial RNC/BSC data)')
        : (heavyNeighbor && bulkExportSshConfigured
            ? 'via CM Operations Import_Export (neighbor MOs — scoped to selected sites)'
            : (heavyNeighbor
                ? 'via scoped CM Open API (LNREL/LNADJ never dump the whole network)'
                : 'via CM Open API'));
    desc.textContent = `${level} scope — ${selectedSiteIds.size} id(s), ${selections.length} MO class(es) — ${parts.join('; ')}. ${methodNote}. One Excel sheet per MO class.`;
    info.hidden = false;
}

function nokiaPayload() {
    return {
        vendor: 'nokia',
        scope_level: getScopeLevel(),
        conf_id: parseInt(document.getElementById('nokia-conf-id').value, 10),
        site_ids: [...selectedSiteIds],
        selections: buildNokiaSelections(),
    };
}

function huaweiPayload() {
    return { vendor: 'huawei' };
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function renderPreviewTables(sheets) {
    const wrap = document.getElementById('nokia-preview-tables');
    wrap.innerHTML = '';
    renderPreviewTablesInto(wrap, sheets);
}

async function previewNokia() {
    const panel = document.getElementById('nokia-preview');
    const countEl = document.getElementById('nokia-preview-count');
    panel.hidden = false;
    countEl.textContent = 'Loading preview…';

    try {
        const response = await fetch('/api/cm-extractor/nokia/preview', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(nokiaPayload()),
        });
        const data = await response.json();
        if (!data.success) {
            countEl.textContent = data.error || 'Preview failed';
            return;
        }
        let summary = `Total ${data.count} row(s) across ${(data.sheet_names || []).join(', ')}`;
        if (data.warnings?.length) {
            summary += `. ${data.warnings.join(' ')}`;
        }
        countEl.textContent = summary;
        renderPreviewTables(data.sheets);
    } catch (error) {
        countEl.textContent = error.message;
    }
}

let extractCreepTimer = null;
let extractElapsedTimer = null;

function setExtractButtonsDisabled(disabled) {
    ['nokia-extract-btn', 'huawei-extract-btn', 'nokia-preview-btn',
     'huawei-preview-btn'].forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.disabled = disabled;
    });
}

function startControllerExtractPhaseTimer() {
    const bulkStartTs = Date.now();
    clearInterval(bulkPhaseTimer);
    bulkPhaseTimer = setInterval(() => {
        const hintEl = document.getElementById('extract-progress-hint');
        const labelEl = document.getElementById('extract-progress-label');
        if (!hintEl) return;
        if (!isCmAdmin) return;
        const elapsedSec = Math.round((Date.now() - bulkStartTs) / 1000);
        if (elapsedSec < 90) {
            if (labelEl) labelEl.textContent = 'Step 1/3 — starting NetAct export…';
            hintEl.textContent = 'Submitting Import_Export to NetAct CM Operations on the OMC.';
        } else if (elapsedSec < Math.max(600, bulkExportTimeoutSec - 300)) {
            if (labelEl) labelEl.textContent = 'Step 2/3 — NetAct is exporting MOs…';
            hintEl.textContent = (
                `NetAct is building the RAML/XML on the OMC (${elapsedSec}s elapsed). `
                + 'This is usually the longest step. You can verify progress in CM Operations Manager.'
            );
        } else {
            if (labelEl) labelEl.textContent = 'Step 3/3 — download & Excel conversion…';
            hintEl.textContent = (
                `Pulling the export file via SFTP and converting to Excel (${elapsedSec}s elapsed). `
                + 'Large controller dumps can take several more minutes here.'
            );
        }
    }, 2000);
}

function stopControllerExtractPhaseTimer() {
    clearInterval(bulkPhaseTimer);
    bulkPhaseTimer = null;
}

function startExtractProgress(hint, label) {
    const section = document.getElementById('extract-progress');
    const fill = document.getElementById('extract-progress-fill');
    const track = section.querySelector('.progress-track');
    const elapsedEl = document.getElementById('extract-progress-elapsed');
    const hintEl = document.getElementById('extract-progress-hint');
    const labelEl = document.getElementById('extract-progress-label');
    if (!section) return;

    document.getElementById('results-section').hidden = true;
    if (labelEl) labelEl.textContent = label || 'Extracting CM data…';
    hintEl.textContent = hint || '';
    setExtractButtonsDisabled(true);
    ['nokia-extract-btn', 'huawei-extract-btn'].forEach((id) => {
        const btn = document.getElementById(id);
        if (btn && typeof setButtonLoading === 'function') {
            setButtonLoading(btn, true, 'Extracting…');
        }
    });

    section.hidden = false;
    section.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

    let pct = 0;
    fill.style.width = '0%';
    track.setAttribute('aria-valuenow', '0');

    const startTs = Date.now();
    elapsedEl.textContent = '0s';
    clearInterval(extractCreepTimer);
    clearInterval(extractElapsedTimer);

    // No backend progress stream: ease toward 90% and let completion finish it.
    extractCreepTimer = setInterval(() => {
        pct += Math.max(0.4, (90 - pct) * 0.05);
        if (pct > 90) pct = 90;
        fill.style.width = `${pct.toFixed(1)}%`;
        track.setAttribute('aria-valuenow', String(Math.round(pct)));
    }, 250);
    extractElapsedTimer = setInterval(() => {
        elapsedEl.textContent = `${Math.round((Date.now() - startTs) / 1000)}s`;
    }, 500);
}

function finishExtractProgress(success) {
    const section = document.getElementById('extract-progress');
    const fill = document.getElementById('extract-progress-fill');
    const track = section ? section.querySelector('.progress-track') : null;
    clearInterval(extractCreepTimer);
    clearInterval(extractElapsedTimer);
    stopControllerExtractPhaseTimer();
    setExtractButtonsDisabled(false);
    ['nokia-extract-btn', 'huawei-extract-btn'].forEach((id) => {
        const btn = document.getElementById(id);
        if (btn && typeof setButtonLoading === 'function') {
            setButtonLoading(btn, false);
        }
    });
    updateActionState();
    if (typeof updateHuaweiActionState === 'function' && document.getElementById('huawei-workflow')) {
        updateHuaweiActionState();
    }
    if (!section) return;
    if (success) {
        fill.style.width = '100%';
        track.setAttribute('aria-valuenow', '100');
        setTimeout(() => { section.hidden = true; }, 700);
    } else {
        section.hidden = true;
    }
}

let nokiaReimportPreviewToken = null;
let nokiaReimportSelectedFile = null;
const NOKIA_REIMPORT_CONFIRMATION = 'APPLY NOKIA EXCEL CHANGES';

function setNokiaReimportStatus(message, type = 'success') {
    const status = document.getElementById('nokia-reimport-status');
    if (!status) return;
    status.hidden = false;
    status.className = `status-message ${type}`;
    status.textContent = message;
}

function updateNokiaReimportExecuteState() {
    const btn = document.getElementById('nokia-reimport-execute-btn');
    const confirm = document.getElementById('nokia-reimport-confirm')?.value.trim();
    if (btn) btn.disabled = !nokiaReimportPreviewToken || confirm !== NOKIA_REIMPORT_CONFIRMATION;
}

function onNokiaReimportFileChanged(event) {
    nokiaReimportSelectedFile = event.target.files?.[0] || null;
    nokiaReimportPreviewToken = null;
    document.getElementById('nokia-reimport-confirm').value = '';
    updateNokiaReimportExecuteState();
    const summary = document.getElementById('nokia-reimport-summary');
    const diff = document.getElementById('nokia-reimport-diff');
    if (summary) summary.hidden = true;
    if (diff) diff.hidden = true;
    if (nokiaReimportSelectedFile) {
        setNokiaReimportStatus(`Ready to preview ${nokiaReimportSelectedFile.name}.`, 'success');
    }
}

function renderNokiaReimportDiff(data) {
    const summary = document.getElementById('nokia-reimport-summary');
    const diff = document.getElementById('nokia-reimport-diff');
    if (!summary || !diff) return;
    summary.hidden = false;
    diff.hidden = false;
    const warnings = data.warnings || [];
    summary.innerHTML = `
        <strong>${data.change_count || 0}</strong> change(s),
        <strong>${data.blocked_count || 0}</strong> blocked item(s)
        ${data.executable ? '' : '<span class="danger-text">Not executable until blocked items are resolved.</span>'}
        ${warnings.length ? `<div>${warnings.map(escapeHtml).join('<br>')}</div>` : ''}
    `;
    const rows = (data.changes || []).slice(0, 100).map((change) => `
        <tr>
            <td>${escapeHtml(change.sheet || '')}</td>
            <td>${escapeHtml(change.target || '')}</td>
            <td>${escapeHtml(change.parameter || '')}</td>
            <td>${escapeHtml(change.old_value || '')}</td>
            <td>${escapeHtml(change.new_value || '')}</td>
        </tr>
    `).join('');
    const blocked = (data.blocked || []).slice(0, 50).map((item) => `
        <li>${escapeHtml(item.sheet || '')} ${escapeHtml(item.target || '')} ${escapeHtml(item.parameter || '')}: ${escapeHtml(item.reason || '')}</li>
    `).join('');
    diff.innerHTML = `
        <table class="reimport-table">
            <thead><tr><th>Sheet</th><th>MO/DN</th><th>Parameter</th><th>Old</th><th>New</th></tr></thead>
            <tbody>${rows || '<tr><td colspan="5">No executable parameter changes detected.</td></tr>'}</tbody>
        </table>
        ${blocked ? `<h4>Blocked items</h4><ul>${blocked}</ul>` : ''}
    `;
}

async function previewNokiaReimport() {
    if (!lastFileId) {
        setNokiaReimportStatus('Export a Nokia Excel workbook first so PrimeNet has a baseline to compare against.', 'error');
        return;
    }
    const fileInput = document.getElementById('nokia-reimport-file');
    const file = nokiaReimportSelectedFile || fileInput?.files?.[0] || null;
    if (!file) {
        setNokiaReimportStatus('Choose the edited Nokia Excel workbook first.', 'error');
        return;
    }
    nokiaReimportSelectedFile = file;
    const form = new FormData();
    form.append('workbook', file);
    form.append('baseline_file_id', lastFileId);
    form.append('allow_blank', document.getElementById('nokia-reimport-allow-blank')?.checked ? '1' : '0');
    const previewBtn = document.getElementById('nokia-reimport-preview-btn');
    if (previewBtn) previewBtn.disabled = true;
    setNokiaReimportStatus(`Uploading ${file.name} and comparing changes...`, 'success');
    try {
        const response = await fetch('/api/cm-extractor/nokia/reimport/preview', {
            method: 'POST',
            body: form,
        });
        const raw = await response.text();
        let data = {};
        try {
            data = raw ? JSON.parse(raw) : {};
        } catch (parseError) {
            throw new Error(`Preview endpoint returned HTTP ${response.status}: ${raw.slice(0, 240) || response.statusText}`);
        }
        if (!response.ok || !data.success) {
            throw new Error(data.error || `Preview failed with HTTP ${response.status}`);
        }
        nokiaReimportPreviewToken = data.token;
        renderNokiaReimportDiff(data);
        updateNokiaReimportExecuteState();
        setNokiaReimportStatus(
            data.executable
                ? 'Preview ready. Review changes, then type the confirmation phrase to execute.'
                : 'Preview completed, but there are blocked items to resolve before execution.',
            data.executable ? 'success' : 'error',
        );
    } catch (error) {
        nokiaReimportPreviewToken = null;
        updateNokiaReimportExecuteState();
        setNokiaReimportStatus(error.message || 'Could not preview Nokia Excel reimport', 'error');
    } finally {
        if (previewBtn) previewBtn.disabled = false;
    }
}

async function executeNokiaReimport() {
    const confirm = document.getElementById('nokia-reimport-confirm')?.value.trim();
    if (!nokiaReimportPreviewToken || confirm !== NOKIA_REIMPORT_CONFIRMATION) {
        setNokiaReimportStatus(`Type ${NOKIA_REIMPORT_CONFIRMATION} before executing.`, 'error');
        return;
    }
    if (!window.confirm('This will upload the reviewed Nokia changes and start a CM Operations import job. Continue?')) {
        return;
    }
    try {
        const response = await fetch('/api/cm-extractor/nokia/reimport/execute', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                token: nokiaReimportPreviewToken,
                confirmation: confirm,
            }),
        });
        const data = await response.json();
        if (!response.ok || !data.success) {
            throw new Error(data.error || 'Nokia Excel reimport failed');
        }
        setNokiaReimportStatus(`Started Nokia operation ${data.operation_id} for ${data.change_count} change(s).`, 'success');
        showNotification('Nokia Excel reimport started', 'success');
    } catch (error) {
        setNokiaReimportStatus(error.message || 'Nokia Excel reimport failed', 'error');
        showNotification('Nokia Excel reimport failed', 'error');
    }
}

async function pollExtractStatus(fileId) {
    const maxWaitMs = 45 * 60 * 1000;
    const started = Date.now();
    while (Date.now() - started < maxWaitMs) {
        await new Promise((resolve) => setTimeout(resolve, 3000));
        const response = await fetch(`/api/cm-extractor/extract-status/${fileId}`, {
            credentials: 'same-origin',
            cache: 'no-store',
        });
        const data = await response.json().catch(() => ({}));
        if (response.status === 401) {
            throw new Error('PrimeNet session expired — refresh the page and sign in again.');
        }
        if (!response.ok && response.status !== 404) {
            throw new Error(data.error || `Status check failed (HTTP ${response.status})`);
        }
        if (data.status === 'error') {
            throw new Error(data.error || 'Extraction failed');
        }
        if (data.status === 'done' && data.success) {
            return data;
        }
    }
    throw new Error('Extraction timed out after 45 minutes. Try fewer sites or use a scheduled job.');
}

function showExtractResults(data) {
    const resultsSection = document.getElementById('results-section');
    lastFileId = data.file_id;
    const sheetNames = data.sheet_names || [];
    const sheetLabel = sheetNames.length
        ? `${sheetNames.length} sheet(s): ${sheetNames.join(', ')}`
        : '1 sheet';
    document.getElementById('results-message').textContent =
        `Ready — ${data.row_count} row(s) across ${sheetLabel}.`;
    const modeLabel = data.extraction_mode === 'bulk_operations'
        ? 'Method: CM Operations bulk export (Import_Export)'
        : (data.extraction_mode === 'selection'
            ? 'Method: CM Open API (persistency queries)'
            : '');
    document.getElementById('results-summary').textContent =
        [modeLabel, data.summary || ''].filter(Boolean).join(' — ');
    if (data.warnings?.length) {
        document.getElementById('results-summary').textContent +=
            ` Warnings: ${data.warnings.slice(0, 3).join('; ')}` +
            (data.warnings.length > 3 ? ` …and ${data.warnings.length - 3} more` : '');
    }
    finishExtractProgress(true);
    resultsSection.hidden = false;
    resultsSection.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    const notifyMsg = data.warnings?.length
        ? `Extraction complete with ${data.warnings.length} warning(s)`
        : (sheetNames.length > 1
            ? `Extraction complete — ${sheetNames.length} sheets`
            : 'Extraction complete');
        showNotification(notifyMsg, data.warnings?.length ? 'warning' : 'success');
    loadRecentExports();
}

async function loadRecentExports() {
    const container = document.getElementById('recent-exports');
    if (!container) return;
    try {
        const response = await fetch('/api/cm-extractor/exports?limit=10', { credentials: 'same-origin' });
        const data = await response.json();
        if (!data.success) {
            container.innerHTML = '<p class="field-hint">Could not load recent exports.</p>';
            return;
        }
        const items = data.exports || [];
        if (!items.length) {
            container.innerHTML = '<p class="field-hint">No saved exports yet.</p>';
            return;
        }
        container.innerHTML = items.map((item) => {
            const when = item.stored_at
                ? new Date(item.stored_at * 1000).toLocaleString()
                : '';
            const label = item.summary || item.filename || 'CM export';
            return `
                <div class="scheduler-job-card">
                    <div class="scheduler-job-title">${escapeHtml(label.slice(0, 80))}</div>
                    <div class="scheduler-job-meta">${escapeHtml(when)} · ${escapeHtml(item.row_count ?? '?')} rows</div>
                    <a class="link-btn" href="/api/cm-extractor/download/${encodeURIComponent(item.file_id)}">Download</a>
                </div>
            `;
        }).join('');
    } catch (_err) {
        container.innerHTML = '<p class="field-hint">Could not load recent exports.</p>';
    }
}

async function extract(vendor) {
    const resultsSection = document.getElementById('results-section');
    resultsSection.hidden = true;

    const payload = vendor === 'nokia' ? nokiaPayload() : buildHuaweiPayload();

    const largeFullMo = vendor === 'nokia' && buildNokiaSelections().some(
        (s) => s.export_mode === 'full',
    );
    const scopeLevel = vendor === 'nokia' ? getScopeLevel() : '';
    const rncBscOps = vendor === 'nokia'
        && (scopeLevel === 'RNC' || scopeLevel === 'BSC')
        && bulkExportSshConfigured;
    let hint = 'Querying the CM API and building your Excel workbook…';
    let progressLabel = 'Extracting CM data…';
    if (!isCmAdmin) {
        hint = '';
    } else if (rncBscOps) {
        progressLabel = 'Extracting RNC/BSC via CM Operations…';
        hint = (
            'Running NetAct Import_Export, then SFTP download and Excel conversion. '
            + 'This can take several minutes — keep this tab open.'
        );
    } else if (largeFullMo) {
        hint = 'Large full-MO exports can take several minutes. Please keep this tab open.';
    }
    startExtractProgress(hint, progressLabel);
    if (rncBscOps) {
        startControllerExtractPhaseTimer();
    }
    showNotification('Extracting CM data…', 'info');
    try {
        const response = await fetch('/api/cm-extractor/extract', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify(payload),
        });
        let data = {};
        try {
            data = await response.json();
        } catch (_) {
            data = {};
        }
        if (response.status === 401) {
            finishExtractProgress(false);
            showNotification('PrimeNet session expired — refresh the page and sign in again.', 'error');
            return;
        }
        if (!response.ok) {
            finishExtractProgress(false);
            const payloadMsg = data.error || '';
            const hint = response.status === 413
                ? 'Request too large — try fewer sites, fewer parameters per MO, or use Full MO export.'
                : (response.status === 400 && /too many items/i.test(payloadMsg)
                    ? 'Too many sites or parameters in one request — try fewer sites or Full MO export.'
                    : '');
            showNotification(payloadMsg || hint || `Extraction failed (HTTP ${response.status})`, 'error');
            return;
        }
        if (!data.success) {
            finishExtractProgress(false);
            showNotification(data.error || 'Extraction failed', 'error');
            return;
        }
        if (data.async) {
            const finalData = await pollExtractStatus(data.file_id);
            showExtractResults(finalData);
            return;
        }
        showExtractResults(data);
    } catch (error) {
        finishExtractProgress(false);
        showNotification(error.message || 'Extraction failed', 'error');
    } finally {
        stopControllerExtractPhaseTimer();
    }
}

function downloadFile() {
    if (!lastFileId) return;
    window.location.href = `/api/cm-extractor/download/${lastFileId}`;
}

// ---------------------------------------------------------------------------
// Scheduled jobs (sidebar + modal)
// ---------------------------------------------------------------------------

const SCHED_KEEP_RUNS = 5;
let schedJobsCache = { jobs: [], isAdmin: false };
const schedCurrentUsername = (document.body.dataset.username || '').trim();
const schedCurrentRole = (document.body.dataset.userRole || '').trim().toLowerCase();
const schedIsAdmin = schedCurrentRole === 'admin';

function schedSlugUsername(username) {
    return (username || 'unknown').replace(/[^A-Za-z0-9._-]+/g, '_').slice(0, 64) || 'unknown';
}

function schedNormalizeSubpath(raw) {
    if (!raw || !String(raw).trim()) return '';
    return String(raw).replace(/\\/g, '/').split('/')
        .map((seg) => seg.trim())
        .filter((seg) => seg && seg !== '.' && seg !== '..')
        .map((seg) => seg.replace(/[^A-Za-z0-9._-]+/g, '_').slice(0, 64))
        .filter(Boolean)
        .join('/');
}

function schedStoragePreviewPath() {
    const user = schedSlugUsername(schedCurrentUsername);
    const sub = schedNormalizeSubpath(document.getElementById('sched-storage-subpath')?.value || '');
    return sub
        ? `cm_extractor/scheduled_job/${user}/${sub}`
        : `cm_extractor/scheduled_job/${user}`;
}

function updateSchedStoragePreview() {
    const el = document.getElementById('sched-storage-preview');
    if (el) el.textContent = schedStoragePreviewPath();
}

const schedState = {
    vendor: 'nokia',
    siteCatalog: [],
    selectedSiteIds: new Set(),
    selectedMoClasses: new Map(),
    selectedParamsByClass: new Map(),
    fullMoByClass: new Set(),
    selectedHuaweiMoObjects: new Map(),
    selectedHuaweiParamsByMo: new Map(),
    fullMoByHuaweiObject: new Set(),
    paramsCache: new Map(),
    huaweiMoCatalog: [],
};

function getSchedNokiaScope() {
    return document.querySelector('input[name="sched-nokia-scope"]:checked')?.value || 'MRBTS';
}

function getSchedHuaweiScope() {
    return document.querySelector('input[name="sched-huawei-scope"]:checked')?.value || 'ENODEB';
}

function setupScheduler() {
    const modal = document.getElementById('schedule-modal');
    if (!modal) return;

    document.getElementById('scheduler-new-btn').addEventListener('click', openScheduleModal);
    document.getElementById('scheduler-refresh-btn').addEventListener('click', loadScheduledJobs);
    document.getElementById('recent-exports-refresh-btn')?.addEventListener('click', loadRecentExports);
    document.getElementById('schedule-modal-close').addEventListener('click', closeScheduleModal);
    document.getElementById('schedule-modal-cancel').addEventListener('click', closeScheduleModal);
    document.getElementById('sched-job-create-btn').addEventListener('click', createScheduledJob);
    document.getElementById('sched-job-schedule-type').addEventListener('change', onSchedScheduleTypeChange);

    modal.addEventListener('click', (e) => {
        if (e.target === modal) closeScheduleModal();
    });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !modal.hidden) closeScheduleModal();
    });

    document.querySelectorAll('input[name="sched-nokia-scope"]').forEach((radio) => {
        radio.addEventListener('change', () => {
            schedState.selectedSiteIds.clear();
            schedLoadSites();
        });
    });
    document.querySelectorAll('input[name="sched-huawei-scope"]').forEach((radio) => {
        radio.addEventListener('change', async () => {
            schedState.selectedSiteIds.clear();
            schedState.selectedHuaweiMoObjects.clear();
            schedState.selectedHuaweiParamsByMo.clear();
            schedState.fullMoByHuaweiObject.clear();
            schedState.paramsCache.clear();
            await schedLoadSites();
            await schedEnsureMoCatalog();
            schedRenderMoList();
            await schedRefreshParamPanels();
        });
    });

    document.getElementById('sched-site-search').addEventListener('input', schedRenderSiteList);
    document.getElementById('sched-site-select-all').addEventListener('click', schedSelectAllSites);
    document.getElementById('sched-site-select-visible').addEventListener('click', schedSelectVisibleSites);
    document.getElementById('sched-site-clear').addEventListener('click', schedClearSites);
    document.getElementById('sched-site-apply-paste').addEventListener('click', schedApplyPastedSites);
    document.getElementById('sched-mo-search').addEventListener('input', schedRenderMoList);
    document.getElementById('sched-mo-select-all').addEventListener('click', () => { schedSelectAllMo(); });
    document.getElementById('sched-mo-select-visible').addEventListener('click', () => { schedSelectVisibleMo(); });
    document.getElementById('sched-mo-clear').addEventListener('click', schedClearMo);
    document.getElementById('sched-param-search').addEventListener('input', schedFilterParams);
    document.getElementById('sched-storage-subpath')?.addEventListener('input', updateSchedStoragePreview);

    const userSpecific = document.getElementById('sched-user-specific');
    if (userSpecific && !schedIsAdmin) {
        userSpecific.checked = true;
        userSpecific.disabled = true;
    }

    onSchedScheduleTypeChange();
    updateSchedStoragePreview();
    loadScheduledJobs();
    loadRecentExports();
    startJobNotificationPolling();
}

let lastJobNotifId = 0;
let jobNotifPollTimer = null;

function updateSchedulerNotifBadge(count) {
    const badge = document.getElementById('scheduler-notif-badge');
    if (!badge) return;
    const n = Number(count) || 0;
    if (n > 0) {
        badge.textContent = n > 99 ? '99+' : String(n);
        badge.hidden = false;
        badge.classList.add('visible');
    } else {
        badge.textContent = '';
        badge.hidden = true;
        badge.classList.remove('visible');
    }
}

async function pollJobNotifications() {
    try {
        const res = await fetch(`/api/cm-extractor/notifications?since_id=${lastJobNotifId}`, {
            credentials: 'same-origin',
            cache: 'no-store',
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data.success) return;

        updateSchedulerNotifBadge(data.unread_count);

        const items = data.notifications || [];
        if (!items.length) return;

        const ids = [];
        for (const n of items) {
            lastJobNotifId = Math.max(lastJobNotifId, Number(n.id) || 0);
            ids.push(n.id);
            const label = n.job_name || 'Scheduled job';
            const msg = n.message || (n.status === 'ok' ? 'Completed successfully.' : 'Run failed.');
            const type = n.status === 'ok' ? 'success' : 'error';
            if (typeof showNotification === 'function') {
                showNotification(`${label}: ${msg}`, type);
            }
        }

        if (ids.length) {
            await fetch('/api/cm-extractor/notifications/seen', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({ ids }),
            });
            updateSchedulerNotifBadge(0);
        }

        loadScheduledJobs();
    } catch (_) {
        // polling is best-effort
    }
}

function startJobNotificationPolling() {
    if (jobNotifPollTimer) return;
    pollJobNotifications();
    jobNotifPollTimer = window.setInterval(pollJobNotifications, 60000);
}

function onSchedScheduleTypeChange() {
    const type = document.getElementById('sched-job-schedule-type').value;
    document.querySelectorAll('#schedule-modal .sched-field').forEach((el) => {
        const applies = (el.dataset.for || '').split(/\s+/).includes(type);
        el.hidden = !applies;
    });
}

function seedSchedStateFromMain() {
    schedState.selectedSiteIds.clear();
    schedState.selectedMoClasses.clear();
    schedState.selectedParamsByClass.clear();
    schedState.fullMoByClass.clear();
    schedState.selectedHuaweiMoObjects.clear();
    schedState.selectedHuaweiParamsByMo.clear();
    schedState.fullMoByHuaweiObject.clear();
    schedState.paramsCache.clear();

    schedState.vendor = activeVendor;

    if (activeVendor === 'huawei') {
        selectedHuaweiSiteIds.forEach((id) => schedState.selectedSiteIds.add(id));
        selectedHuaweiMoObjects.forEach((mo, id) => schedState.selectedHuaweiMoObjects.set(id, { ...mo }));
        selectedHuaweiParamsByMo.forEach((set, id) => {
            schedState.selectedHuaweiParamsByMo.set(id, new Set(set));
        });
        fullMoByHuaweiObject.forEach((id) => schedState.fullMoByHuaweiObject.add(id));
        const scope = getHuaweiScopeLevel();
        const radio = document.querySelector(`input[name="sched-huawei-scope"][value="${scope}"]`);
        if (radio) radio.checked = true;
    } else {
        selectedSiteIds.forEach((id) => schedState.selectedSiteIds.add(id));
        selectedMoClasses.forEach((mo, id) => schedState.selectedMoClasses.set(id, { ...mo }));
        selectedParamsByClass.forEach((set, id) => {
            schedState.selectedParamsByClass.set(id, new Set(set));
        });
        fullMoByClass.forEach((id) => schedState.fullMoByClass.add(id));
        const scope = getScopeLevel();
        const radio = document.querySelector(`input[name="sched-nokia-scope"][value="${scope}"]`);
        if (radio) radio.checked = true;
        const confSel = document.getElementById('sched-nokia-conf-id');
        if (confSel) confSel.value = document.getElementById('nokia-conf-id')?.value || '1';
    }
}

async function openScheduleModal() {
    seedSchedStateFromMain();
    const isHuawei = schedState.vendor === 'huawei';
    document.getElementById('sched-vendor-label').textContent = isHuawei ? 'Huawei' : 'Nokia';
    document.getElementById('sched-owner-label').textContent = schedCurrentUsername || '—';
    const userSpecific = document.getElementById('sched-user-specific');
    if (userSpecific) {
        userSpecific.checked = true;
        if (!schedIsAdmin) userSpecific.disabled = true;
        else userSpecific.disabled = false;
    }
    document.getElementById('sched-storage-subpath').value = '';
    updateSchedStoragePreview();
    document.getElementById('sched-nokia-scope').hidden = isHuawei;
    const huaweiScopeEl = document.getElementById('sched-huawei-scope');
    if (huaweiScopeEl) huaweiScopeEl.hidden = !isHuawei;
    document.getElementById('sched-form-hint').hidden = true;
    document.getElementById('sched-form-hint').textContent = '';
    document.getElementById('sched-site-paste').value = '';
    document.getElementById('sched-site-status').hidden = true;

    onSchedScheduleTypeChange();
    document.getElementById('schedule-modal').hidden = false;
    document.body.style.overflow = 'hidden';

    await schedLoadSites();
    await schedEnsureMoCatalog();
    schedRenderMoList();
    await schedRefreshParamPanels();
}

function closeScheduleModal() {
    const modal = document.getElementById('schedule-modal');
    if (!modal || modal.hidden) return;
    modal.hidden = true;
    document.body.style.overflow = '';
}

async function schedLoadSites() {
    const loading = document.getElementById('sched-site-loading');
    const listEl = document.getElementById('sched-site-list');
    const isHuawei = schedState.vendor === 'huawei';
    loading.hidden = false;
    listEl.innerHTML = '';

    try {
        const scope = encodeURIComponent(isHuawei ? getSchedHuaweiScope() : getSchedNokiaScope());
        const url = isHuawei
            ? `/api/cm-extractor/huawei/sites?scope=${scope}&limit=3000`
            : `/api/cm-extractor/nokia/sites?scope=${scope}&limit=3000`;
        const response = await fetch(url, { credentials: 'same-origin' });
        const data = await response.json();
        if (!response.ok || !data.success) {
            throw new Error(data.error || 'Failed to load sites');
        }
        schedState.siteCatalog = data.sites || [];
    } catch (error) {
        schedState.siteCatalog = isHuawei ? [...huaweiNeCatalog] : [...nokiaSiteCatalog];
        if (!schedState.siteCatalog.length) {
            listEl.innerHTML = `<p class="field-hint">${escapeHtml(error.message || 'No sites loaded.')}</p>`;
            loading.hidden = true;
            schedUpdateSiteHint();
            return;
        }
    } finally {
        loading.hidden = true;
    }
    schedRenderSiteList();
}

function schedFilteredSites() {
    const query = (document.getElementById('sched-site-search')?.value || '').trim().toLowerCase();
    return schedState.siteCatalog.filter((site) => {
        if (!query) return true;
        const hay = `${site.site_id} ${site.metadata_site_id || ''} ${site.site_name || ''} ${site.label || ''} ${site.area || ''}`.toLowerCase();
        return hay.includes(query);
    });
}

function schedRenderSiteList() {
    const listEl = document.getElementById('sched-site-list');
    const filtered = schedFilteredSites();
    const fragment = document.createDocumentFragment();

    filtered.forEach((site) => {
        const label = document.createElement('label');
        label.className = 'mo-class-item site-item';
        const cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.checked = schedState.selectedSiteIds.has(site.site_id);
        cb.addEventListener('change', () => {
            if (cb.checked) schedState.selectedSiteIds.add(site.site_id);
            else schedState.selectedSiteIds.delete(site.site_id);
            schedUpdateSiteHint();
        });
        label.appendChild(cb);
        const display = schedSiteDisplay(site);
        const text = document.createElement('span');
        text.textContent = display.title;
        label.appendChild(text);
        if (display.meta) {
            const meta = document.createElement('span');
            meta.className = 'mo-class-meta';
            meta.textContent = display.meta;
            label.appendChild(meta);
        }
        fragment.appendChild(label);
    });

    listEl.innerHTML = '';
    if (!filtered.length) {
        listEl.innerHTML = '<p class="loading-hint">No sites match your search.</p>';
    } else {
        listEl.appendChild(fragment);
    }
    schedUpdateSiteHint();
}

function schedUpdateSiteHint() {
    const hint = document.getElementById('sched-site-hint');
    if (hint) hint.textContent = `${schedState.selectedSiteIds.size} object(s) selected`;
}

function schedApplyPastedSites() {
    const ids = parsePastedSiteIds(document.getElementById('sched-site-paste').value);
    const statusEl = document.getElementById('sched-site-status');
    if (!ids.length) {
        statusEl.hidden = false;
        statusEl.textContent = 'No IDs found in pasted text.';
        return;
    }
    ids.forEach((id) => {
        const resolvedId = schedState.vendor === 'huawei' ? id : resolveNokiaCatalogSiteId(id);
        schedState.selectedSiteIds.add(resolvedId);
    });
    schedRenderSiteList();
    statusEl.hidden = false;
    statusEl.textContent = `Added ${ids.length} id(s).`;
}

function schedSelectAllSites() {
    schedState.siteCatalog.forEach((site) => schedState.selectedSiteIds.add(site.site_id));
    schedRenderSiteList();
}

function schedSelectVisibleSites() {
    schedFilteredSites().forEach((site) => schedState.selectedSiteIds.add(site.site_id));
    schedRenderSiteList();
}

function schedClearSites() {
    schedState.selectedSiteIds.clear();
    schedRenderSiteList();
}

function schedFilteredMoClasses() {
    const query = (document.getElementById('sched-mo-search')?.value || '').trim().toLowerCase();
    const catalog = schedState.vendor === 'huawei'
        ? (schedState.huaweiMoCatalog.length ? schedState.huaweiMoCatalog : huaweiMoCatalog)
        : moClassCatalog;
    return catalog.filter((mo) => {
        if (!query) return true;
        const hay = schedState.vendor === 'huawei'
            ? `${mo.label} ${mo.id} ${mo.command}`.toLowerCase()
            : `${mo.label} ${mo.group} ${mo.id}`.toLowerCase();
        return hay.includes(query);
    });
}

async function schedAddMoSelections(mos) {
    if (schedState.vendor === 'huawei') {
        mos.forEach((mo) => {
            schedState.selectedHuaweiMoObjects.set(mo.id, mo);
            if (!schedState.selectedHuaweiParamsByMo.has(mo.id)) {
                schedState.selectedHuaweiParamsByMo.set(mo.id, new Set());
            }
        });
    } else {
        mos.forEach((mo) => {
            schedState.selectedMoClasses.set(mo.id, mo);
            if (!schedState.selectedParamsByClass.has(mo.id)) {
                schedState.selectedParamsByClass.set(mo.id, new Set());
            }
        });
    }
    schedRenderMoList();
    await schedRefreshParamPanels();
}

async function schedSelectAllMo() {
    const catalog = schedState.vendor === 'huawei'
        ? (schedState.huaweiMoCatalog.length ? schedState.huaweiMoCatalog : huaweiMoCatalog)
        : moClassCatalog;
    await schedAddMoSelections(catalog);
}

async function schedSelectVisibleMo() {
    await schedAddMoSelections(schedFilteredMoClasses());
}

function schedClearMo() {
    if (schedState.vendor === 'huawei') {
        schedState.selectedHuaweiMoObjects.clear();
        schedState.selectedHuaweiParamsByMo.clear();
        schedState.fullMoByHuaweiObject.clear();
    } else {
        schedState.selectedMoClasses.clear();
        schedState.selectedParamsByClass.clear();
        schedState.fullMoByClass.clear();
    }
    schedState.paramsCache.clear();
    schedRenderMoList();
    schedRefreshParamPanels();
}

async function schedEnsureMoCatalog() {
    const loading = document.getElementById('sched-mo-loading');
    loading.hidden = false;
    try {
        if (schedState.vendor === 'huawei') {
            const scope = encodeURIComponent(getSchedHuaweiScope());
            const response = await fetch(`/api/cm-extractor/huawei/mo-objects?scope=${scope}`, { credentials: 'same-origin' });
            const data = await response.json();
            if (response.ok && data.success) {
                schedState.huaweiMoCatalog = data.mo_objects || [];
            }
        } else if (!moClassCatalog.length) {
            await loadMoClasses();
        }
    } finally {
        loading.hidden = true;
    }
}

function schedRenderMoList() {
    const listEl = document.getElementById('sched-mo-list');
    const filtered = schedFilteredMoClasses();

    if (schedState.vendor === 'huawei') {
        listEl.innerHTML = filtered.map((mo) => {
            const checked = schedState.selectedHuaweiMoObjects.has(mo.id) ? 'checked' : '';
            const display = huaweiMoDisplay(mo);
            const metaHtml = display.meta
                ? `<span class="mo-class-meta">${escapeHtml(display.meta)}</span>`
                : '';
            return `
                <label class="mo-class-item">
                    <input type="checkbox" data-sched-mo-id="${escapeHtml(mo.id)}" ${checked}>
                    <span>${escapeHtml(display.title)}</span>
                    ${metaHtml}
                </label>`;
        }).join('') || '<p class="loading-hint">No MO types match your search.</p>';

        listEl.querySelectorAll('input[type="checkbox"]').forEach((input) => {
            input.addEventListener('change', async () => {
                const moId = input.dataset.schedMoId;
                if (input.checked) {
                    const mo = (schedState.huaweiMoCatalog.find((item) => item.id === moId)
                        || huaweiMoCatalog.find((item) => item.id === moId));
                    if (mo) schedState.selectedHuaweiMoObjects.set(moId, mo);
                } else {
                    schedState.selectedHuaweiMoObjects.delete(moId);
                    schedState.selectedHuaweiParamsByMo.delete(moId);
                    schedState.fullMoByHuaweiObject.delete(moId);
                    schedState.paramsCache.delete(moId);
                }
                await schedRefreshParamPanels();
            });
        });
        return;
    }

    const fragment = document.createDocumentFragment();
    filtered.forEach((mo) => {
        const label = document.createElement('label');
        label.className = 'mo-class-item';
        const cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.checked = schedState.selectedMoClasses.has(mo.id);
        cb.addEventListener('change', async () => {
            if (cb.checked) {
                schedState.selectedMoClasses.set(mo.id, mo);
                if (!schedState.selectedParamsByClass.has(mo.id)) {
                    schedState.selectedParamsByClass.set(mo.id, new Set());
                }
            } else {
                schedState.selectedMoClasses.delete(mo.id);
                schedState.selectedParamsByClass.delete(mo.id);
                schedState.fullMoByClass.delete(mo.id);
                schedState.paramsCache.delete(mo.id);
            }
            await schedRefreshParamPanels();
        });
        label.appendChild(cb);
        label.appendChild(document.createTextNode(mo.label));
        fragment.appendChild(label);
    });
    listEl.innerHTML = '';
    listEl.appendChild(fragment);
    if (!filtered.length) {
        listEl.innerHTML = '<p class="loading-hint">No MO classes match your search.</p>';
    }
}

async function schedRefreshParamPanels() {
    const section = document.getElementById('sched-param-section');
    const groupsEl = document.getElementById('sched-param-groups');
    const loading = document.getElementById('sched-param-loading');

    if (schedState.vendor === 'huawei') {
        if (!schedState.selectedHuaweiMoObjects.size) {
            section.hidden = true;
            groupsEl.innerHTML = '';
            return;
        }
        section.hidden = false;
        const needFetch = [...schedState.selectedHuaweiMoObjects.keys()].filter((id) => !schedState.paramsCache.has(id));
        if (needFetch.length) {
            loading.hidden = false;
            try {
                const response = await fetch('/api/cm-extractor/huawei/parameters', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ mo_ids: needFetch }),
                });
                const data = await response.json();
                if (data.success) {
                    Object.entries(data.parameters || {}).forEach(([id, params]) => {
                        schedState.paramsCache.set(id, params);
                    });
                }
            } finally {
                loading.hidden = true;
            }
        }
        groupsEl.innerHTML = '';
        [...schedState.selectedHuaweiMoObjects.entries()].forEach(([moId, mo]) => {
            const params = schedState.paramsCache.get(moId) || [];
            const isFull = schedState.fullMoByHuaweiObject.has(moId);
            const selected = schedState.selectedHuaweiParamsByMo.get(moId) || new Set();
            const block = document.createElement('div');
            block.className = 'param-mo-group';
            block.innerHTML = `<div class="param-mo-head"><strong>${escapeHtml(mo.label)}</strong></div>`;
            const grid = document.createElement('div');
            grid.className = 'param-checkboxes';
            if (isFull) {
                grid.innerHTML = '<p class="loading-hint">Full MML report — all columns.</p>';
            } else {
                params.forEach((param) => {
                    const pl = document.createElement('label');
                    pl.className = 'param-check';
                    pl.dataset.paramId = param.id;
                    const cb = document.createElement('input');
                    cb.type = 'checkbox';
                    cb.checked = selected.has(param.id);
                    cb.addEventListener('change', () => {
                        const set = schedState.selectedHuaweiParamsByMo.get(moId) || new Set();
                        if (cb.checked) set.add(param.id);
                        else set.delete(param.id);
                        schedState.selectedHuaweiParamsByMo.set(moId, set);
                    });
                    pl.appendChild(cb);
                    pl.appendChild(document.createTextNode(param.id));
                    grid.appendChild(pl);
                });
            }
            const fullBtn = document.createElement('button');
            fullBtn.type = 'button';
            fullBtn.className = 'link-btn';
            fullBtn.textContent = isFull ? 'Use selected parameters' : 'Full MML report';
            fullBtn.addEventListener('click', () => {
                if (schedState.fullMoByHuaweiObject.has(moId)) {
                    schedState.fullMoByHuaweiObject.delete(moId);
                } else {
                    schedState.fullMoByHuaweiObject.add(moId);
                    schedState.selectedHuaweiParamsByMo.set(moId, new Set());
                }
                schedRefreshParamPanels();
            });
            block.querySelector('.param-mo-head').appendChild(fullBtn);
            block.appendChild(grid);
            groupsEl.appendChild(block);
        });
        schedFilterParams();
        return;
    }

    if (!schedState.selectedMoClasses.size) {
        section.hidden = true;
        groupsEl.innerHTML = '';
        return;
    }
    section.hidden = false;
    const needFetch = [...schedState.selectedMoClasses.keys()].filter((id) => !schedState.paramsCache.has(id));
    if (needFetch.length) {
        loading.hidden = false;
        try {
            const response = await fetch('/api/cm-extractor/nokia/parameters', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    mo_classes: needFetch.map((id) => {
                        const mo = schedState.selectedMoClasses.get(id);
                        return { mo_class_id: id, id, version: mo.version };
                    }),
                }),
            });
            const data = await response.json();
            if (data.success) {
                Object.entries(data.parameters || {}).forEach(([classId, params]) => {
                    schedState.paramsCache.set(classId, params);
                });
            }
        } finally {
            loading.hidden = true;
        }
    }

    groupsEl.innerHTML = '';
    [...schedState.selectedMoClasses.values()].forEach((mo) => {
        const params = schedState.paramsCache.get(mo.id) || [];
        const isFullMo = schedState.fullMoByClass.has(mo.id);
        const selected = schedState.selectedParamsByClass.get(mo.id) || new Set();
        const group = document.createElement('div');
        group.className = 'param-mo-group';
        const head = document.createElement('div');
        head.className = 'param-mo-head';
        head.innerHTML = `<strong>${escapeHtml(mo.abbreviation || mo.label)}</strong>`;
        const fullBtn = document.createElement('button');
        fullBtn.type = 'button';
        fullBtn.className = 'link-btn';
        fullBtn.textContent = isFullMo ? 'Full MO selected' : 'Full MO export';
        fullBtn.addEventListener('click', () => {
            if (schedState.fullMoByClass.has(mo.id)) schedState.fullMoByClass.delete(mo.id);
            else {
                schedState.fullMoByClass.add(mo.id);
                schedState.selectedParamsByClass.set(mo.id, new Set());
            }
            schedRefreshParamPanels();
        });
        head.appendChild(fullBtn);
        group.appendChild(head);

        const grid = document.createElement('div');
        grid.className = 'param-checkboxes';
        if (isFullMo) {
            grid.innerHTML = '<p class="loading-hint">Full MO export — all parameters.</p>';
        } else {
            params.forEach((param) => {
                const pl = document.createElement('label');
                pl.className = 'param-check';
                pl.dataset.paramId = param.id;
                const cb = document.createElement('input');
                cb.type = 'checkbox';
                cb.checked = selected.has(param.id);
                cb.disabled = param.queryable === false;
                cb.addEventListener('change', () => {
                    const set = schedState.selectedParamsByClass.get(mo.id) || new Set();
                    if (cb.checked) set.add(param.id);
                    else set.delete(param.id);
                    schedState.selectedParamsByClass.set(mo.id, set);
                });
                pl.appendChild(cb);
                pl.appendChild(document.createTextNode(param.id));
                grid.appendChild(pl);
            });
        }
        group.appendChild(grid);
        groupsEl.appendChild(group);
    });
    schedFilterParams();
}

function schedFilterParams() {
    const query = (document.getElementById('sched-param-search')?.value || '').trim().toLowerCase();
    document.querySelectorAll('#sched-param-groups .param-check').forEach((label) => {
        const paramId = (label.dataset.paramId || '').toLowerCase();
        label.hidden = Boolean(query && !paramId.includes(query));
    });
}

function schedBuildNokiaSelections() {
    return [...schedState.selectedMoClasses.entries()].map(([moId, mo]) => {
        const isFullMo = schedState.fullMoByClass.has(moId);
        const params = isFullMo ? [] : [...(schedState.selectedParamsByClass.get(moId) || [])];
        return {
            mo_class_id: moId,
            version: mo.version,
            parameters: params,
            export_mode: isFullMo ? 'full' : 'selected',
        };
    });
}

function schedBuildHuaweiSelections() {
    return [...schedState.selectedHuaweiMoObjects.keys()].map((moId) => {
        const exportAll = schedState.fullMoByHuaweiObject.has(moId);
        const params = exportAll ? [] : [...(schedState.selectedHuaweiParamsByMo.get(moId) || [])];
        return {
            mo_id: moId,
            export_all: exportAll,
            parameters: params,
        };
    });
}

function schedBuildPayload() {
    if (schedState.vendor === 'huawei') {
        const siteIds = [...schedState.selectedSiteIds];
        const neNames = siteIds.map((siteId) => {
            const site = schedState.siteCatalog.find((row) => row.site_id === siteId)
                || huaweiNeCatalog.find((row) => row.site_id === siteId);
            return catalogNeNameForSite(site);
        }).filter(Boolean);
        return {
            vendor: 'huawei',
            scope_level: getSchedHuaweiScope(),
            site_ids: siteIds,
            ne_names: neNames.length === siteIds.length ? neNames : [],
            selections: schedBuildHuaweiSelections(),
        };
    }
    return {
        vendor: 'nokia',
        scope_level: getSchedNokiaScope(),
        conf_id: parseInt(document.getElementById('sched-nokia-conf-id')?.value || '1', 10),
        site_ids: [...schedState.selectedSiteIds],
        selections: schedBuildNokiaSelections(),
    };
}

function schedSelectionValid(payload) {
    if (!payload.site_ids?.length) return 'Select at least one object.';
    if (!payload.selections?.length) return 'Select at least one managed object.';
    const bad = payload.selections.find((s) => {
        if (s.export_mode === 'full' || s.export_all) return false;
        return !(s.parameters || []).length;
    });
    if (bad) return 'Each MO needs at least one parameter, or use full MO export.';
    return '';
}

async function createScheduledJob() {
    const hint = document.getElementById('sched-form-hint');
    hint.hidden = true;
    hint.textContent = '';

    const payload = schedBuildPayload();
    const validErr = schedSelectionValid(payload);
    if (validErr) {
        hint.hidden = false;
        hint.textContent = validErr;
        return;
    }

    const scheduleType = document.getElementById('sched-job-schedule-type').value;
    const body = {
        name: document.getElementById('sched-job-name').value.trim(),
        vendor: payload.vendor,
        payload,
        schedule_type: scheduleType,
        keep_runs: SCHED_KEEP_RUNS,
        user_specific: document.getElementById('sched-user-specific')?.checked !== false,
        storage_subpath: schedNormalizeSubpath(document.getElementById('sched-storage-subpath')?.value || ''),
    };
    if (scheduleType === 'daily' || scheduleType === 'weekly') {
        body.schedule_time = document.getElementById('sched-job-time').value || '02:00';
    }
    if (scheduleType === 'weekly') {
        const days = [...document.querySelectorAll('#sched-job-days input:checked')].map((c) => c.value);
        if (!days.length) {
            hint.hidden = false;
            hint.textContent = 'Pick at least one weekday.';
            return;
        }
        body.schedule_days = days.join(',');
    }
    if (scheduleType === 'interval') {
        body.interval_hours = parseInt(document.getElementById('sched-job-interval').value, 10) || 6;
    }
    if (scheduleType === 'once') {
        const runAt = document.getElementById('sched-job-runat').value;
        if (!runAt) {
            hint.hidden = false;
            hint.textContent = 'Pick a date/time for the one-time job.';
            return;
        }
        body.run_at = runAt;
    }

    try {
        const response = await fetch('/api/cm-extractor/jobs', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const data = await response.json();
        if (!data.success) {
            hint.hidden = false;
            hint.textContent = data.error || 'Could not create job.';
            return;
        }
        document.getElementById('sched-job-name').value = '';
        showNotification('Scheduled job created', 'success');
        closeScheduleModal();
        loadScheduledJobs();
    } catch (error) {
        hint.hidden = false;
        hint.textContent = 'Could not create job.';
    }
}

async function loadScheduledJobs() {
    const wrap = document.getElementById('scheduler-jobs');
    if (!wrap) return;
    try {
        const response = await fetch('/api/cm-extractor/jobs', { credentials: 'same-origin' });
        const data = await response.json();
        if (!data.success) {
            wrap.innerHTML = `<p class="field-hint">${escapeHtml(data.error || 'Could not load jobs.')}</p>`;
            return;
        }
        schedJobsCache = { jobs: data.jobs || [], isAdmin: Boolean(data.is_admin) };
        renderScheduledJobs(schedJobsCache.jobs, schedJobsCache.isAdmin);
    } catch (error) {
        wrap.innerHTML = '<p class="field-hint">Could not load jobs.</p>';
    }
}

function statusBadge(status) {
    const s = (status || '').toLowerCase();
    const cls = s === 'ok' ? 'badge-ok' : (s === 'error' ? 'badge-err' : (s === 'running' ? 'badge-run' : 'badge-idle'));
    return `<span class="job-badge ${cls}">${escapeHtml(status || 'never run')}</span>`;
}

function renderScheduledJobs(jobs, isAdmin) {
    const wrap = document.getElementById('scheduler-jobs');
    const filtered = jobs.filter((job) => (job.vendor || '').toLowerCase() === activeVendor);
    if (!filtered.length) {
        wrap.innerHTML = `<p class="field-hint">No ${escapeHtml(activeVendor)} scheduled jobs yet.</p>`;
        return;
    }
    wrap.innerHTML = '';
    filtered.forEach((job) => {
        const card = document.createElement('div');
        card.className = 'job-card' + (job.enabled ? '' : ' job-disabled');
        const ownerName = job.owner_username || job.creator_username || '';
        const ownerLine = isAdmin && ownerName
            ? `<span class="job-owner" title="Job owner">@${escapeHtml(ownerName)}</span>`
            : '';
        const privateBadge = job.user_specific === false
            ? '<span class="job-badge badge-idle">shared</span>'
            : '';
        const storageLine = job.storage_label
            ? `<div class="job-meta job-storage" title="Output directory">${escapeHtml(job.storage_label)}</div>`
            : '';
        card.innerHTML = `
            <div class="job-main">
                <div class="job-title">
                    <strong>${escapeHtml(job.name)}</strong>
                    <span class="job-vendor">${escapeHtml(job.vendor)}</span>
                    ${ownerLine}
                    ${privateBadge}
                    ${statusBadge(job.last_status)}
                </div>
                <div class="job-meta">
                    ${escapeHtml(job.schedule_label || '')}
                    · ${job.site_count} site(s) · ${job.mo_count} MO(s)
                    ${job.scope_level ? '· ' + escapeHtml(job.scope_level) : ''}
                </div>
                ${storageLine}
                <div class="job-meta job-sub">
                    Next: ${escapeHtml(job.next_run_at || (job.enabled ? '—' : 'disabled'))}
                    ${job.last_run_at ? '· Last: ' + escapeHtml(job.last_run_at) : ''}
                    ${job.last_message ? '· ' + escapeHtml(job.last_message.slice(0, 120)) : ''}
                </div>
            </div>
            <div class="job-actions">
                <button type="button" class="btn-ghost" data-act="run">Run now</button>
                <button type="button" class="btn-ghost" data-act="toggle">${job.enabled ? 'Disable' : 'Enable'}</button>
                <button type="button" class="btn-ghost" data-act="runs">History</button>
                <button type="button" class="btn-ghost btn-danger" data-act="delete">Delete</button>
            </div>
            <div class="job-runs" hidden></div>
        `;
        card.querySelector('[data-act="run"]').addEventListener('click', () => runJobNow(job.id));
        card.querySelector('[data-act="toggle"]').addEventListener('click', () => toggleJob(job.id, !job.enabled));
        card.querySelector('[data-act="delete"]').addEventListener('click', () => deleteJob(job.id, job.name));
        const runsBox = card.querySelector('.job-runs');
        card.querySelector('[data-act="runs"]').addEventListener('click', () => {
            if (runsBox.hidden) {
                loadJobRuns(job.id, runsBox);
                runsBox.hidden = false;
            } else {
                runsBox.hidden = true;
            }
        });
        wrap.appendChild(card);
    });
}

async function runJobNow(jobId) {
    try {
        const response = await fetch(`/api/cm-extractor/jobs/${jobId}/run-now`, { method: 'POST' });
        const data = await response.json();
        showNotification(data.success ? 'Run started' : (data.error || 'Could not start run'),
            data.success ? 'info' : 'error');
        setTimeout(loadScheduledJobs, 2500);
    } catch (error) {
        showNotification('Could not start run', 'error');
    }
}

async function toggleJob(jobId, enabled) {
    try {
        await fetch(`/api/cm-extractor/jobs/${jobId}/toggle`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled }),
        });
        loadScheduledJobs();
    } catch (error) {
        showNotification('Could not update job', 'error');
    }
}

async function deleteJob(jobId, name) {
    if (!window.confirm(`Delete scheduled job "${name}"? Its run history and files will be removed.`)) return;
    try {
        await fetch(`/api/cm-extractor/jobs/${jobId}`, { method: 'DELETE' });
        showNotification('Job deleted', 'success');
        loadScheduledJobs();
    } catch (error) {
        showNotification('Could not delete job', 'error');
    }
}

async function loadJobRuns(jobId, box) {
    box.innerHTML = '<p class="field-hint">Loading runs…</p>';
    try {
        const response = await fetch(`/api/cm-extractor/jobs/${jobId}/runs`, { credentials: 'same-origin' });
        const data = await response.json();
        if (!data.success || !(data.runs || []).length) {
            box.innerHTML = '<p class="field-hint">No runs yet.</p>';
            return;
        }
        const rows = data.runs.map((run) => {
            const dl = run.has_file
                ? `<a href="/api/cm-extractor/jobs/runs/${run.id}/download">Download</a>`
                : '<span class="muted">—</span>';
            const by = run.run_by_username || run.trigger || '';
            return `
                <tr>
                    <td>${escapeHtml(run.started_at || '')}</td>
                    <td>${statusBadge(run.status)}</td>
                    <td title="${escapeHtml(run.message || '')}">${escapeHtml(by)}</td>
                    <td>${run.row_count || 0}</td>
                    <td>${dl}</td>
                </tr>`;
        }).join('');
        box.innerHTML = `
            <table class="runs-table">
                <thead><tr><th>Started</th><th>Status</th><th>By</th><th>Rows</th><th>File</th></tr></thead>
                <tbody>${rows}</tbody>
            </table>`;
    } catch (error) {
        box.innerHTML = '<p class="field-hint">Could not load runs.</p>';
    }
}

setupScheduler();
