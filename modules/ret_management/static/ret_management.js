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
    /** Technologies currently drawn on the hologram (empty = none). */
    let activeTechs = new Set();
    let techFilterInitialized = false;
    /** Analytical pattern detail — isolates one sector (main + 2 sides + back). */
    let patternDetailEnabled = false;
    /** Always live network (NetAct conf_id=1). */
    const LIVE_CONF_ID = 1;
    const TECH_ORDER = [
        '2G', '3G', '4G', '4G-TDD',
        '4G-AAU-Left', '4G-AAU-Right', '4G-AAU', '4G-L1800+',
        'Not Used',
        '4G-FDD', '5G',  // metadata inventory fallbacks when no RET name
    ];

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
            if (typeof hologram.setAntennaFacings === 'function') {
                hologram.setAntennaFacings([]);
            }
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
     * row drives. Nokia from `sectorID` (D4-L1800 / F1_F2-A1-…), Huawei from
     * Subunit Name (`1020_A-2G-L900`) — joined to metadata azimuth by sector key.
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

    /** AAU Left/Right split a 60° sector into two 30° half-beams. */
    function techBeamwidth(tech) {
        if (tech === '4G-AAU-Left' || tech === '4G-AAU-Right') return 30;
        return 60;
    }

    /** Offset Left/Right half-beams from the sector centre azimuth (±15°). */
    function techAzimuthOffset(tech) {
        if (tech === '4G-AAU-Left') return -15;
        if (tech === '4G-AAU-Right') return 15;
        return 0;
    }

    function applyAzimuthOffset(baseAzimuth, tech) {
        if (!Number.isFinite(baseAzimuth)) return baseAzimuth;
        const offset = techAzimuthOffset(tech);
        if (!offset) return baseAzimuth;
        return ((baseAzimuth + offset) % 360 + 360) % 360;
    }

    /** Mean of finite tilt samples — hologram must track the table RET degrees. */
    function meanTilt(values) {
        const nums = (values || []).filter((v) => Number.isFinite(v));
        if (!nums.length) return NaN;
        return nums.reduce((sum, v) => sum + v, 0) / nums.length;
    }

    /** Per-sector × technology RET state, merged onto inventory geometry. */
    function computeSectors() {
        const scale = vendor === 'nokia' ? nokiaAngleScale(currentRows) : 1;
        const perLobe = new Map();
        let unmappedCount = 0;
        let unmappedEdits = 0;

        function lobeBucket(sectorKey, tech) {
            const techKey = tech || 'Unknown';
            return `${sectorKey}::${techKey}`;
        }

        currentRows.forEach((row, index) => {
            const key = rowSector(row);
            const tech = String(row._ret_tech || '').trim();
            const pending = pendingChanges.get(rowKey(row, index));
            const committed = tiltToDegrees(committedTiltRaw(row), scale);
            const current = pending ? tiltToDegrees(pending.value, scale) : committed;
            const edited = Boolean(pending) && String(pending.value).trim() !== String(committedTiltRaw(row)).trim();
            if (!key) {
                unmappedCount += 1;
                if (edited) unmappedEdits += 1;
                return;
            }
            const bucket = lobeBucket(key, tech);
            if (!perLobe.has(bucket)) {
                perLobe.set(bucket, {
                    sectorKey: key,
                    tech: tech || '',
                    retCount: 0,
                    current: [],
                    committed: [],
                    edited: false,
                    azimuths: [],
                });
            }
            const entry = perLobe.get(bucket);
            entry.retCount += 1;
            if (Number.isFinite(current)) entry.current.push(current);
            if (Number.isFinite(committed)) entry.committed.push(committed);
            if (edited) entry.edited = true;
            const bearing = Number(row._ret_azimuth);
            if (Number.isFinite(bearing)) entry.azimuths.push(bearing);
        });

        const layoutSectors = siteLayout?.sectors || [];
        const lobes = [];
        const seen = new Set();

        layoutSectors.forEach((sector) => {
            const metaTechs = (sector.technologies || []).slice();
            const retTechs = [];
            perLobe.forEach((entry) => {
                if (entry.sectorKey === sector.key && entry.tech && !retTechs.includes(entry.tech)) {
                    retTechs.push(entry.tech);
                }
            });
            // RET-named techs first; fall back to inventory techs when no RET rows yet.
            let techs = retTechs.length ? retTechs.slice() : metaTechs.slice();
            if (!techs.length) techs = [''];
            techs.sort((a, b) => {
                const ai = TECH_ORDER.indexOf(a);
                const bi = TECH_ORDER.indexOf(b);
                return (ai < 0 ? 99 : ai) - (bi < 0 ? 99 : bi) || a.localeCompare(b);
            });

            techs.forEach((tech, techIndex) => {
                const bucket = lobeBucket(sector.key, tech);
                seen.add(bucket);
                const ret = perLobe.get(bucket);
                const retAzimuth = ret && ret.azimuths.length ? ret.azimuths[0] : null;
                const hasMetaAz = Number.isFinite(sector.azimuth);
                const azimuthSource = hasMetaAz
                    ? (sector.azimuth_source || 'metadata')
                    : (Number.isFinite(retAzimuth) ? 'RET antBearing' : sector.azimuth_source);
                const metaEtilt = Number.isFinite(sector.electrical_tilt) ? sector.electrical_tilt : NaN;
                const tiltDeg = ret && ret.current.length
                    ? meanTilt(ret.current)
                    : metaEtilt;
                const baseline = ret && ret.committed.length ? meanTilt(ret.committed) : NaN;
                const tiltSpread = ret && ret.current.length > 1
                    ? [Math.min(...ret.current), Math.max(...ret.current)]
                    : null;
                const techLabel = tech || 'Unknown';
                const baseAzimuth = hasMetaAz ? sector.azimuth : retAzimuth;
                lobes.push({
                    key: bucket,
                    sectorKey: sector.key,
                    label: `${sector.label} · ${techLabel}`,
                    technology: techLabel,
                    technologies: tech ? [tech] : [],
                    techIndex,
                    azimuth: applyAzimuthOffset(baseAzimuth, tech),
                    azimuthSource,
                    beamwidth: techBeamwidth(tech),
                    height: sector.height,
                    mechanicalTilt: sector.mechanical_tilt,
                    bands: sector.bands || [],
                    cellCount: (sector.cells || []).filter((c) => !tech || c.technology === tech).length
                        || (tech ? 0 : (sector.cell_count || 0)),
                    retCount: ret ? ret.retCount : 0,
                    tiltDeg,
                    baselineTiltDeg: baseline,
                    tiltSpread: tiltSpread && tiltSpread[0] !== tiltSpread[1] ? tiltSpread : null,
                    edited: Boolean(ret && ret.edited),
                });
            });
        });

        perLobe.forEach((entry, bucket) => {
            if (seen.has(bucket)) return;
            if (!entry.azimuths.length) {
                unmappedCount += entry.retCount;
                if (entry.edited) unmappedEdits += 1;
                return;
            }
            const techLabel = entry.tech || 'Unknown';
            lobes.push({
                key: bucket,
                sectorKey: entry.sectorKey,
                label: `${sectorLabelFor(entry.sectorKey)} · ${techLabel}`,
                technology: techLabel,
                technologies: entry.tech ? [entry.tech] : [],
                techIndex: 0,
                azimuth: applyAzimuthOffset(entry.azimuths[0], entry.tech),
                azimuthSource: 'RET antBearing (not in inventory)',
                beamwidth: techBeamwidth(entry.tech),
                height: siteLayout?.site?.antenna_height,
                mechanicalTilt: NaN,
                bands: [],
                cellCount: 0,
                retCount: entry.retCount,
                tiltDeg: meanTilt(entry.current),
                baselineTiltDeg: meanTilt(entry.committed),
                tiltSpread: entry.current.length > 1
                    && Math.min(...entry.current) !== Math.max(...entry.current)
                    ? [Math.min(...entry.current), Math.max(...entry.current)]
                    : null,
                edited: entry.edited,
            });
        });

        lobes.sort((a, b) => {
            const aNum = /^\d+$/.test(a.sectorKey) ? Number(a.sectorKey) : Number.MAX_SAFE_INTEGER;
            const bNum = /^\d+$/.test(b.sectorKey) ? Number(b.sectorKey) : Number.MAX_SAFE_INTEGER;
            const techA = TECH_ORDER.indexOf(a.technology);
            const techB = TECH_ORDER.indexOf(b.technology);
            return aNum - bNum
                || (techA < 0 ? 99 : techA) - (techB < 0 ? 99 : techB)
                || a.key.localeCompare(b.key);
        });

        const availableTechs = [];
        lobes.forEach((lobe) => {
            const tech = lobe.technology;
            if (tech && tech !== 'Unknown' && !availableTechs.includes(tech)) availableTechs.push(tech);
        });
        availableTechs.sort((a, b) => {
            const ai = TECH_ORDER.indexOf(a);
            const bi = TECH_ORDER.indexOf(b);
            return (ai < 0 ? 99 : ai) - (bi < 0 ? 99 : bi) || a.localeCompare(b);
        });
        if (!techFilterInitialized && availableTechs.length) {
            activeTechs = new Set(availableTechs);
            techFilterInitialized = true;
        } else if (availableTechs.length) {
            // Drop techs that disappeared; keep user toggles for the rest.
            const next = new Set();
            availableTechs.forEach((tech) => {
                if (activeTechs.has(tech) || !techFilterInitialized) next.add(tech);
            });
            // If everything was toggled off after a reload that introduced new techs only,
            // leave activeTechs as-is (user may have cleared all intentionally).
            if (next.size || activeTechs.size === 0) activeTechs = next.size ? next : activeTechs;
        }

        return {
            sectors: lobes,
            availableTechs,
            unmappedCount,
            unmappedEdits,
            scale,
        };
    }

    function ensureHologram() {
        if (hologram || !holoCanvas || !window.RetHologram) return hologram;
        hologram = window.RetHologram.create(holoCanvas, {
            onSelectSector(sectorKey) {
                sectorFilter = sectorKey || '';
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
        const bySector = new Map();
        (computed.sectors || []).forEach((lobe) => {
            const key = lobe.sectorKey || lobe.key;
            if (!bySector.has(key)) {
                bySector.set(key, {
                    key,
                    label: sectorLabelFor(key),
                    azimuth: lobe.azimuth,
                    tiltDeg: lobe.tiltDeg,
                    mechanicalTilt: lobe.mechanicalTilt,
                    retCount: 0,
                    cellCount: 0,
                    edited: false,
                    technologies: [],
                });
            }
            const agg = bySector.get(key);
            agg.retCount += lobe.retCount || 0;
            agg.cellCount += lobe.cellCount || 0;
            if (lobe.edited) agg.edited = true;
            if (Number.isFinite(lobe.tiltDeg)) {
                agg.tiltDeg = Number.isFinite(agg.tiltDeg)
                    ? Math.max(agg.tiltDeg, lobe.tiltDeg)
                    : lobe.tiltDeg;
            }
            if (Number.isFinite(lobe.mechanicalTilt)) {
                agg.mechanicalTilt = Number.isFinite(agg.mechanicalTilt)
                    ? Math.max(agg.mechanicalTilt, lobe.mechanicalTilt)
                    : lobe.mechanicalTilt;
            }
            (lobe.technologies || []).forEach((tech) => {
                if (!agg.technologies.includes(tech)) agg.technologies.push(tech);
            });
        });
        Array.from(bySector.values()).forEach((sector) => {
            const chip = document.createElement('button');
            chip.type = 'button';
            chip.className = 'holo-chip';
            if (sector.edited) chip.classList.add('edited');
            if (selected === sector.key) chip.classList.add('active');
            const retTilt = Number.isFinite(sector.tiltDeg)
                ? window.RetHologram.formatDegrees(sector.tiltDeg)
                : '—';
            const eff = window.RetHologram.effectiveTiltDeg
                ? window.RetHologram.effectiveTiltDeg(sector.tiltDeg, sector.mechanicalTilt)
                : sector.tiltDeg;
            const tiltLabel = Number.isFinite(eff)
                ? `eff ${window.RetHologram.formatDegrees(eff)}`
                : 'tilt —';
            [
                ['holo-chip-key', `S${sector.label}`],
                ['holo-chip-az', window.RetHologram.formatDegrees(sector.azimuth)],
                ['holo-chip-tilt', tiltLabel],
            ].forEach(([className, text]) => {
                const span = document.createElement('span');
                span.className = className;
                span.textContent = text;
                chip.appendChild(span);
            });
            const mechLabel = Number.isFinite(sector.mechanicalTilt)
                ? window.RetHologram.formatDegrees(sector.mechanicalTilt)
                : '—';
            chip.title = `${sector.retCount} RET row(s), ${sector.cellCount} cell(s)`
                + (sector.technologies.length ? ` · ${sector.technologies.join(', ')}` : '')
                + ` · RET ${retTilt} · mech ${mechLabel} ×3 → ${tiltLabel}`;
            chip.addEventListener('click', () => {
                let next = selected === sector.key ? null : sector.key;
                // Pattern detail isolates one sector — keep a focus sector selected.
                if (patternDetailEnabled && !next) next = sector.key;
                if (hologram) hologram.setSelected(next);
                sectorFilter = next || '';
                renderTable();
                renderHologramRail();
                if (patternDetailEnabled) renderHologram();
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
                ? 'Subunit Name did not match {SiteId}_{Sector}-… for these RETSUBUNITs'
                : 'These RETU rows carry no parseable sectorID';
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
        const techs = computed.availableTechs || [];
        const buttons = techs.map((tech) => {
            const colour = window.RetHologram.TECH_COLORS[tech] || [110, 196, 240];
            const on = activeTechs.has(tech);
            return `<button type="button" class="holo-tech-toggle${on ? ' active' : ''}" data-tech="${escapeHtml(tech)}" `
                + `aria-pressed="${on ? 'true' : 'false'}" title="Toggle ${escapeHtml(tech)} lobes">`
                + `<i style="background: rgba(${colour[0]}, ${colour[1]}, ${colour[2]}, ${on ? '0.95' : '0.25'})"></i>`
                + `${escapeHtml(tech)}</button>`;
        });
        const actions = techs.length
            ? '<button type="button" class="holo-tech-all" data-action="all">All</button>'
                + '<button type="button" class="holo-tech-all" data-action="none">None</button>'
            : '';
        holoLegend.innerHTML = [
            '<div class="holo-tech-bar">',
            '<span class="holo-tech-label">Technologies</span>',
            ...buttons,
            actions,
            '</div>',
            `<button type="button" class="holo-tech-toggle holo-pattern-toggle${patternDetailEnabled ? ' active' : ''}" `
                + `data-action="pattern" aria-pressed="${patternDetailEnabled ? 'true' : 'false'}" `
                + 'title="Analytical pattern (main + 2 side + back). Isolates the selected sector.">'
                + 'Pattern detail</button>',
            '<span class="holo-legend-item"><i class="edited"></i>edited (mesh ghost = committed tilt)</span>',
            '<p class="holo-legend-note">Pointing uses RET + 3× mechanical (metadata). '
                + 'Reach clamped 100–1000 m, then band. Pattern detail = main + 2 sides (~20% @ ±90°) '
                + '+ back (~55% @ 180°) and turns other sectors off — click a sector chip to switch focus; '
                + 'tech toggles still compare techs on that sector.</p>',
        ].join('');
        holoLegend.querySelectorAll('.holo-tech-toggle').forEach((btn) => {
            btn.addEventListener('click', () => {
                if (btn.dataset.action === 'pattern') {
                    patternDetailEnabled = !patternDetailEnabled;
                    const holo = ensureHologram();
                    if (patternDetailEnabled) {
                        // Isolate one sector — pick current selection or first available.
                        let focus = holo ? holo.getSelected() : null;
                        if (!focus) {
                            const first = (computed.sectors || []).find((l) => l.sectorKey);
                            focus = first ? first.sectorKey : null;
                        }
                        if (focus && holo) {
                            holo.setSelected(focus);
                            sectorFilter = focus;
                        }
                    }
                    if (holo && typeof holo.setPatternDetail === 'function') {
                        holo.setPatternDetail(patternDetailEnabled);
                    }
                    renderTable();
                    renderHologram();
                    return;
                }
                const tech = btn.dataset.tech;
                if (activeTechs.has(tech)) activeTechs.delete(tech);
                else activeTechs.add(tech);
                renderHologram();
            });
        });
        holoLegend.querySelectorAll('.holo-tech-all').forEach((btn) => {
            btn.addEventListener('click', () => {
                if (btn.dataset.action === 'all') {
                    activeTechs = new Set(techs);
                } else {
                    activeTechs = new Set();
                }
                renderHologram();
            });
        });
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
        const layoutFacings = (siteLayout?.sectors || [])
            .filter((s) => Number.isFinite(s.azimuth))
            .map((s) => ({ key: s.key, azimuth: s.azimuth, label: s.label }));
        // RET-only sectors (no inventory row) still get a panel from their bearing.
        const facingKeys = new Set(layoutFacings.map((f) => f.key));
        (computed.sectors || []).forEach((lobe) => {
            const key = lobe.sectorKey;
            if (!key || facingKeys.has(key) || !Number.isFinite(lobe.azimuth)) return;
            let az = lobe.azimuth;
            // Undo AAU half-beam offset so the panel faces the sector centre.
            if (lobe.technology === '4G-AAU-Left') az = (az + 15 + 360) % 360;
            else if (lobe.technology === '4G-AAU-Right') az = (az - 15 + 360) % 360;
            layoutFacings.push({ key, azimuth: az, label: lobe.label || key });
            facingKeys.add(key);
        });
        if (typeof holo.setAntennaFacings === 'function') {
            holo.setAntennaFacings(layoutFacings);
        }
        if (typeof holo.setPatternDetail === 'function') {
            holo.setPatternDetail(patternDetailEnabled);
        }
        const focusSector = patternDetailEnabled && holo.getSelected
            ? holo.getSelected()
            : null;
        const visible = computed.sectors.filter((lobe) => {
            if (!Number.isFinite(lobe.azimuth)) return false;
            if (patternDetailEnabled && focusSector && lobe.sectorKey !== focusSector) {
                return false;
            }
            const tech = lobe.technology;
            if (!tech || tech === 'Unknown') {
                return (computed.availableTechs || []).length > 0
                    && (computed.availableTechs || []).every((t) => activeTechs.has(t));
            }
            return activeTechs.has(tech);
        });
        holo.setSectors(visible);
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
            const sectorCount = new Set(computed.sectors.map((l) => l.sectorKey)).size;
            bits.push(`${sectorCount} sector(s)`);
            bits.push(`${visible.length}/${computed.sectors.length} lobe(s)`);
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
                    ? 'Sector from Subunit Name ({SiteId}_{Sector}-…). Click to sort.'
                    : 'Sector from sectorID (e.g. D4-L1800). Click to sort.';
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
            techFilterInitialized = false;
            activeTechs = new Set();
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
            techFilterInitialized = false;
            activeTechs = new Set();
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
            if (holoPitch) holoPitch.value = String(window.RetHologram.DEFAULT_PITCH_DEG || 30);
            if (hologram) hologram.setPitch(Number(holoPitch.value));
        });
    }
    if (holoPitch) {
        holoPitch.value = String(window.RetHologram && window.RetHologram.DEFAULT_PITCH_DEG || 30);
        holoPitch.addEventListener('input', () => {
            if (hologram) hologram.setPitch(Number(holoPitch.value));
        });
    }

    updateVendorUi();
    fetchDefaults();
})();
