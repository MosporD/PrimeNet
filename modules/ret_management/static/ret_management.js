(function () {
    'use strict';

    const body = document.body;
    const huaweiEnabled = body.dataset.huaweiEnabled === 'true';
    const cmWriteAllowed = body.dataset.cmWriteAllowed === 'true';

    const vendorTabs = Array.from(document.querySelectorAll('.vendor-tab'));
    const neSearch = document.getElementById('ne-search');
    const neSelect = document.getElementById('ne-select');
    const loadBtn = document.getElementById('load-rets-btn');
    const reloadBtn = document.getElementById('reload-btn');
    const saveBtn = document.getElementById('save-changes-btn');
    const loadStatus = document.getElementById('load-status');
    const configStatus = document.getElementById('cm-config-status');
    const resultsPanel = document.getElementById('results-panel');
    const resultsTitle = document.getElementById('results-title');
    const warningsBox = document.getElementById('results-warnings');
    const retTable = document.getElementById('ret-table');
    const emptyState = document.getElementById('empty-state');
    const writeHint = document.getElementById('write-hint');
    const nokiaOnly = document.getElementById('nokia-only-fields');
    const confId = document.getElementById('conf-id');

    let vendor = 'nokia';
    let neItems = [];
    let currentRows = [];
    let serverColumns = [];
    let pendingChanges = new Map();

    const HUAWEI_EDIT_COL = 'Tilt';
    const NOKIA_EDIT_COL = 'angle';

    function normalizeKey(text) {
        return String(text || '').toLowerCase().replace(/[^a-z0-9]+/g, '');
    }

    function isHuaweiTiltColumn(col) {
        const key = normalizeKey(col);
        if (!key.startsWith('tilt')) return false;
        if (key.includes('actual')) return false;
        if (key.includes('alarm') || key.includes('error') || key.includes('range')) return false;
        return true;
    }

    function resolveHuaweiField(row, canonical) {
        const aliases = {
            'Device No.': ['Device No.', 'DeviceNo', 'DEVICENO', 'Device No'],
            'Subunit No.': ['Subunit No.', 'SubunitNo', 'SUBUNITNO', 'Subunit No'],
            'Subunit Name': ['Subunit Name', 'SubunitName', 'SUBUNITNAME'],
            Tilt: ['Tilt', 'TILT'],
            'Actual Tilt': ['Actual Tilt', 'ActualTilt', 'RtmTilt', 'RTMTILT'],
            'Online Status': ['Online Status', 'OnlineStatus', 'Status', 'STATUS'],
        };
        const candidates = aliases[canonical] || [canonical];
        for (const key of candidates) {
            if (row[key] !== undefined && row[key] !== null && String(row[key]).trim() !== '') {
                return String(row[key]).trim();
            }
        }
        const target = normalizeKey(canonical);
        for (const [key, value] of Object.entries(row)) {
            if (normalizeKey(key) === target && value !== undefined && value !== null) {
                return String(value).trim();
            }
        }
        if (canonical === 'Tilt') {
            for (const [key, value] of Object.entries(row)) {
                if (isHuaweiTiltColumn(key) && value !== undefined && value !== null) {
                    return String(value).trim();
                }
            }
        }
        if (canonical === 'Actual Tilt') {
            for (const [key, value] of Object.entries(row)) {
                const nk = normalizeKey(key);
                if (nk.includes('actual') && nk.includes('tilt') && value !== undefined && value !== null) {
                    return String(value).trim();
                }
            }
        }
        return '';
    }

    function resolveEditColumn(columns) {
        if (vendor === 'nokia') {
            return columns.find((col) => normalizeKey(col) === 'angle') || NOKIA_EDIT_COL;
        }
        return columns.find((col) => isHuaweiTiltColumn(col))
            || columns.find((col) => normalizeKey(col) === 'tilt')
            || HUAWEI_EDIT_COL;
    }

    function setStatus(el, text, kind) {
        el.textContent = text || '';
        el.classList.remove('error', 'ok', 'warn');
        if (kind) el.classList.add(kind);
    }

    function selectedNe() {
        const option = neSelect.options[neSelect.selectedIndex];
        if (!option || !option.value) return null;
        return {
            site_id: option.value,
            label: option.textContent,
            ne_name: option.dataset.neName || '',
        };
    }

    function updateVendorUi() {
        const isNokia = vendor === 'nokia';
        nokiaOnly.hidden = !isNokia;
        resultsTitle.textContent = isNokia ? 'LNCEL antenna angles' : 'RETSUBUNIT tilts (LST + DSP)';
        pendingChanges.clear();
        currentRows = [];
        serverColumns = [];
        resultsPanel.hidden = true;
        loadNeList();
    }

    async function fetchDefaults() {
        try {
            const res = await fetch('/api/ret-management/defaults');
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || 'Failed to load defaults');

            const nokiaOk = data.nokia_configured;
            const huaweiOk = data.huawei_enabled && data.huawei_configured;
            if (vendor === 'nokia' && nokiaOk) {
                setStatus(configStatus, 'Nokia CM configured', 'ok');
            } else if (vendor === 'huawei' && huaweiOk) {
                setStatus(configStatus, 'Huawei CM configured', 'ok');
            } else if (vendor === 'nokia') {
                setStatus(configStatus, 'Nokia CM not configured', 'error');
            } else {
                setStatus(configStatus, 'Huawei CM not configured', 'error');
            }

            if (!data.cm_write_allowed) {
                writeHint.hidden = false;
                saveBtn.hidden = true;
            }
        } catch (err) {
            setStatus(configStatus, err.message, 'error');
        }
    }

    async function loadNeList() {
        neSelect.innerHTML = '';
        setStatus(loadStatus, 'Loading NE list…');
        try {
            const q = encodeURIComponent(neSearch.value.trim());
            const res = await fetch(`/api/ret-management/nes?vendor=${vendor}&q=${q}&limit=500`);
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || 'Failed to load NE list');
            neItems = data.items || [];
            neItems.forEach((item) => {
                const opt = document.createElement('option');
                opt.value = item.site_id || item.id || '';
                const name = item.site_name || item.name || item.label || opt.value;
                opt.textContent = `${name} (${opt.value})`;
                const neName = item.u2020_ne_name || item.ne_name || '';
                if (neName) opt.dataset.neName = neName;
                neSelect.appendChild(opt);
            });
            setStatus(loadStatus, `${neItems.length} NE(s) loaded`);
        } catch (err) {
            setStatus(loadStatus, err.message, 'error');
        }
    }

    function rowKey(row, index) {
        if (vendor === 'huawei') {
            const device = resolveHuaweiField(row, 'Device No.');
            const subunit = resolveHuaweiField(row, 'Subunit No.');
            return `${device}:${subunit}`;
        }
        return row.DN || row.dn || `row-${index}`;
    }

    function displayColumns(rows) {
        if (vendor === 'huawei') {
            const preferred = [
                'Device No.', 'Subunit No.', 'Subunit Name', 'Tilt', 'Actual Tilt', 'Online Status',
            ];
            const keys = new Set();
            rows.forEach((row) => Object.keys(row).forEach((k) => keys.add(k)));
            const cols = preferred.filter((c) => keys.has(c) || rows.some((row) => resolveHuaweiField(row, c) !== ''));
            keys.forEach((k) => {
                if (!cols.includes(k) && k !== '$instance' && k !== '_mml_warnings' && k !== 'NE') {
                    if (isHuaweiTiltColumn(k) && cols.some((c) => c === 'Tilt' || isHuaweiTiltColumn(c))) {
                        return;
                    }
                    cols.push(k);
                }
            });
            if (rows.some((row) => row.NE)) cols.push('NE');
            return cols.length ? cols : preferred;
        }
        if (!rows.length) {
            return vendor === 'nokia'
                ? ['DN', 'name', 'angle']
                : ['Device No.', 'Subunit No.', 'Subunit Name', 'Tilt', 'Actual Tilt', 'Online Status'];
        }
        const preferred = vendor === 'nokia'
            ? ['DN', 'name', 'angle']
            : ['Device No.', 'Subunit No.', 'Subunit Name', 'Tilt', 'Actual Tilt', 'Online Status', 'NE'];
        const keys = new Set();
        rows.forEach((row) => Object.keys(row).forEach((k) => keys.add(k)));
        const cols = preferred.filter((c) => keys.has(c));
        keys.forEach((k) => {
            if (!cols.includes(k) && k !== '$instance' && k !== '_mml_warnings') cols.push(k);
        });
        return cols;
    }

    function huaweiCanEdit(rows) {
        return vendor === 'huawei' && rows.length > 0;
    }

    function renderTable(rows) {
        currentRows = rows;
        pendingChanges.clear();
        const thead = retTable.querySelector('thead');
        const tbody = retTable.querySelector('tbody');
        thead.innerHTML = '';
        tbody.innerHTML = '';

        if (!rows.length) {
            emptyState.hidden = false;
            retTable.hidden = true;
            saveBtn.hidden = true;
            return;
        }

        emptyState.hidden = true;
        retTable.hidden = false;
        const columns = displayColumns(rows);
        const editCol = resolveEditColumn(columns);
        const hasEditColumn = vendor === 'huawei'
            ? huaweiCanEdit(rows) && (columns.includes(editCol) || resolveHuaweiField(rows[0], 'Tilt') !== '')
            : columns.includes(editCol);

        const headRow = document.createElement('tr');
        columns.forEach((col) => {
            const th = document.createElement('th');
            th.textContent = col;
            if (col === editCol && cmWriteAllowed && hasEditColumn) {
                th.title = vendor === 'huawei' ? 'Editable — applied via MOD RETSUBUNIT' : 'Editable — applied via Nokia CM import';
            }
            headRow.appendChild(th);
        });
        if (cmWriteAllowed && hasEditColumn) {
            const actionTh = document.createElement('th');
            actionTh.textContent = 'Action';
            headRow.appendChild(actionTh);
        }
        thead.appendChild(headRow);

        rows.forEach((row, index) => {
            const tr = document.createElement('tr');
            tr.dataset.rowKey = rowKey(row, index);
            columns.forEach((col) => {
                const td = document.createElement('td');
                const raw = vendor === 'huawei' ? resolveHuaweiField(row, col) : (row[col] ?? '');
                const isTiltCell = vendor === 'huawei' && col === editCol;
                const value = isTiltCell
                    ? (resolveHuaweiField(row, 'Tilt') || resolveHuaweiField(row, 'Actual Tilt'))
                    : raw;
                if (isTiltCell && cmWriteAllowed && hasEditColumn) {
                    const input = document.createElement('input');
                    input.type = 'text';
                    input.className = 'tilt-input';
                    input.value = value;
                    input.dataset.original = String(value);
                    input.addEventListener('input', () => {
                        const key = tr.dataset.rowKey;
                        if (input.value !== input.dataset.original) {
                            pendingChanges.set(key, { row, index, value: input.value });
                            tr.classList.add('row-changed');
                        } else {
                            pendingChanges.delete(key);
                            tr.classList.remove('row-changed');
                        }
                        saveBtn.hidden = !cmWriteAllowed || pendingChanges.size === 0;
                    });
                    td.appendChild(input);
                } else {
                    td.textContent = value;
                }
                tr.appendChild(td);
            });
            if (cmWriteAllowed && hasEditColumn) {
                const actionTd = document.createElement('td');
                const modBtn = document.createElement('button');
                modBtn.type = 'button';
                modBtn.className = 'btn-secondary btn-row-mod';
                modBtn.textContent = vendor === 'huawei' ? 'MOD' : 'Apply';
                modBtn.addEventListener('click', () => saveSingleRow(row, index, tr));
                actionTd.appendChild(modBtn);
                tr.appendChild(actionTd);
            }
            tbody.appendChild(tr);
        });

        saveBtn.hidden = !cmWriteAllowed || !hasEditColumn || pendingChanges.size === 0;
    }

    async function saveSingleRow(row, index, tr) {
        const ne = selectedNe();
        if (!ne) return;
        const tiltInput = tr.querySelector('.tilt-input');
        const tiltValue = tiltInput ? tiltInput.value : (vendor === 'nokia' ? row.angle : resolveHuaweiField(row, 'Tilt'));
        if (!tiltValue && tiltValue !== '0') {
            setStatus(loadStatus, 'Enter a tilt value first', 'error');
            return;
        }
        saveBtn.disabled = true;
        setStatus(loadStatus, 'Applying change…');
        try {
            if (vendor === 'nokia') {
                const res = await fetch('/api/ret-management/nokia/lncel/update', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        updates: [{
                            dist_name: row.DN || row.dn,
                            angle: tiltValue,
                            old_angle: row.angle ?? '',
                        }],
                        wait: true,
                    }),
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.error || 'Nokia update failed');
            } else {
                const payload = {
                    site_id: ne.site_id,
                    ne_name: ne.ne_name,
                    device_no: resolveHuaweiField(row, 'Device No.'),
                    subunit_no: resolveHuaweiField(row, 'Subunit No.'),
                    tilt: tiltValue,
                };
                const res = await fetch('/api/ret-management/huawei/rets/update', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
                const data = await res.json();
                if (!res.ok) {
                    const detail = data.vendor_request
                        ? ` ${JSON.stringify(data.vendor_request.body)}`
                        : '';
                    throw new Error((data.error || 'Huawei MOD failed') + detail);
                }
            }
            setStatus(loadStatus, 'Change applied successfully', 'ok');
            await loadRets();
        } catch (err) {
            setStatus(loadStatus, err.message, 'error');
        } finally {
            saveBtn.disabled = false;
        }
    }

    function showWarnings(warnings) {
        if (!warnings || !warnings.length) {
            warningsBox.hidden = true;
            warningsBox.textContent = '';
            return;
        }
        warningsBox.hidden = false;
        warningsBox.textContent = warnings.join(' ');
    }

    async function loadRets() {
        const ne = selectedNe();
        if (!ne) {
            setStatus(loadStatus, 'Select a network element first', 'error');
            return;
        }

        setStatus(loadStatus, 'Loading RET data…');
        resultsPanel.hidden = false;
        try {
            let url;
            if (vendor === 'nokia') {
                url = `/api/ret-management/nokia/lncel?site_id=${encodeURIComponent(ne.site_id)}&conf_id=${encodeURIComponent(confId.value)}`;
            } else {
                url = `/api/ret-management/huawei/rets?site_id=${encodeURIComponent(ne.site_id)}`;
                if (ne.ne_name) url += `&ne_name=${encodeURIComponent(ne.ne_name)}`;
            }
            const res = await fetch(url);
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || 'Failed to load RET data');
            serverColumns = data.columns || [];
            showWarnings(data.warnings);
            renderTable(data.rows || []);
            setStatus(loadStatus, `Loaded ${(data.rows || []).length} record(s) for ${ne.label}`, 'ok');
        } catch (err) {
            renderTable([]);
            setStatus(loadStatus, err.message, 'error');
        }
    }

    async function saveChanges() {
        const ne = selectedNe();
        if (!ne || pendingChanges.size === 0) return;

        saveBtn.disabled = true;
        setStatus(loadStatus, 'Applying changes…');
        try {
            if (vendor === 'nokia') {
                const updates = [];
                pendingChanges.forEach(({ row, value }) => {
                    updates.push({
                        dist_name: row.DN || row.dn,
                        angle: value,
                        old_angle: row.angle ?? row[NOKIA_EDIT_COL] ?? '',
                    });
                });
                const res = await fetch('/api/ret-management/nokia/lncel/update', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ updates, wait: true }),
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.error || 'Nokia update failed');
            } else {
                for (const { row, value } of pendingChanges.values()) {
                    const payload = {
                        site_id: ne.site_id,
                        ne_name: ne.ne_name,
                        device_no: resolveHuaweiField(row, 'Device No.'),
                        subunit_no: resolveHuaweiField(row, 'Subunit No.'),
                        tilt: value,
                    };
                    const res = await fetch('/api/ret-management/huawei/rets/update', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload),
                    });
                    const data = await res.json();
                    if (!res.ok) throw new Error(data.error || 'Huawei MOD failed');
                }
            }
            setStatus(loadStatus, 'Changes applied successfully', 'ok');
            await loadRets();
        } catch (err) {
            setStatus(loadStatus, err.message, 'error');
        } finally {
            saveBtn.disabled = false;
        }
    }

    vendorTabs.forEach((tab) => {
        tab.addEventListener('click', () => {
            vendorTabs.forEach((t) => {
                const active = t === tab;
                t.classList.toggle('active', active);
                t.setAttribute('aria-selected', active ? 'true' : 'false');
            });
            vendor = tab.dataset.vendor;
            updateVendorUi();
            fetchDefaults();
        });
    });

    let searchTimer;
    neSearch.addEventListener('input', () => {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(loadNeList, 300);
    });

    loadBtn.addEventListener('click', loadRets);
    reloadBtn.addEventListener('click', loadRets);
    saveBtn.addEventListener('click', saveChanges);

    updateVendorUi();
    fetchDefaults();
})();
