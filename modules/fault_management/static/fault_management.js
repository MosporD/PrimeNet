function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text == null ? '' : String(text);
    return div.innerHTML;
}

function escapeAttr(text) {
    return escapeHtml(text).replace(/"/g, '&quot;');
}

let fmCurrentAlarms = [];
let fmTableState = {
    search: '',
    severity: '',
    sortKey: 'occur_time',
    sortDir: 'desc',
};

const FM_TABLE_COLUMNS = [
    { key: 'severity', label: 'Severity', sortable: true },
    { key: 'me_name', label: 'NE', sortable: true },
    { key: 'site_id', label: 'Site', sortable: true },
    { key: 'product_name', label: 'Product', sortable: true },
    { key: 'alarm_name', label: 'Alarm', sortable: true },
    { key: 'occur_time', label: 'Occurred', sortable: true, type: 'date' },
    { key: 'location_info', label: 'Location', sortable: true },
    { key: 'probable_cause', label: 'Cause', sortable: true },
    { key: '__details', label: 'Details', sortable: false },
];

function alarmExtraFields(alarm) {
    const raw = alarm.raw && typeof alarm.raw === 'object' ? alarm.raw : {};
    const merged = { ...raw, ...alarm };
    const skip = new Set(['raw', 'severity', 'me_name', 'alarm_name', 'occur_time', 'location_info', 'probable_cause']);
    return Object.entries(merged)
        .filter(([key, value]) => !skip.has(key) && value != null && String(value).trim() !== '')
        .sort(([a], [b]) => String(a).localeCompare(String(b), undefined, { sensitivity: 'base' }));
}

function openAlarmInfoModal(index) {
    const alarm = fmCurrentAlarms[Number(index)];
    if (!alarm) return;

    const modal = document.getElementById('fm-info-modal');
    const title = document.getElementById('fm-info-title');
    const subtitle = document.getElementById('fm-info-subtitle');
    const body = document.getElementById('fm-info-body');
    if (!modal || !title || !subtitle || !body) return;

    const extras = alarmExtraFields(alarm);
    title.textContent = alarm.alarm_name || 'Alarm details';
    subtitle.textContent = [alarm.me_name, alarm.occur_time].filter(Boolean).join(' · ');
    body.innerHTML = extras.length
        ? `<table class="fm-info-table">
            <tbody>
                ${extras.map(([key, value]) => `
                    <tr>
                        <th>${escapeHtml(key)}</th>
                        <td>${escapeHtml(value)}</td>
                    </tr>
                `).join('')}
            </tbody>
        </table>`
        : '<p class="fm-info-empty">No additional alarm details returned for this row.</p>';

    modal.hidden = false;
    modal.removeAttribute('hidden');
    modal.classList.add('is-open');
    modal.style.display = 'flex';
    modal.querySelector('.fm-info-close')?.focus();
}

function closeAlarmInfoModal() {
    const modal = document.getElementById('fm-info-modal');
    if (!modal) return;
    modal.classList.remove('is-open');
    modal.style.display = 'none';
    modal.hidden = true;
}

function setFaultVendor(vendor) {
    const normalized = vendor === 'nokia' ? 'nokia' : 'huawei';
    const vendorInput = document.getElementById('fm-vendor');
    const statusEl = document.getElementById('fm-status');
    const tableWrap = document.getElementById('fm-table-wrap');

    if (vendorInput) vendorInput.value = normalized;
    document.querySelectorAll('.fm-vendor-tab').forEach((btn) => {
        const active = btn.dataset.vendor === normalized;
        btn.classList.toggle('active', active);
        btn.setAttribute('aria-selected', active ? 'true' : 'false');
    });

    fmCurrentAlarms = [];
    if (tableWrap) {
        tableWrap.hidden = true;
        tableWrap.innerHTML = '';
    }
    if (statusEl) {
        statusEl.className = 'fm-status';
        statusEl.textContent = `Query to load ${normalized === 'nokia' ? 'Nokia NetAct' : 'Huawei U2000'} FM alarms.`;
    }
    closeAlarmInfoModal();
}

function resetFaultTableState() {
    fmTableState = {
        search: '',
        severity: '',
        sortKey: 'occur_time',
        sortDir: 'desc',
    };
}

function alarmSearchText(alarm) {
    const raw = alarm.raw && typeof alarm.raw === 'object' ? alarm.raw : {};
    return Object.values({ ...raw, ...alarm })
        .filter((value) => value != null && String(value).trim() !== '')
        .map((value) => String(value).toLowerCase())
        .join(' ');
}

function alarmSortValue(alarm, column) {
    const value = alarm[column.key];
    if (column.type === 'date') {
        const ts = Date.parse(value || '');
        return Number.isNaN(ts) ? 0 : ts;
    }
    return String(value == null ? '' : value).toLowerCase();
}

function filteredSortedFaultRows() {
    const search = fmTableState.search.trim().toLowerCase();
    const severity = fmTableState.severity.trim().toLowerCase();
    const column = FM_TABLE_COLUMNS.find((col) => col.key === fmTableState.sortKey && col.sortable);

    let rows = fmCurrentAlarms.map((alarm, index) => ({ alarm, index }));
    if (severity) {
        rows = rows.filter(({ alarm }) => String(alarm.severity || '').trim().toLowerCase() === severity);
    }
    if (search) {
        rows = rows.filter(({ alarm }) => alarmSearchText(alarm).includes(search));
    }
    if (column) {
        const dir = fmTableState.sortDir === 'asc' ? 1 : -1;
        rows.sort((a, b) => {
            const av = alarmSortValue(a.alarm, column);
            const bv = alarmSortValue(b.alarm, column);
            if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * dir;
            return String(av).localeCompare(String(bv), undefined, { numeric: true, sensitivity: 'base' }) * dir;
        });
    }
    return rows;
}

function renderFaultTableControls(total, filtered) {
    const severities = [...new Set(fmCurrentAlarms
        .map((alarm) => String(alarm.severity || '').trim())
        .filter(Boolean))]
        .sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' }));

    return `
        <div class="fm-table-controls" role="region" aria-label="Alarm table filters">
            <label class="fm-table-search">
                <span>Search table</span>
                <input type="search" id="fm-table-search" value="${escapeAttr(fmTableState.search)}"
                    placeholder="Search alarms, NEs, causes, details...">
            </label>
            <label class="fm-table-filter">
                <span>Severity</span>
                <select id="fm-table-severity">
                    <option value="">All severities</option>
                    ${severities.map((sev) => `
                        <option value="${escapeAttr(sev)}" ${fmTableState.severity === sev ? 'selected' : ''}>${escapeHtml(sev)}</option>
                    `).join('')}
                </select>
            </label>
            <button type="button" class="fm-table-clear" id="fm-table-clear">Clear</button>
            <span class="fm-table-count">${filtered} / ${total} alarm(s)</span>
        </div>
    `;
}

function renderFaultTableView(wrap) {
    const activeId = document.activeElement?.id || '';
    const rows = filteredSortedFaultRows();
    const header = FM_TABLE_COLUMNS.map((column) => {
        if (!column.sortable) return `<th>${escapeHtml(column.label)}</th>`;
        const active = fmTableState.sortKey === column.key;
        const indicator = active ? (fmTableState.sortDir === 'asc' ? '▲' : '▼') : '↕';
        return `<th>
            <button type="button" class="fm-sort-btn${active ? ' active' : ''}" data-sort-key="${escapeAttr(column.key)}">
                <span>${escapeHtml(column.label)}</span>
                <span aria-hidden="true">${indicator}</span>
            </button>
        </th>`;
    }).join('');

    const body = rows.length
        ? rows.map(({ alarm, index }) => {
            const extras = alarmExtraFields(alarm);
            const details = extras.length
                ? `<button type="button" class="fm-more-info-btn" data-alarm-index="${index}" onclick="openAlarmInfoModal(${index})">More info</button>`
                : '';
            return `
                <tr>
                    <td><span class="fm-severity">${escapeHtml(alarm.severity)}</span></td>
                    <td>${escapeHtml(alarm.me_name)}</td>
                    <td>${escapeHtml(alarm.site_id)}</td>
                    <td>${escapeHtml(alarm.product_name)}</td>
                    <td>${escapeHtml(alarm.alarm_name)}</td>
                    <td>${escapeHtml(alarm.occur_time)}</td>
                    <td>${escapeHtml(alarm.location_info)}</td>
                    <td>${escapeHtml(alarm.probable_cause)}</td>
                    <td>${details}</td>
                </tr>
            `;
        }).join('')
        : '<tr><td colspan="9" class="fm-table-empty">No alarms match the current table filters.</td></tr>';

    wrap.innerHTML = `
        ${renderFaultTableControls(fmCurrentAlarms.length, rows.length)}
        <div class="fm-table-scroll">
            <table class="fm-table">
                <thead><tr>${header}</tr></thead>
                <tbody>${body}</tbody>
            </table>
        </div>
    `;
    wrap.hidden = false;

    const restore = activeId && document.getElementById(activeId);
    if (restore) {
        restore.focus();
        if (restore.id === 'fm-table-search') {
            const len = restore.value.length;
            restore.setSelectionRange(len, len);
        }
    }
}

function renderFaultTable(wrap, alarms) {
    if (!alarms.length) {
        fmCurrentAlarms = [];
        resetFaultTableState();
        wrap.hidden = true;
        wrap.innerHTML = '';
        return;
    }

    fmCurrentAlarms = alarms;
    resetFaultTableState();
    renderFaultTableView(wrap);
}

async function loadFaults() {
    const statusEl = document.getElementById('fm-status');
    const tableWrap = document.getElementById('fm-table-wrap');
    const btn = document.getElementById('fm-refresh-btn');
    const vendor = document.getElementById('fm-vendor').value || 'huawei';
    const dataType = document.getElementById('fm-data-type').value || 'CURRENT';
    const limit = parseInt(document.getElementById('fm-limit').value, 10) || 200;
    const neName = document.getElementById('fm-ne-name').value.trim();
    const period = document.getElementById('fm-period').value || '24';
    const startTime = document.getElementById('fm-start-time').value;
    const endTime = document.getElementById('fm-end-time').value;

    btn.disabled = true;
    tableWrap.hidden = true;
    tableWrap.innerHTML = '';
    statusEl.className = 'fm-status';
    statusEl.textContent = `Loading ${dataType.toLowerCase()} FM alarms from ${vendor.toUpperCase()}...`;

    try {
        const response = await fetch(`/api/fault-management/${encodeURIComponent(vendor)}/faults`, {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                data_type: dataType,
                limit,
                ne_name: neName,
                period_hours: period === 'custom' ? null : Number(period),
                start_time: period === 'custom' ? startTime : '',
                end_time: period === 'custom' ? endTime : '',
            }),
        });
        const data = await response.json();
        if (!response.ok || !data.success) {
            throw new Error(data.error || 'Could not load FM faults');
        }
        const alarms = data.alarms || [];
        statusEl.textContent = alarms.length
            ? `Showing ${alarms.length} ${vendor.toUpperCase()} ${dataType.toLowerCase()} FM alarm(s).`
            : `No ${vendor.toUpperCase()} ${dataType.toLowerCase()} FM alarms returned for this request.`;
        renderFaultTable(tableWrap, alarms);
    } catch (error) {
        statusEl.className = 'fm-status fm-status-error';
        statusEl.textContent = error.message || 'Could not load FM faults';
    } finally {
        btn.disabled = false;
    }
}

document.getElementById('fm-refresh-btn').addEventListener('click', loadFaults);
document.querySelectorAll('.fm-vendor-tab').forEach((btn) => {
    btn.addEventListener('click', () => setFaultVendor(btn.dataset.vendor));
});
document.getElementById('fm-table-wrap').addEventListener('click', (event) => {
    const target = event.target instanceof Element ? event.target : event.target?.parentElement;
    const btn = target?.closest('.fm-more-info-btn');
    if (btn) {
        event.preventDefault();
        openAlarmInfoModal(btn.getAttribute('data-alarm-index'));
        return;
    }

    const sortBtn = target?.closest('.fm-sort-btn');
    if (sortBtn) {
        const key = String(sortBtn.getAttribute('data-sort-key') || '');
        if (fmTableState.sortKey === key) {
            fmTableState.sortDir = fmTableState.sortDir === 'asc' ? 'desc' : 'asc';
        } else {
            fmTableState.sortKey = key;
            fmTableState.sortDir = key === 'occur_time' ? 'desc' : 'asc';
        }
        renderFaultTableView(event.currentTarget);
    }
});
document.getElementById('fm-table-wrap').addEventListener('input', (event) => {
    if (event.target?.id !== 'fm-table-search') return;
    fmTableState.search = event.target.value || '';
    renderFaultTableView(event.currentTarget);
});
document.getElementById('fm-table-wrap').addEventListener('change', (event) => {
    if (event.target?.id !== 'fm-table-severity') return;
    fmTableState.severity = event.target.value || '';
    renderFaultTableView(event.currentTarget);
});
document.getElementById('fm-table-wrap').addEventListener('click', (event) => {
    if (event.target?.id !== 'fm-table-clear') return;
    resetFaultTableState();
    renderFaultTableView(event.currentTarget);
});
document.getElementById('fm-info-modal').addEventListener('click', (event) => {
    const target = event.target instanceof Element ? event.target : event.target?.parentElement;
    if (target?.id === 'fm-info-modal' || target?.closest('[data-fm-info-close]')) {
        closeAlarmInfoModal();
    }
});
document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeAlarmInfoModal();
});
document.getElementById('fm-period').addEventListener('change', (event) => {
    const custom = event.target.value === 'custom';
    document.querySelectorAll('.fm-custom-period').forEach((el) => { el.hidden = !custom; });
});
