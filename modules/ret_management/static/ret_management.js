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
    const exportBtn = document.getElementById('export-excel-btn');
    const saveBtn = document.getElementById('save-changes-btn');
    const loadStatus = document.getElementById('load-status');
    const configStatus = document.getElementById('cm-config-status');
    const userCredStatus = document.getElementById('user-cred-status');
    const resultsPanel = document.getElementById('results-panel');
    const resultsTitle = document.getElementById('results-title');
    const warningsBox = document.getElementById('results-warnings');
    const retTable = document.getElementById('ret-table');
    const emptyState = document.getElementById('empty-state');
    const writeHint = document.getElementById('write-hint');
    const tableFilterInput = document.getElementById('ret-table-filter');
    const tableMeta = document.getElementById('ret-table-meta');
    const holoPanel = document.getElementById('holo-panel');
    const holoCanvas = document.getElementById('holo-canvas');
    const holoSiteMeta = document.getElementById('holo-site-meta');
    const holoStatus = document.getElementById('holo-status');
    const holoChips = document.getElementById('holo-sector-chips');
    const holoEditSummary = document.getElementById('holo-edit-summary');
    const holoLegend = document.getElementById('holo-legend');
    const holoResetBtn = document.getElementById('holo-reset-btn');
    const holoPitch = document.getElementById('holo-pitch');

    let vendor = 'nokia';
    let neItems = [];
    let currentRows = [];
    let serverColumns = [];
    let pendingChanges = new Map();
    let nokiaMoClass = '';
    let sortState = { col: null, dir: 1 };
    let tableFilter = '';
    let sectorFilter = '';
    let loadedNeKey = '';
    let siteLayout = null;
    let layoutRequestId = 0;
    let hologram = null;
    /** Always live network (NetAct conf_id=1). */
    const LIVE_CONF_ID = 1;

    const HUAWEI_EDIT_COL = 'Tilt';
    const NOKIA_EDIT_COL = 'angle';
    const NOKIA_PREFERRED_COLS = [
        'DN', '$instance', 'sectorID', 'angle', 'minAngle', 'maxAngle', 'mechanicalAngle',
        'baseStationID', 'antModel', 'antSerial', 'antBearing', 'subunitNumber',
        'installDate', 'operationalState',
    ];

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
            metadata_site_id: option.dataset.metadataSiteId || '',
            site_name: option.dataset.siteName || '',
        };
    }

    /** Identity of the loaded NE — used to decide whether to keep the table view. */
    function neKey(ne) {
        return ne ? `${vendor}|${ne.site_id}|${ne.ne_name}` : '';
    }

    function updateVendorUi() {
        const isNokia = vendor === 'nokia';
        resultsTitle.textContent = isNokia ? 'RETU_R antenna angles' : 'RETSUBUNIT tilts (LST + DSP)';
        pendingChanges.clear();
        currentRows = [];
        serverColumns = [];
        nokiaMoClass = '';
        sortState = { col: null, dir: 1 };
        tableFilter = '';
        sectorFilter = '';
        loadedNeKey = '';
        siteLayout = null;
        layoutRequestId += 1;
        if (hologram) {
            hologram.setSelected(null);
            hologram.setSectors([]);
        }
        if (tableFilterInput) tableFilterInput.value = '';
        resultsPanel.hidden = true;
        if (holoPanel) holoPanel.hidden = true;
        if (exportBtn) exportBtn.disabled = true;
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

            if (userCredStatus) {
                const creds = data.user_credentials || {};
                const vendorKey = vendor === 'huawei' ? 'huawei' : 'nokia';
                const info = creds[vendorKey] || {};
                if (info.configured) {
                    setStatus(userCredStatus, `Using your ${vendorKey === 'huawei' ? 'U2020' : 'MantaRay'} account (${info.username})`, 'ok');
                } else {
                    setStatus(
                        userCredStatus,
                        `No personal ${vendorKey === 'huawei' ? 'U2020' : 'MantaRay'} credentials — actions will be flagged for admin`,
                        'error',
                    );
                }
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
                if (item.metadata_site_id) opt.dataset.metadataSiteId = item.metadata_site_id;
                opt.dataset.siteName = name;
                neSelect.appendChild(opt);
            });
            setStatus(loadStatus, `${neItems.length} NE(s) loaded`);
        } catch (err) {
            setStatus(loadStatus, err.message, 'error');
        }
    }

    /**
     * Identity of a table row, stable across reloads.
     *
     * The API stamps `_ret_key` on every row (device:subunit for Huawei, the
     * config RETU DN for Nokia). Falling back to the array index is what used to
     * let edits and highlights jump to a different row after a reload, so the
     * index is only a last resort for responses from an older server build.
     */
    function rowKey(row, index) {
        const stamped = String(row._ret_key || '').trim();
        if (stamped) return stamped;
        if (vendor === 'huawei') {
            const device = resolveHuaweiField(row, 'Device No.');
            const subunit = resolveHuaweiField(row, 'Subunit No.');
            if (device || subunit) return `${device}:${subunit}`;
        } else if (row.DN || row.dn) {
            return row.DN || row.dn;
        }
        return `row-${index}`;
    }

    function rowSector(row) {
        return String(row._ret_sector || '').trim();
    }

    function isMetaColumn(key) {
        const name = String(key || '');
        return name.startsWith('_') || name === '$instance' || name === 'report';
    }

    /** Sector ids and band labels come from the inventory DB, so never trust them as markup. */
    function escapeHtml(value) {
        return String(value ?? '').replace(/[&<>"']/g, (ch) => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
        }[ch]));
    }

    /* ---------------------------------------------------------------- hologram */

    const UNMAPPED_SECTOR = '__unmapped__';
    const HUAWEI_TILT_UNSET = 32767;
    /**
     * Derived first column, present for both vendors, that names the sector a RET
     * row drives. Nokia gets it from `sectorID`, Huawei from `Actual Sector ID`
     * or the subunit name — so an edit can always be traced to a hologram lobe.
     */
    const SECTOR_COLUMN = 'Sector';

    function sectorLabelFor(key) {
        if (key === UNMAPPED_SECTOR) return 'unmapped';
        const layoutSector = (siteLayout?.sectors || []).find((sector) => sector.key === key);
        if (layoutSector) return layoutSector.label;
        if (/^\d+$/.test(key)) {
            const index = Number(key);
            return index >= 1 && index <= 26 ? `${index} (${String.fromCharCode(64 + index)})` : key;
        }
        return key;
    }

    /**
     * Unit of the Nokia RETU `angle` field for the loaded rows.
     *
     * The MO is defined in 0.1° steps, but some NetAct adaptations report whole
     * degrees. A decimal point means degrees; otherwise a magnitude above 20 can
     * only be tenths (no RET does 20°+ of electrical downtilt).
     */
    function nokiaAngleScale(rows) {
        let maxSeen = 0;
        let sawFraction = false;
        (rows || []).forEach((row) => {
            ['angle', 'minAngle', 'maxAngle'].forEach((key) => {
                const text = String(row[key] ?? '').trim();
                if (!text) return;
                if (text.includes('.')) sawFraction = true;
                const value = Number(text);
                if (Number.isFinite(value)) maxSeen = Math.max(maxSeen, Math.abs(value));
            });
        });
        if (sawFraction) return 1;
        return maxSeen > 20 ? 0.1 : 1;
    }

    /** Vendor tilt/angle string → degrees. NaN when the NE reports no usable value. */
    function tiltToDegrees(rawValue, scale) {
        const text = String(rawValue ?? '').trim();
        if (!text) return NaN;
        const value = Number(text);
        if (!Number.isFinite(value)) return NaN;
        if (vendor === 'huawei') {
            if (value === HUAWEI_TILT_UNSET) return NaN;
            return text.includes('.') ? value : value / 10;
        }
        return value * scale;
    }

    function committedTiltRaw(row) {
        if (vendor === 'huawei') {
            return resolveHuaweiField(row, 'Tilt') || resolveHuaweiField(row, 'Actual Tilt');
        }
        return row.angle ?? '';
    }

    /** Per-sector RET state, merged onto the inventory geometry. */
    function computeSectors() {
        const scale = vendor === 'nokia' ? nokiaAngleScale(currentRows) : 1;
        const perSector = new Map();
        let unmappedCount = 0;
        let unmappedEdits = 0;

        currentRows.forEach((row, index) => {
            const key = rowSector(row);
            const pending = pendingChanges.get(rowKey(row, index));
            const committed = tiltToDegrees(committedTiltRaw(row), scale);
            const current = pending ? tiltToDegrees(pending.value, scale) : committed;
            const edited = Boolean(pending) && String(pending.value).trim() !== String(committedTiltRaw(row)).trim();
            if (!key) {
                unmappedCount += 1;
                if (edited) unmappedEdits += 1;
                return;
            }
            if (!perSector.has(key)) {
                perSector.set(key, { retCount: 0, current: [], committed: [], edited: false, azimuths: [] });
            }

            const entry = perSector.get(key);
            entry.retCount += 1;
            if (Number.isFinite(current)) entry.current.push(current);
            if (Number.isFinite(committed)) entry.committed.push(committed);
            if (edited) entry.edited = true;
            const bearing = Number(row._ret_azimuth);
            if (Number.isFinite(bearing)) entry.azimuths.push(bearing);
        });

        const layoutSectors = siteLayout?.sectors || [];
        const sectors = layoutSectors.map((sector) => {
            const ret = perSector.get(sector.key);
            const retAzimuth = ret && ret.azimuths.length ? ret.azimuths[0] : null;
            // A sector can carry several RETs (one per band). The lobe is drawn at
            // the deepest downtilt (shortest reach) and the spread goes to the
            // tooltip, so a 2°/8° pair is never read as a single 8° sector.
            const tiltDeg = ret && ret.current.length
                ? Math.max(...ret.current)
                : (Number.isFinite(sector.electrical_tilt) ? sector.electrical_tilt : NaN);
            const baseline = ret && ret.committed.length ? Math.max(...ret.committed) : NaN;
            const tiltSpread = ret && ret.current.length > 1
                ? [Math.min(...ret.current), Math.max(...ret.current)]
                : null;
            return {
                key: sector.key,
                label: sector.label,
                azimuth: Number.isFinite(retAzimuth) ? retAzimuth : sector.azimuth,
                azimuthSource: Number.isFinite(retAzimuth) ? 'RET antBearing' : sector.azimuth_source,
                beamwidth: sector.beamwidth,
                height: sector.height,
                mechanicalTilt: sector.mechanical_tilt,
                technologies: sector.technologies || [],
                bands: sector.bands || [],
                cellCount: sector.cell_count || 0,
                retCount: ret ? ret.retCount : 0,
                tiltDeg,
                baselineTiltDeg: baseline,
                tiltSpread: tiltSpread && tiltSpread[0] !== tiltSpread[1] ? tiltSpread : null,
                edited: Boolean(ret && ret.edited),
            };
        });

        // RETs reporting a sector the inventory does not know about: draw them
        // when the RET itself reports a bearing, otherwise list them as unmapped.
        const drawn = new Set(sectors.map((sector) => sector.key));
        perSector.forEach((entry, key) => {
            if (drawn.has(key)) return;
            if (!entry.azimuths.length) {
                unmappedCount += entry.retCount;
                if (entry.edited) unmappedEdits += 1;
                return;
            }
            sectors.push({
                key,
                label: sectorLabelFor(key),
                azimuth: entry.azimuths[0],
                azimuthSource: 'RET antBearing (not in inventory)',
                beamwidth: 65,
                height: siteLayout?.site?.antenna_height,
                mechanicalTilt: NaN,
                technologies: [],
                bands: [],
                cellCount: 0,
                retCount: entry.retCount,
                tiltDeg: entry.current.length ? Math.max(...entry.current) : NaN,
                baselineTiltDeg: entry.committed.length ? Math.max(...entry.committed) : NaN,
                tiltSpread: entry.current.length > 1
                    && Math.min(...entry.current) !== Math.max(...entry.current)
                    ? [Math.min(...entry.current), Math.max(...entry.current)]
                    : null,
                edited: entry.edited,
            });
        });

        sectors.sort((a, b) => {
            const aNum = /^\d+$/.test(a.key) ? Number(a.key) : Number.MAX_SAFE_INTEGER;
            const bNum = /^\d+$/.test(b.key) ? Number(b.key) : Number.MAX_SAFE_INTEGER;
            return aNum - bNum || a.key.localeCompare(b.key);
        });
        return { sectors, unmappedCount, unmappedEdits, scale };
    }

    function ensureHologram() {
        if (hologram || !holoCanvas || !window.RetHologram) return hologram;
        hologram = window.RetHologram.create(holoCanvas, {
            onSelectSector(key) {
                sectorFilter = key || '';
                renderTable();
                renderHologramRail();
            },
        });
        return hologram;
    }

    function renderSectorChips(computed) {
        if (!holoChips) return;
        holoChips.innerHTML = '';
        const selected = hologram ? hologram.getSelected() : null;
        computed.sectors.forEach((sector) => {
            const chip = document.createElement('button');
            chip.type = 'button';
            chip.className = 'holo-chip';
            if (sector.edited) chip.classList.add('edited');
            if (selected === sector.key) chip.classList.add('active');
            const tilt = Number.isFinite(sector.tiltDeg)
                ? window.RetHologram.formatDegrees(sector.tiltDeg)
                : 'tilt —';
            [
                ['holo-chip-key', `S${sector.label}`],
                ['holo-chip-az', window.RetHologram.formatDegrees(sector.azimuth)],
                ['holo-chip-tilt', tilt],
            ].forEach(([className, text]) => {
                const span = document.createElement('span');
                span.className = className;
                span.textContent = text;
                chip.appendChild(span);
            });
            chip.title = `${sector.retCount} RET row(s), ${sector.cellCount} cell(s)`
                + (sector.technologies.length ? ` · ${sector.technologies.join(', ')}` : '');
            chip.addEventListener('click', () => {
                const next = selected === sector.key ? null : sector.key;
                if (hologram) hologram.setSelected(next);
                sectorFilter = next || '';
                renderTable();
                renderHologramRail();
            });
            holoChips.appendChild(chip);
        });
        if (computed.unmappedCount) {
            const chip = document.createElement('button');
            chip.type = 'button';
            chip.className = 'holo-chip unmapped';
            if (sectorFilter === UNMAPPED_SECTOR) chip.classList.add('active');
            [
                ['holo-chip-key', 'Unmapped'],
                ['holo-chip-az', `${computed.unmappedCount} RET`],
            ].forEach(([className, text]) => {
                const span = document.createElement('span');
                span.className = className;
                span.textContent = text;
                chip.appendChild(span);
            });
            chip.title = vendor === 'huawei'
                ? 'U2020 did not report a sector id for these RETSUBUNITs'
                : 'These RETU rows carry no sectorID';
            chip.addEventListener('click', () => {
                sectorFilter = sectorFilter === UNMAPPED_SECTOR ? '' : UNMAPPED_SECTOR;
                if (hologram) hologram.setSelected(null);
                renderTable();
                renderHologramRail();
            });
            holoChips.appendChild(chip);
        }
    }

    function renderEditSummary(computed) {
        if (!holoEditSummary) return;
        const edited = computed.sectors.filter((sector) => sector.edited);
        if (!edited.length && !computed.unmappedEdits) {
            holoEditSummary.hidden = true;
            holoEditSummary.innerHTML = '';
            return;
        }
        const parts = edited.map((sector) => {
            const from = Number.isFinite(sector.baselineTiltDeg)
                ? window.RetHologram.formatDegrees(sector.baselineTiltDeg)
                : '—';
            const to = Number.isFinite(sector.tiltDeg)
                ? window.RetHologram.formatDegrees(sector.tiltDeg)
                : '—';
            return `<li><strong>S${escapeHtml(sector.label)}</strong> ${from} → ${to}</li>`;
        });
        if (computed.unmappedEdits) {
            parts.push(`<li><strong>Unmapped</strong> ${computed.unmappedEdits} pending edit(s)</li>`);
        }
        holoEditSummary.hidden = false;
        holoEditSummary.innerHTML = `<h3>Pending tilt edits</h3><ul>${parts.join('')}</ul>`;
    }

    function renderLegend(computed) {
        if (!holoLegend) return;
        const techs = new Set();
        computed.sectors.forEach((sector) => (sector.technologies || []).forEach((tech) => techs.add(tech)));
        const items = Array.from(techs).map((tech) => {
            const colour = window.RetHologram.TECH_COLORS[tech] || [110, 196, 240];
            return `<span class="holo-legend-item">`
                + `<i style="background: rgba(${colour[0]}, ${colour[1]}, ${colour[2]}, 0.85)"></i>`
                + `${escapeHtml(tech)}</span>`;
        });
        items.push('<span class="holo-legend-item"><i class="edited"></i>edited (dashed ring = current tilt)</span>');
        holoLegend.innerHTML = items.join('');
    }

    function renderHologramRail() {
        if (!holoPanel) return;
        const computed = computeSectors();
        renderSectorChips(computed);
        renderEditSummary(computed);
        renderLegend(computed);
        return computed;
    }

    function renderHologram() {
        if (!holoPanel || !holoCanvas || !window.RetHologram) return;
        const holo = ensureHologram();
        if (!holo) return;
        const computed = computeSectors();
        holo.setSite(siteLayout?.site || {});
        holo.setSectors(computed.sectors.filter((sector) => Number.isFinite(sector.azimuth)));
        renderSectorChips(computed);
        renderEditSummary(computed);
        renderLegend(computed);

        if (holoSiteMeta) {
            const site = siteLayout?.site || {};
            const bits = [];
            if (site.site_name) bits.push(site.site_name);
            if (site.metadata_site_id) bits.push(`id ${site.metadata_site_id}`);
            if (Number.isFinite(site.latitude) && Number.isFinite(site.longitude)) {
                bits.push(`${site.latitude.toFixed(5)}, ${site.longitude.toFixed(5)}`);
            }
            if (site.antenna_height) {
                bits.push(
                    `antenna ${Math.round(site.antenna_height)} m`
                    + (site.height_source === 'default' ? ' (assumed)' : ''),
                );
            }
            bits.push(`${computed.sectors.length} sector(s)`);
            holoSiteMeta.textContent = bits.join(' · ');
        }
        if (holoStatus && vendor === 'nokia' && currentRows.length) {
            setStatus(
                holoStatus,
                computed.scale === 1
                    ? 'RETU angle read as whole degrees.'
                    : 'RETU angle read as 0.1° steps (MO definition).',
            );
        }
    }

    async function loadSiteLayout(ne) {
        if (!holoPanel) return;
        siteLayout = null;
        if (!ne) {
            holoPanel.hidden = true;
            return;
        }
        holoPanel.hidden = false;
        setStatus(holoStatus, 'Loading site geometry…');
        const requestId = ++layoutRequestId;
        try {
            const params = new URLSearchParams({
                vendor,
                site_id: ne.site_id || '',
                metadata_site_id: ne.metadata_site_id || '',
                site_name: ne.site_name || '',
                ne_name: ne.ne_name || '',
            });
            const res = await fetch(`/api/ret-management/site-layout?${params.toString()}`);
            const data = await res.json();
            if (requestId !== layoutRequestId) return;
            if (!res.ok) throw new Error(data.error || 'Failed to load site geometry');
            siteLayout = data;
            const warnings = data.warnings || [];
            if (!data.sector_count) {
                setStatus(holoStatus, warnings[0] || 'No sector geometry in metadata for this site.', 'warn');
            } else if (warnings.length) {
                setStatus(holoStatus, warnings.join(' '), 'warn');
            } else {
                setStatus(
                    holoStatus,
                    `${data.sector_count} sector(s) · ${data.cell_count} cell(s) from PrimeNet inventory`,
                    'ok',
                );
            }
        } catch (err) {
            if (requestId !== layoutRequestId) return;
            setStatus(holoStatus, err.message, 'error');
        }
        renderHologram();
    }

    function displayColumns(rows) {
        return rows && rows.length
            ? [SECTOR_COLUMN, ...vendorColumns(rows)]
            : vendorColumns(rows);
    }

    function vendorColumns(rows) {
        if (vendor === 'huawei') {
            const preferred = [
                'Device No.', 'Subunit No.', 'Subunit Name', 'Tilt', 'Actual Tilt', 'Online Status',
            ];
            const keys = new Set();
            rows.forEach((row) => Object.keys(row).forEach((k) => keys.add(k)));
            const cols = preferred.filter((c) => keys.has(c) || rows.some((row) => resolveHuaweiField(row, c) !== ''));
            keys.forEach((k) => {
                if (!cols.includes(k) && !isMetaColumn(k) && k !== 'NE') {
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
                ? NOKIA_PREFERRED_COLS.slice()
                : ['Device No.', 'Subunit No.', 'Subunit Name', 'Tilt', 'Actual Tilt', 'Online Status'];
        }
        const preferred = vendor === 'nokia'
            ? NOKIA_PREFERRED_COLS
            : ['Device No.', 'Subunit No.', 'Subunit Name', 'Tilt', 'Actual Tilt', 'Online Status', 'NE'];
        const keys = new Set();
        rows.forEach((row) => Object.keys(row).forEach((k) => keys.add(k)));
        const cols = preferred.filter((c) => keys.has(c));
        keys.forEach((k) => {
            if (!cols.includes(k) && !isMetaColumn(k)) cols.push(k);
        });
        return cols;
    }

    function huaweiCanEdit(rows) {
        return vendor === 'huawei' && rows.length > 0;
    }

    function huaweiTiltColumnLabel(col) {
        if (vendor !== 'huawei') return col;
        if (col === 'Tilt' || isHuaweiTiltColumn(col)) return 'Tilt (MML)';
        if (col === 'Actual Tilt' || normalizeKey(col).includes('actualtilt')) return 'Actual Tilt (MML)';
        return col;
    }

    function huaweiTiltHint(value) {
        const text = String(value || '').trim();
        if (!text || text.includes('.') || !/^-?\d+$/.test(text)) return '';
        const deg = Number(text) / 10;
        return Number.isFinite(deg) ? `≈ ${deg}°` : '';
    }

    /** Degrees hint for the editable tilt cell, in the unit the vendor uses. */
    function tiltInputHint(value) {
        if (vendor === 'huawei') return huaweiTiltHint(value);
        const scale = nokiaAngleScale(currentRows);
        if (scale === 1) return '';
        const deg = tiltToDegrees(value, scale);
        return Number.isFinite(deg) ? `≈ ${Math.round(deg * 10) / 10}°` : '';
    }

    function cellDisplayValue(row, col, editCol) {
        if (col === SECTOR_COLUMN) {
            const sector = rowSector(row);
            return sector ? sectorLabelFor(sector) : '—';
        }
        const raw = vendor === 'huawei' ? resolveHuaweiField(row, col) : (row[col] ?? '');
        if (col === editCol && vendor === 'huawei') {
            return resolveHuaweiField(row, 'Tilt') || resolveHuaweiField(row, 'Actual Tilt') || raw;
        }
        return raw == null ? '' : raw;
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

    function visibleRows(editCol) {
        let rows = currentRows.map((row, index) => ({ row, index }));
        if (sectorFilter) {
            // Never hide a row with an unapplied edit — losing sight of a pending
            // tilt change right before "Apply changes" is the dangerous case.
            const matches = ({ row, index }) => (
                pendingChanges.has(rowKey(row, index))
                || (sectorFilter === UNMAPPED_SECTOR ? !rowSector(row) : rowSector(row) === sectorFilter)
            );
            rows = rows.filter(matches);
        }
        if (tableFilter) {
            const term = tableFilter.toLowerCase();
            const columns = displayColumns(currentRows);
            rows = rows.filter(({ row }) => (
                columns.some((col) => String(cellDisplayValue(row, col, editCol)).toLowerCase().includes(term))
                || Object.entries(row).some(([key, value]) => (
                    !isMetaColumn(key) && String(value ?? '').toLowerCase().includes(term)
                ))
            ));
        }
        if (sortState.col) {
            const col = sortState.col;
            const dir = sortState.dir;
            // Tie-break on the server's canonical order so equal cells never swap
            // places between renders.
            rows.sort((left, right) => {
                const diff = compareValues(
                    cellDisplayValue(left.row, col, editCol),
                    cellDisplayValue(right.row, col, editCol),
                );
                return diff !== 0 ? dir * diff : left.index - right.index;
            });
        }
        return rows;
    }

    function updateTableMeta(shown, total) {
        if (!tableMeta) return;
        if (!total) {
            tableMeta.textContent = '';
            return;
        }
        const parts = [`${shown} of ${total}`];
        parts.push(
            sortState.col
                ? `sorted by ${sortState.col} ${sortState.dir > 0 ? '↑' : '↓'}`
                : 'default order (device/sector)',
        );
        if (sectorFilter) {
            parts.push(
                sectorFilter === UNMAPPED_SECTOR
                    ? 'unmapped RETs only'
                    : `sector ${sectorLabelFor(sectorFilter)} only`,
            );
            if (pendingChanges.size) parts.push('edited rows pinned');
        }
        if (tableFilter) {
            parts.push('filtered');
        }
        tableMeta.textContent = parts.join(' · ');
    }

    function renderTable(rows) {
        if (Array.isArray(rows)) {
            currentRows = rows;
            pendingChanges.clear();
        }
        const thead = retTable.querySelector('thead');
        const tbody = retTable.querySelector('tbody');
        thead.innerHTML = '';
        tbody.innerHTML = '';

        if (!currentRows.length) {
            emptyState.hidden = false;
            retTable.hidden = true;
            saveBtn.hidden = true;
            if (exportBtn) exportBtn.disabled = true;
            updateTableMeta(0, 0);
            return;
        }

        emptyState.hidden = true;
        retTable.hidden = false;
        if (exportBtn) exportBtn.disabled = false;
        const columns = displayColumns(currentRows);
        const editCol = resolveEditColumn(columns.filter((col) => col !== SECTOR_COLUMN));
        const hasEditColumn = vendor === 'huawei'
            ? huaweiCanEdit(currentRows) && (columns.includes(editCol) || resolveHuaweiField(currentRows[0], 'Tilt') !== '')
            : columns.includes(editCol);

        const headRow = document.createElement('tr');
        columns.forEach((col) => {
            const th = document.createElement('th');
            th.className = 'sortable-th';
            th.dataset.col = col;
            const label = huaweiTiltColumnLabel(col);
            let marker = '';
            if (sortState.col === col) {
                marker = sortState.dir > 0 ? ' ↑' : ' ↓';
            }
            th.textContent = `${label}${marker}`;
            if (col === SECTOR_COLUMN) {
                th.title = vendor === 'huawei'
                    ? 'Sector this RETSUBUNIT drives (Actual Sector ID / subunit name). Click to sort.'
                    : 'Sector this RETU drives (sectorID). Click to sort.';
            } else if (col === editCol && cmWriteAllowed && hasEditColumn) {
                th.title = vendor === 'huawei'
                    ? 'Editable — U2020 MML 0.1° units (40 = 4.0°). Click header to sort.'
                    : 'Editable — RETU.angle. Click header to sort.';
            } else {
                th.title = 'Click to sort. Click again to reverse.';
            }
            th.tabIndex = 0;
            th.addEventListener('click', () => {
                if (sortState.col === col) {
                    sortState.dir = -sortState.dir;
                } else {
                    sortState = { col, dir: 1 };
                }
                renderTable();
            });
            th.addEventListener('keydown', (ev) => {
                if (ev.key === 'Enter' || ev.key === ' ') {
                    ev.preventDefault();
                    th.click();
                }
            });
            headRow.appendChild(th);
        });
        if (cmWriteAllowed && hasEditColumn) {
            const actionTh = document.createElement('th');
            actionTh.textContent = 'Action';
            headRow.appendChild(actionTh);
        }
        thead.appendChild(headRow);

        const shown = visibleRows(editCol);
        const selectedSector = hologram ? hologram.getSelected() : null;
        shown.forEach(({ row, index }) => {
            const tr = document.createElement('tr');
            const key = rowKey(row, index);
            const sector = rowSector(row);
            tr.dataset.rowKey = key;
            tr.dataset.sector = sector;
            if (sector && selectedSector === sector) tr.classList.add('row-sector-active');
            columns.forEach((col) => {
                const td = document.createElement('td');
                const value = cellDisplayValue(row, col, editCol);
                const isTiltCell = col === editCol;
                if (isTiltCell && cmWriteAllowed && hasEditColumn) {
                    const pending = pendingChanges.get(key);
                    const input = document.createElement('input');
                    input.type = 'text';
                    input.className = 'tilt-input';
                    input.value = pending ? pending.value : value;
                    input.placeholder = vendor === 'huawei' ? 'e.g. 40 (=4°)' : '';
                    input.title = tiltInputHint(input.value);
                    input.dataset.original = String(value);
                    if (pending && pending.value !== String(value)) {
                        tr.classList.add('row-changed');
                    }
                    input.addEventListener('input', () => {
                        input.title = tiltInputHint(input.value);
                        if (input.value !== input.dataset.original) {
                            pendingChanges.set(key, { row, index, value: input.value });
                            tr.classList.add('row-changed');
                        } else {
                            pendingChanges.delete(key);
                            tr.classList.remove('row-changed');
                        }
                        saveBtn.hidden = !cmWriteAllowed || pendingChanges.size === 0;
                        renderHologram();
                    });
                    td.appendChild(input);
                } else {
                    td.textContent = value;
                    if (col === SECTOR_COLUMN) td.className = 'sector-cell';
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

        updateTableMeta(shown.length, currentRows.length);
        saveBtn.hidden = !cmWriteAllowed || !hasEditColumn || pendingChanges.size === 0;
    }

    function applyLocalRowUpdate(row, index, value) {
        const editCol = resolveEditColumn(vendorColumns(currentRows));
        if (vendor === 'nokia') {
            row.angle = value;
            if (editCol) row[editCol] = value;
        } else {
            const tiltKey = Object.keys(row).find((k) => isHuaweiTiltColumn(k)) || 'Tilt';
            row[tiltKey] = value;
        }
        const key = rowKey(row, index);
        pendingChanges.delete(key);
    }

    function applyLocalPendingUpdates() {
        pendingChanges.forEach(({ row, index, value }) => {
            applyLocalRowUpdate(row, index, value);
        });
        pendingChanges.clear();
        renderTable();
        renderHologram();
    }

    function nokiaUpdatePayload(row, angle, ne) {
        return {
            dist_name: row.DN || row.dn,
            configDN: row.configDN || row.configDn || '',
            runtime_DN: row.runtime_DN || '',
            site_id: ne?.site_id || '',
            angle,
            mo_class: nokiaMoClass || undefined,
        };
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
                const res = await fetch('/api/ret-management/nokia/retu/update', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        mo_class: nokiaMoClass || undefined,
                        site_id: ne.site_id,
                        updates: [nokiaUpdatePayload(row, tiltValue, ne)],
                        wait: true,
                    }),
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.error || 'Nokia update failed');
                showCredentialFallbackNotice(data);
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
                showCredentialFallbackNotice(data);
            }
            setStatus(loadStatus, 'Change applied successfully', 'ok');
            applyLocalRowUpdate(row, index, tiltValue);
            renderTable();
            renderHologram();
        } catch (err) {
            setStatus(loadStatus, err.message, 'error');
        } finally {
            saveBtn.disabled = false;
        }
    }

    function showCredentialFallbackNotice(data) {
        if (!data || (!data.credential_fallback && !data.credential_missing)) return;
        const notice = data.credential_notice
            || (data.credential_missing
                ? 'You have not configured personal vendor credentials. The shared service account was used and an administrator has been notified.'
                : 'Your personal vendor credentials could not complete this action. The shared service account was used instead.');
        setStatus(loadStatus, notice, 'warn');
        if (typeof window.showToast === 'function') {
            window.showToast(notice, 'warn', 8000);
        } else {
            window.alert(notice);
        }
    }

    function mergeResponseWarnings(data, existingWarnings) {
        const warnings = Array.isArray(existingWarnings) ? [...existingWarnings] : [];
        if (data && (data.credential_fallback || data.credential_missing) && data.credential_notice) {
            warnings.push(data.credential_notice);
        }
        return warnings;
    }

    async function exportExcelReport() {
        if (!currentRows.length) {
            setStatus(loadStatus, 'Load RET data before exporting', 'error');
            return;
        }
        const ne = selectedNe();
        const columns = displayColumns(currentRows);
        const editCol = resolveEditColumn(columns);
        const visible = visibleRows(editCol);
        if (!visible.length) {
            setStatus(loadStatus, 'No rows match the current filter', 'error');
            return;
        }

        const exportRows = visible.map(({ row }) => {
            const out = {};
            columns.forEach((col) => {
                out[col] = cellDisplayValue(row, col, editCol);
            });
            return out;
        });
        const columnLabels = {};
        columns.forEach((col) => {
            columnLabels[col] = huaweiTiltColumnLabel(col);
        });

        if (exportBtn) exportBtn.disabled = true;
        setStatus(loadStatus, 'Preparing Excel report…');
        try {
            const res = await fetch('/api/ret-management/export/excel', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    vendor,
                    site_id: ne?.site_id || '',
                    ne_label: ne?.label || '',
                    ne_name: ne?.ne_name || '',
                    mo_class: nokiaMoClass || '',
                    columns,
                    column_labels: columnLabels,
                    rows: exportRows,
                    table_filter: tableFilter,
                    total_rows: currentRows.length,
                    exported_rows: exportRows.length,
                }),
            });
            if (!res.ok) {
                let message = 'Excel export failed';
                try {
                    const data = await res.json();
                    message = data.error || message;
                } catch (_) {
                    /* binary or empty body */
                }
                throw new Error(message);
            }
            const blob = await res.blob();
            const disposition = res.headers.get('Content-Disposition') || '';
            const match = disposition.match(/filename="?([^";]+)"?/i);
            const filename = match ? match[1] : `RET_${vendor}_${Date.now()}.xlsx`;
            const url = URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = url;
            link.download = filename;
            document.body.appendChild(link);
            link.click();
            link.remove();
            URL.revokeObjectURL(url);
            setStatus(loadStatus, `Downloaded ${exportRows.length} row(s) to Excel`, 'ok');
        } catch (err) {
            setStatus(loadStatus, err.message, 'error');
        } finally {
            if (exportBtn) exportBtn.disabled = !currentRows.length;
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

        // A reload of the same NE keeps the sort, the filters and the sector
        // selection; only a different NE resets the view.
        const key = neKey(ne);
        const sameNe = key === loadedNeKey;
        if (!sameNe) {
            sortState = { col: null, dir: 1 };
            tableFilter = '';
            sectorFilter = '';
            if (tableFilterInput) tableFilterInput.value = '';
            if (hologram) hologram.setSelected(null);
        }
        if (pendingChanges.size) {
            const proceed = window.confirm(
                `${pendingChanges.size} unapplied tilt edit(s) will be discarded by this reload. Continue?`,
            );
            if (!proceed) return;
        }
        loadedNeKey = key;
        if (!sameNe || !siteLayout) {
            loadSiteLayout(ne);
        }

        if (typeof setButtonLoading === 'function') {
            setButtonLoading(loadBtn, true, 'Loading…');
            setButtonLoading(reloadBtn, true, 'Loading…');
        }
        setStatus(loadStatus, 'Loading RET data…');
        resultsPanel.hidden = false;
        try {
            let url;
            if (vendor === 'nokia') {
                url = `/api/ret-management/nokia/retu?site_id=${encodeURIComponent(ne.site_id)}&conf_id=${LIVE_CONF_ID}`;
            } else {
                url = `/api/ret-management/huawei/rets?site_id=${encodeURIComponent(ne.site_id)}`;
                if (ne.ne_name) url += `&ne_name=${encodeURIComponent(ne.ne_name)}`;
            }
            const res = await fetch(url);
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || 'Failed to load RET data');
            showCredentialFallbackNotice(data);
            serverColumns = data.columns || [];
            nokiaMoClass = data.mo_class || '';
            showWarnings(mergeResponseWarnings(data, data.warnings));
            renderTable(data.rows || []);
            renderHologram();
            const moLabel = nokiaMoClass ? ` [${nokiaMoClass}]` : '';
            setStatus(loadStatus, `Loaded ${(data.rows || []).length} record(s) for ${ne.label}${moLabel}`, 'ok');
        } catch (err) {
            renderTable([]);
            renderHologram();
            setStatus(loadStatus, err.message, 'error');
        } finally {
            if (typeof setButtonLoading === 'function') {
                setButtonLoading(loadBtn, false);
                setButtonLoading(reloadBtn, false);
            }
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
                    updates.push(nokiaUpdatePayload(row, value, ne));
                });
                const res = await fetch('/api/ret-management/nokia/retu/update', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        updates,
                        wait: true,
                        mo_class: nokiaMoClass || undefined,
                        site_id: ne.site_id,
                    }),
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.error || 'Nokia update failed');
                showCredentialFallbackNotice(data);
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
                    showCredentialFallbackNotice(data);
                }
            }
            setStatus(loadStatus, 'Changes applied successfully', 'ok');
            applyLocalPendingUpdates();
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
    if (exportBtn) exportBtn.addEventListener('click', exportExcelReport);
    saveBtn.addEventListener('click', saveChanges);
    if (tableFilterInput) {
        tableFilterInput.addEventListener('input', () => {
            tableFilter = tableFilterInput.value.trim();
            renderTable();
        });
    }

    // Selecting a site draws its hologram straight away, before the RET read.
    // Debounced because arrowing through the NE list fires `change` per row.
    let layoutTimer;
    neSelect.addEventListener('change', () => {
        clearTimeout(layoutTimer);
        layoutTimer = setTimeout(() => {
            const ne = selectedNe();
            if (!ne) return;
            if (neKey(ne) === loadedNeKey && siteLayout) return;
            loadSiteLayout(ne);
        }, 250);
    });

    if (holoResetBtn) {
        holoResetBtn.addEventListener('click', () => {
            if (hologram) hologram.reset();
            if (holoPitch) holoPitch.value = '0';
            if (hologram) hologram.setPitch(0);
        });
    }
    if (holoPitch) {
        holoPitch.addEventListener('input', () => {
            if (hologram) hologram.setPitch(Number(holoPitch.value) / 100);
        });
    }

    updateVendorUi();
    fetchDefaults();
})();
