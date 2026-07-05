/**
 * Network Map – Leaflet visualization
 * Sites → sector wedges drawn per cell (azimuth-aligned)
 * Tech filter: All / 2G / 3G / 4G-FDD / 4G-TDD / 5G.
 */

// ─── Constants ───────────────────────────────────────────────────────────────

const TECH_COLORS = {
    '2G-2G':         '#7f8c8d',
    '3G-3G':         '#27ae60',
    '4G-4G':         '#1a5276',
    '4G-4G Intra-eNB': '#1a5276',
    '4G-4G Inter-eNB': '#8e44ad',
    '4G-4G Intra':     '#1a5276',
    '4G-4G Inter':     '#8e44ad',
    '2G':            '#7f8c8d',
    '3G':            '#27ae60',
    '4G-FDD':        '#1a5276',
    '4G-TDD':        '#148f77',
    '5G':            '#9b59b6',
};

const TECH_ORDER = ['2G', '3G', '4G-FDD', '4G-TDD', '5G'];

/** Sort order for cells in the site panel (actual ``technology`` field from API). */
const CELL_TECH_SORT_ORDER = ['2G', '3G', '4G-FDD', '4G-TDD', '5G'];

const DEFAULT_CENTER = [31.9539, 35.9106];   // Amman, Jordan
const DEFAULT_ZOOM   = 10;
const SECTOR_RADIUS_M = 240;                 // wedge radius in metres (was 600; scaled to 0.4×)
const SECTOR_BEAMWIDTH = 65;                 // 3 dB beamwidth in degrees
const _ELEVATION_CACHE = new Map();

/** Zain RanSitesTool site audits (opens tool home — no per-site deep link). */
const SITE_AUDITS_TOOL_URL = 'https://services.jo.zain.com/RanSitesTool/site-audits/';

// Cluster number → Area name  (cluster = Math.floor(site_id / 100))
const CLUSTER_AREA = {
     3: 'East Amman',  13: 'East Amman',  17: 'East Amman',  21: 'East Amman',
    23: 'East Amman',  27: 'East Amman',  48: 'East Amman',  49: 'East Amman',
    50: 'East Amman',  51: 'East Amman',  52: 'East Amman',  54: 'East Amman',
    10: 'East Jordan', 11: 'East Jordan', 19: 'East Jordan', 28: 'East Jordan',
    31: 'East Jordan', 42: 'East Jordan', 43: 'East Jordan', 47: 'East Jordan',
     1: 'South Amman',  6: 'South Amman',  9: 'South Amman', 18: 'South Amman',
    30: 'South Amman', 36: 'South Amman', 38: 'South Amman', 39: 'South Amman',
    53: 'South Amman', 57: 'South Amman', 59: 'South Amman',
     7: 'South Jordan',  8: 'South Jordan', 12: 'South Jordan', 15: 'South Jordan',
    33: 'South Jordan', 41: 'South Jordan', 58: 'South Jordan',
     2: 'West Amman',   5: 'West Amman',  16: 'West Amman',  20: 'West Amman',
    22: 'West Amman',  25: 'West Amman',  26: 'West Amman',  32: 'West Amman',
    35: 'West Amman',  40: 'West Amman',  55: 'West Amman',  56: 'West Amman',
     4: 'North Jordan', 14: 'North Jordan', 24: 'North Jordan', 29: 'North Jordan',
    34: 'North Jordan', 37: 'North Jordan', 44: 'North Jordan', 45: 'North Jordan',
    46: 'North Jordan', 65: 'North Jordan',
};

// ─── State ───────────────────────────────────────────────────────────────────

let map              = null;
let sitesData        = [];
let repeaterData     = [];
let siteMarkers      = [];
let repeaterMarkers  = [];
let repeaterLayer    = null;
let showRepeaters    = false;
let repeatersLoaded  = false;
let _repeaterPinIcon = null;
let sectorLayers     = [];
let activeTech       = 'all';
let lastLoadedScopeKey = '';
let highlightMarkers = [];
let highlightLayers  = [];
let codeSearchTimer  = null;
let activeTechSpecific = 'all';
let selectedSiteId = null;
let selectedNeighborCell = '';
let neighborEnabled = false;
let neighborLinesLayer = null;
let neighborLineData = [];
let mapModule = 'site-explorer';
/** When a site is opened: { site, wedgeCells } for redrawing wedges in Neighbor Explorer. */
let lastNeighborSiteContext = null;
const NEIGHBOR_ONLY_MODE = document.body.classList.contains('neighbor-only-page');

// Map wedge group id -> group payload (cells + site context)
let wedgeGroups = {};

// Coordinate search marker
let coordMarker = null;

// ─── Measure tool state ───────────────────────────────────────────────────────
let measureActive    = false;
let measurePoints    = [];
let measurePtMarkers = [];
let measurePolyline  = null;
let measureDistLabel = null;

const LEFT_PANEL_COLLAPSE_KEY = 'networkMapLeftPanelCollapsed';

function applySavedLeftPanelState() {
    try {
        if (localStorage.getItem(LEFT_PANEL_COLLAPSE_KEY) === '1') {
            const shell = document.getElementById('left-panel-shell');
            const tab = document.getElementById('left-panel-tab');
            if (shell) shell.classList.add('collapsed');
            if (tab) {
                tab.setAttribute('aria-expanded', 'false');
                tab.title = 'Show filters panel';
            }
        }
    } catch (_) { /* storage blocked */ }
}

function toggleMapLeftPanel() {
    const shell = document.getElementById('left-panel-shell');
    const tab = document.getElementById('left-panel-tab');
    if (!shell || !tab) return;
    const collapsed = shell.classList.toggle('collapsed');
    tab.setAttribute('aria-expanded', String(!collapsed));
    tab.title = collapsed ? 'Show filters panel' : 'Hide filters panel';
    try {
        localStorage.setItem(LEFT_PANEL_COLLAPSE_KEY, collapsed ? '1' : '0');
    } catch (_) { /* ignore */ }
    window.setTimeout(() => {
        if (map) map.invalidateSize();
    }, 320);
}

// ─── Initialization ──────────────────────────────────────────────────────────

function initializeMap() {
    // Full-screen KPI modal can survive bfcache restore and block all clicks
    closeKPIModal();

    applySavedLeftPanelState();

    if (map) { map.invalidateSize(); return; }

    map = L.map('network-map', { preferCanvas: true }).setView(DEFAULT_CENTER, DEFAULT_ZOOM);
    neighborLinesLayer = L.layerGroup().addTo(map);
    repeaterLayer = L.layerGroup();
    if (NEIGHBOR_ONLY_MODE) {
        mapModule = 'neighbor-explorer';
        neighborEnabled = true;
        const modSel = document.getElementById('map-module-select');
        if (modSel) modSel.value = 'neighbor-explorer';
        const controls = document.getElementById('neighbor-controls');
        if (controls) controls.style.display = '';
    }

    // Base map styles
    const street = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; OpenStreetMap contributors',
        maxZoom: 19
    });
    const hot = L.tileLayer('https://{s}.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png', {
        attribution: '&copy; OpenStreetMap contributors, Tiles style by Humanitarian OpenStreetMap Team',
        maxZoom: 19
    });
    const topo = L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png', {
        attribution: 'Map data: &copy; OpenStreetMap contributors, SRTM | Map style: &copy; OpenTopoMap',
        maxZoom: 17
    });
    const satellite = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
        attribution: 'Tiles &copy; Esri',
        maxZoom: 19
    });
    const terrain = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Terrain_Base/MapServer/tile/{z}/{y}/{x}', {
        attribution: 'Tiles &copy; Esri',
        maxZoom: 13
    });

    // Default layer
    street.addTo(map);

    // Layer control (top-right)
    L.control.layers(
        {
            'Street': street,
            'Street (HOT)': hot,
            'Topographic': topo,
            'Satellite': satellite,
            'Terrain': terrain
        },
        {},
        { collapsed: false }
    ).addTo(map);

    window.setTimeout(() => { if (map) map.invalidateSize(); }, 200);

    // Load stats + tech buttons, but do NOT load sites until the user applies a filter.
    loadNetworkStats().then(() => {
        _showEmptyState();
        _wireInitialFilterListeners();
        updateNeighborMetricHint();
    });
}

// ─── Stats & tech filter buttons ─────────────────────────────────────────────

async function loadNetworkStats() {
    try {
        const res  = await fetch('/api/map/stats');
        const data = await res.json();
        if (!data.success) return;

        const s = data.stats;
        const sitesCountEl = document.getElementById('sites-count');
        if (sitesCountEl) {
            const repTotal = Number(s.total_repeaters) || 0;
            sitesCountEl.textContent = repTotal
                ? `${s.total_sites} sites · ${repTotal} repeaters`
                : String(s.total_sites);
        }

        if (NEIGHBOR_ONLY_MODE) {
            rebuildNeighborRatSelectForExportVendor();
            await updateTechSpecificFilter();
        }
        buildTechButtons(s.tech_counts || {});
        if (NEIGHBOR_ONLY_MODE && neighborEnabled && map) {
            await loadNetworkSites();
            _neighborPanelIdle();
        }
    } catch (e) {
        console.error('Stats error:', e);
    }
}

/** Neighbor-only page: RAT dropdown drives ``activeTech`` (replaces tech chips). */
const _NEIGHBOR_RAT_OPTIONS_NOKIA = [
    { value: '2G-2G', label: '2G' },
    { value: '3G-3G', label: '3G' },
    { value: '4G-4G', label: '4G' },
];
/** 4G is a single logical relation table; relation_scope flags intra/inter per row. */
const _NEIGHBOR_RAT_OPTIONS_HUAWEI = [
    { value: '2G-2G', label: '2G' },
    { value: '3G-3G', label: '3G' },
    { value: '4G-4G', label: '4G' },
];

function rebuildNeighborRatSelectForExportVendor() {
    if (!NEIGHBOR_ONLY_MODE) return;
    const sel = document.getElementById('neighbor-rat-select');
    if (!sel) return;
    const v = (document.getElementById('vendor-filter')?.value || 'all').toLowerCase();
    const opts = v === 'huawei' ? _NEIGHBOR_RAT_OPTIONS_HUAWEI : _NEIGHBOR_RAT_OPTIONS_NOKIA;
    const prev = sel.value;
    sel.innerHTML = opts.map((o) => `<option value="${o.value}">${escapeHtml(o.label)}</option>`).join('');
    const still = opts.some((o) => o.value === prev);
    sel.value = still ? prev : opts[0].value;
    _syncActiveTechFromNeighborRatSelect();
}

function _syncActiveTechFromNeighborRatSelect() {
    const sel = document.getElementById('neighbor-rat-select');
    if (!sel) return;
    const v = String(sel.value || '').trim();
    activeTech = v || '4G-4G';
    activeTechSpecific = 'all';
}

async function onNeighborRatChange() {
    _syncActiveTechFromNeighborRatSelect();
    clearNeighborOverlay();
    await updateTechSpecificFilter();
    await refreshNeighborWedgePresentation();
}

function buildTechButtons(counts) {
    const container = document.getElementById('tech-filter');
    if (!container) return;

    const opts = NEIGHBOR_ONLY_MODE
        ? [
            { value: '2G-2G', label: '2G-2G', count: Number(counts['2G']) || 0, color: TECH_COLORS['2G'] || '#7f8c8d' },
            { value: '3G-3G', label: '3G-3G', count: Number(counts['3G']) || 0, color: TECH_COLORS['3G'] || '#27ae60' },
            { value: '4G-4G', label: '4G-4G', count: Number(counts['4G-FDD']) || 0, color: TECH_COLORS['4G-4G'] || '#1a5276' },
        ]
        : TECH_ORDER.map((tech) => ({
            value: tech,
            label: tech,
            count: Number(counts[tech]) || 0,
            color: TECH_COLORS[tech] || '#3498db',
        }));

    const total = NEIGHBOR_ONLY_MODE
        ? (Number(counts['2G']) || 0) + (Number(counts['3G']) || 0) + (Number(counts['4G-FDD']) || 0)
        : opts.reduce((sum, o) => sum + o.count, 0);

    let html = `<button class="tech-btn${activeTech === 'all' ? ' active' : ''}" data-tech="all"
                        onclick="setTechFilter('all')">
                  All <span class="tech-count">${total}</span>
                </button>`;

    opts.forEach((opt) => {
        if (!opt.count) return;
        const isActive = activeTech === opt.value ? ' active' : '';
        html += `<button class="tech-btn${isActive}" data-tech="${opt.value}"
                         style="--tc:${opt.color}"
                         onclick="setTechFilter('${opt.value}')">
                   ${opt.label} <span class="tech-count">${opt.count}</span>
                 </button>`;
    });

    container.innerHTML = html;
}

async function setTechFilter(tech) {
    activeTech = tech;
    activeTechSpecific = 'all';
    document.querySelectorAll('.tech-btn').forEach(btn =>
        btn.classList.toggle('active', btn.dataset.tech === tech)
    );
    clearSectorLayers();
    clearHighlights();
    clearNeighborOverlay();
    selectedNeighborCell = '';
    selectedSiteId = null;
    lastNeighborSiteContext = null;
    document.getElementById('site-info-panel').style.display = 'none';

    const codeInput = document.getElementById('cell-code-search');
    if (codeInput) {
        codeInput.placeholder =
            tech === '3G-3G' || tech === '3G' ? 'Scrambling Code...' :
            tech === '4G-4G' ||
            tech === '4G-4G Intra-eNB' || tech === '4G-4G Inter-eNB' ||
            tech === '4G-4G Intra' || tech === '4G-4G Inter' ||
            tech === '4G-FDD' || tech === '4G-TDD' || tech === '5G' ? 'PCI...' :
            tech === '2G-2G' || tech === '2G' ? 'BCCH...' :
            'SC / PCI / BCCH...';
    }
    await updateTechSpecificFilter();
    _onFilterChanged(false, true);
}

// ─── Cell operational state (`activity_status` from map APIs; `status` is alias) ─

/** True when KPI / detail actions are allowed (on-air per vendor rules). */
function cellOperational(c) {
    const raw = c && (c.activity_status != null ? c.activity_status : c.status);
    const s = raw != null ? String(raw).trim().toLowerCase() : '';
    return s === 'active';
}

function escapeHtmlAttr(str) {
    return String(str ?? '')
        .replace(/&/g, '&amp;')
        .replace(/"/g, '&quot;')
        .replace(/</g, '&lt;');
}

function escapeHtml(str) {
    return String(str ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

function elevationCacheKey(lat, lng) {
    return `${Number(lat).toFixed(5)},${Number(lng).toFixed(5)}`;
}

function formatElevation(elevationM) {
    const n = Number(elevationM);
    return Number.isFinite(n) ? `${Math.round(n)} m` : 'unavailable';
}

async function fetchElevation(lat, lng) {
    const la = Number(lat);
    const lo = Number(lng);
    if (!Number.isFinite(la) || !Number.isFinite(lo)) return null;
    const key = elevationCacheKey(la, lo);
    if (_ELEVATION_CACHE.has(key)) return _ELEVATION_CACHE.get(key);
    try {
        const res = await fetch(`/api/elevation?lat=${encodeURIComponent(la)}&lng=${encodeURIComponent(lo)}`, {
            credentials: 'same-origin',
            cache: 'no-store',
        });
        const data = await res.json().catch(() => ({}));
        const val = res.ok && data.success ? data.elevation_m : null;
        _ELEVATION_CACHE.set(key, val);
        return val;
    } catch (_) {
        _ELEVATION_CACHE.set(key, null);
        return null;
    }
}

function fillElevationText(elementId, lat, lng) {
    const el = document.getElementById(elementId);
    if (!el) return;
    el.textContent = 'loading...';
    fetchElevation(lat, lng).then((elev) => {
        const target = document.getElementById(elementId);
        if (target) target.textContent = formatElevation(elev);
    });
}

function _hasArabicText(str) {
    return /[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]/.test(String(str || ''));
}

/** Escape HTML; wrap in RTL span when the value contains Arabic script. */
function escapeHtmlMaybeRtl(str) {
    const raw = String(str ?? '');
    const html = escapeHtml(raw);
    if (!raw.trim() || !_hasArabicText(raw)) return html;
    return `<span class="text-ar" dir="rtl" lang="ar">${html}</span>`;
}

function _repeaterDisplayName(rep) {
    return String(rep?.name || rep?.refcode || rep?.repeater_id || 'Repeater').trim();
}

/** Tooltip when at least one sector wedge has every cell inactive (matches map wedge bins). */
function sitePinTitle(site) {
    const n = Number(site.full_sector_offline_count) || 0;
    if (n <= 0) return site.site_name || '';
    const w = n === 1 ? 'wedge' : 'wedges';
    return `${site.site_name || ''} — ${n} sector ${w} fully deactivated`;
}

/** Leaflet divIcon size/anchor: lat/lng aligns with center of the circular pin. */
function sitePinIconMetrics() {
    const labelH = 12;
    const circle = 26;
    const h = labelH + circle;
    const w = 72;
    return {
        iconSize: [w, h],
        iconAnchor: [w / 2, labelH + circle / 2],
    };
}

function sitePinInnerHtml(site, { highlight = false } = {}) {
    const color = activeTech !== 'all'
        ? (TECH_COLORS[activeTech] || '#3498db')
        : (site.vendor === 'Nokia' ? '#00a3e0' : '#e55300');
    const fullOff = Number(site.full_sector_offline_count) || 0;
    const hasOff = fullOff > 0;
    const hi = highlight ? ' highlight-marker' : '';
    const title = escapeHtmlAttr(sitePinTitle(site));
    const sid = escapeHtml(site.site_id != null ? site.site_id : '');
    return `<div class="site-marker-stack">
              <span class="site-marker-id" aria-hidden="true">${sid}</span>
              <div class="site-marker-inner${hi}${hasOff ? ' site-marker-has-offline' : ''}" style="border-color:${color}" title="${title}">
                <div class="site-icon">📡</div>
                ${hasOff ? '<span class="site-offline-pin-badge" aria-hidden="true"></span>' : ''}
              </div>
            </div>`;
}

// ─── Site enrichment ──────────────────────────────────────────────────────────

function enrichSites(sites) {
    return sites.map(s => {
        const cluster = s.cluster != null ? s.cluster : Math.floor(s.site_id / 100);
        const area = s.area || CLUSTER_AREA[cluster] || 'Unknown';
        return Object.assign({}, s, { cluster, area });
    });
}

// ─── Client-side filtering ────────────────────────────────────────────────────

function applyClientFilters(sites) {
    const vendor  = document.getElementById('vendor-filter').value;
    const area    = document.getElementById('area-filter').value;
    const cluster = document.getElementById('cluster-filter').value;

    return sites.filter(s => {
        if (!NEIGHBOR_ONLY_MODE && vendor !== 'all' && s.vendor !== vendor) return false;
        if (area    !== 'all' && s.area            !== area)    return false;
        if (cluster !== 'all' && String(s.cluster) !== cluster) return false;
        return true;
    });
}

function _zoomToSiteSearchMatches(sites) {
    const term = String(document.getElementById('site-search')?.value || '').trim().toLowerCase();
    if (!term || !map || !Array.isArray(sites) || !sites.length) return;

    const matches = sites.filter((s) => {
        const name = String(s.site_name || '').toLowerCase();
        const sid = String(s.site_id || '').toLowerCase();
        return name.includes(term) || sid.includes(term);
    });
    if (!matches.length) return;

    // Always pick one best match and zoom in, instead of fitting all matches
    // (fitBounds can zoom out too much on broad terms).
    const ranked = matches
        .map((s) => {
            const name = String(s.site_name || '').toLowerCase();
            const sid = String(s.site_id || '').toLowerCase();
            let score = 0;
            if (sid === term || name === term) score += 100;
            if (sid.startsWith(term) || name.startsWith(term)) score += 30;
            score += Math.max(0, 20 - Math.min(name.indexOf(term) >= 0 ? name.indexOf(term) : 999, sid.indexOf(term) >= 0 ? sid.indexOf(term) : 999));
            return { site: s, score };
        })
        .sort((a, b) => b.score - a.score);

    const best = ranked[0]?.site;
    if (!best) return;
    const lat = Number(best.latitude);
    const lng = Number(best.longitude);
    if (Number.isFinite(lat) && Number.isFinite(lng)) {
        map.setView([lat, lng], Math.max(map.getZoom(), 17));
    }
    // Open the matched site context so sector wedges are shown while searching.
    showSiteDetails(best.site_id);
}

/** Map chip (2G/3G/4G-FDD/4G-TDD/5G) vs cell.technology from API. */
function cellMatchesMapTechFilter(c) {
    if (activeTech === 'all') return true;
    const t = String(c.technology || '');
    if (activeTech === '2G-2G') return t === '2G'; // backward compatibility
    if (activeTech === '3G-3G') return t === '3G'; // backward compatibility
    if (
        activeTech === '4G-4G' ||
        activeTech === '4G-4G Intra-eNB' || activeTech === '4G-4G Inter-eNB' ||
        activeTech === '4G-4G Intra' || activeTech === '4G-4G Inter'
    ) return t === '4G-FDD';
    return t === activeTech;
}

function _updateMapCountLabel(siteCount, repeaterCount) {
    const el = document.getElementById('sites-count');
    if (!el) return;
    const s = Number(siteCount) || 0;
    const r = Number(repeaterCount) || 0;
    if (s && r) el.textContent = `${s} sites · ${r} repeaters`;
    else if (r) el.textContent = `${r} repeaters`;
    else el.textContent = String(s);
}

function runFilters() {
    const hasSites = sitesData.length > 0;
    const hasRepeaters = showRepeaters && repeaterData.length > 0;

    if (!hasSites && !hasRepeaters) {
        _showEmptyState();
        displaySites([]);
        displayRepeaters([]);
        _updateMapCountLabel(0, 0);
        return;
    }

    const filteredSites = hasSites ? applyClientFilters(sitesData) : [];
    displaySites(filteredSites);

    if (showRepeaters && repeaterData.length) {
        displayRepeaters(repeaterData);
    } else {
        displayRepeaters([]);
    }

    _updateMapCountLabel(filteredSites.length, showRepeaters ? repeaterData.length : 0);
    _zoomToSiteSearchMatches(filteredSites);
    void _maybeRerunCodeSearch();
}

// ─── Site loading & display ───────────────────────────────────────────────────

async function loadNetworkSites() {
    try {
        if (!_hasActiveFilters()) {
            sitesData = [];
            lastLoadedScopeKey = '';
            displaySites([]);
            if (showRepeaters) {
                await loadRepeaters();
            } else {
                repeaterData = [];
                repeatersLoaded = false;
                displayRepeaters([]);
                _showEmptyState();
            }
            return;
        }

        const scopeKey = NEIGHBOR_ONLY_MODE
            ? `neighbor-sites|${activeTechSpecific}`
            : `${activeTech}|${activeTechSpecific}`;
        const shouldFetchFromServer = !sitesData.length || lastLoadedScopeKey !== scopeKey;
        if (!shouldFetchFromServer) {
            runFilters();
            return;
        }

        const params = new URLSearchParams();
        if (!NEIGHBOR_ONLY_MODE && activeTech !== 'all') params.set('tech', activeTech);
        if (activeTechSpecific !== 'all') params.set('tech_value', activeTechSpecific);
        const qs = params.toString();
        const url = qs ? `/api/map/sites?${qs}` : '/api/map/sites';
        const res  = await fetch(url);
        const data = await res.json();
        if (!data.success) {
            console.error('Sites API error:', data.error || data);
            return;
        }

        sitesData = enrichSites(data.sites);
        lastLoadedScopeKey = scopeKey;

        runFilters();

        buildAreaFilter(sitesData);
        buildClusterFilter(sitesData);

        if (showRepeaters) {
            await loadRepeaters();
        }
    } catch (e) {
        console.error('Sites error:', e);
        showNotification('Failed to load network sites', 'error');
    }
}

// ─── Repeater layer (manual spreadsheet) ─────────────────────────────────────

function getRepeaterPinIcon() {
    if (_repeaterPinIcon) return _repeaterPinIcon;
    const svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 36">'
        + '<path fill="#c0392b" stroke="#7b241c" stroke-width="1.2" d="M12 0C5.4 0 0 5.4 0 12c0 9 12 24 12 24s12-15 12-24C24 5.4 18.6 0 12 0z"/>'
        + '<circle fill="#fff" cx="12" cy="11" r="4.5"/></svg>';
    _repeaterPinIcon = L.icon({
        iconUrl: `data:image/svg+xml,${encodeURIComponent(svg)}`,
        iconSize: [22, 33],
        iconAnchor: [11, 33],
    });
    return _repeaterPinIcon;
}

async function loadRepeaters() {
    if (!showRepeaters || NEIGHBOR_ONLY_MODE) {
        repeaterData = [];
        repeatersLoaded = false;
        displayRepeaters([]);
        return;
    }
    if (repeatersLoaded && repeaterData.length) {
        runFilters();
        return;
    }

    const btn = document.getElementById('show-repeaters');
    if (btn) btn.disabled = true;
    showNotification('Loading repeaters…', 'info');

    try {
        const res = await fetch('/api/map/repeaters', {
            headers: { 'Accept-Encoding': 'gzip' },
            credentials: 'same-origin',
        });
        let data;
        try {
            data = await res.json();
        } catch (parseErr) {
            console.error('Repeaters JSON parse error:', parseErr);
            showNotification(`Failed to parse repeater data (HTTP ${res.status})`, 'error');
            return;
        }
        if (!res.ok || !data.success) {
            console.error('Repeaters API error:', data.error || data, res.status);
            showNotification(data.error || `Failed to load repeaters (HTTP ${res.status})`, 'error');
            return;
        }
        if (data.message && !data.repeaters?.length) {
            showNotification(data.message, 'info');
        }
        repeaterData = Array.isArray(data.repeaters) ? data.repeaters : [];
        repeatersLoaded = true;
        document.getElementById('site-info-panel').style.display = 'none';
        runFilters();
        showNotification(`Loaded ${repeaterData.length} repeaters`, 'success');
    } catch (e) {
        console.error('Repeaters error:', e);
        showNotification(e.message || 'Failed to load repeaters', 'error');
    } finally {
        if (btn) btn.disabled = false;
    }
}

function displayRepeaters(repeaters) {
    if (!map || !repeaterLayer) return;
    repeaterLayer.clearLayers();
    repeaterMarkers = [];
    if (!repeaters || !repeaters.length) {
        if (map.hasLayer(repeaterLayer)) map.removeLayer(repeaterLayer);
        return;
    }

    const icon = getRepeaterPinIcon();
    const BATCH = 500;
    let idx = 0;

    function addBatch() {
        const end = Math.min(idx + BATCH, repeaters.length);
        for (; idx < end; idx++) {
            const rep = repeaters[idx];
            const lat = Number(rep.latitude);
            const lng = Number(rep.longitude);
            if (!Number.isFinite(lat) || !Number.isFinite(lng)) continue;

            const marker = L.marker([lat, lng], { icon });
            const tipParts = [
                _repeaterDisplayName(rep),
                rep.repeater_type ? `Type: ${rep.repeater_type}` : '',
                rep.supported_rats ? `RAT: ${rep.supported_rats}` : '',
                rep.contact_number ? `Tel: ${rep.contact_number}` : '',
                rep.technician ? `Tech: ${rep.technician}` : '',
            ].filter(Boolean);
            if (tipParts.length) {
                marker.bindTooltip(tipParts.map(escapeHtml).join('<br>'), {
                    direction: 'top',
                    offset: [0, -28],
                });
            }
            marker.on('click', () => showRepeaterDetails(rep.repeater_id));
            repeaterLayer.addLayer(marker);
            repeaterMarkers.push(marker);
        }
        if (idx < repeaters.length) {
            window.requestAnimationFrame(addBatch);
        } else if (!map.hasLayer(repeaterLayer)) {
            repeaterLayer.addTo(map);
        }
    }

    addBatch();
}

function _repeaterPanelRow(label, value, { rtl = false } = {}) {
    if (value == null || !String(value).trim()) return '';
    const valHtml = rtl ? escapeHtmlMaybeRtl(value) : escapeHtml(String(value));
    return `<div class="site-meta-row${rtl ? ' site-meta-row-rtl' : ''}"><strong>${escapeHtml(label)}:</strong> ${valHtml}</div>`;
}

function _renderRepeaterPanel(rep) {
    const panel = document.getElementById('site-info-panel');
    const title = _repeaterDisplayName(rep);
    const technician = rep.technician || rep.assign_to || '';
    const supportedRats = rep.supported_rats
        || _deriveSupportedRats(rep.repeater_type);

    const highlight = [
        ['Repeater type', rep.repeater_type, false],
        ['Supported RATs', supportedRats, false],
        ['Contact number', rep.contact_number, false],
        ['Technician', technician, _hasArabicText(technician)],
    ].filter(([, v]) => v != null && String(v).trim() !== '');

    const rows = [
        ['Site name', rep.site_name, _hasArabicText(rep.site_name)],
        ['Hardware vendor', rep.manufacturer, false],
        ['Model', rep.repeater_model, false],
        ['Status', rep.status, false],
        ['Action', rep.remedy_action, false],
        ['Requester', rep.requester, _hasArabicText(rep.requester)],
        ['Customer (Arabic)', rep.customer_name_arabic, true],
        ['Neighborhood', rep.neighborhood, _hasArabicText(rep.neighborhood)],
        ['Address', rep.address, _hasArabicText(rep.address)],
        ['Category', rep.category, _hasArabicText(rep.category)],
        ['Subcategory', rep.subcategory, _hasArabicText(rep.subcategory)],
        ['Outdoor antenna', rep.outdoor_antenna, false],
        ['Serial', rep.serial_number, false],
        ['Floor', rep.floor_no, _hasArabicText(rep.floor_no)],
        ['Technician notes', rep.technician_notes, _hasArabicText(rep.technician_notes)],
        ['Solution type', rep.solution_type, false],
        ['Coordinates', `${rep.latitude}, ${rep.longitude}`, false],
    ].filter(([, v]) => v != null && String(v).trim() !== '');

    const highlightHtml = highlight.length
        ? `<div class="repeater-highlight-block">
            ${highlight.map(([k, v, rtl]) => {
                const valHtml = rtl ? escapeHtmlMaybeRtl(v) : escapeHtml(String(v));
                return `<div class="site-meta-row repeater-highlight-row${rtl ? ' site-meta-row-rtl' : ''}"><strong>${escapeHtml(k)}:</strong> ${valHtml}</div>`;
            }).join('')}
           </div>`
        : '';

    panel.innerHTML = `
        <h3 class="site-panel-title repeater-panel-title">📻 ${escapeHtml(title)}</h3>
        <div class="site-meta-row repeater-badge-row"><span class="repeater-layer-badge">Repeater device</span></div>
        ${highlightHtml}
        ${rows.map(([k, v, rtl]) => _repeaterPanelRow(k, v, { rtl })).join('')}
    `;
    panel.style.display = 'block';
}

/** Client-side RAT list when detail payload omits supported_rats (older cache). */
function _deriveSupportedRats(repeaterType) {
    const raw = String(repeaterType || '').trim();
    if (!raw) return '';
    const c = raw.toLowerCase().replace(/\s+/g, '');
    if (c === 'non' || c === 'none') return '';
    const rats = [];
    if (c.includes('2g')) rats.push('2G');
    if (c.includes('3g')) rats.push('3G');
    if (c.includes('4g') || c.includes('lte')) rats.push('4G');
    if (c.includes('5g') || c.startsWith('nr')) rats.push('5G');
    return rats.length ? rats.join(', ') : raw;
}

async function showRepeaterDetails(repeaterId) {
    try {
        clearSectorLayers();
        selectedSiteId = null;
        lastNeighborSiteContext = null;

        const rid = String(repeaterId || '');
        const res = await fetch(`/api/map/repeater/${encodeURIComponent(rid)}`, {
            credentials: 'same-origin',
        });
        const data = await res.json();
        if (!res.ok || !data.success) {
            showNotification(data.error || 'Repeater not found', 'error');
            return;
        }
        const rep = data.repeater;
        _renderRepeaterPanel(rep);

        if (map && Number.isFinite(Number(rep.latitude)) && Number.isFinite(Number(rep.longitude))) {
            map.setView([Number(rep.latitude), Number(rep.longitude)], Math.max(map.getZoom(), 16));
        }
    } catch (e) {
        console.error('Repeater detail error:', e);
        showNotification('Failed to load repeater details', 'error');
    }
}

function toggleShowRepeaters() {
    const cb = document.getElementById('show-repeaters');
    showRepeaters = Boolean(cb?.checked);
    if (showRepeaters) {
        loadRepeaters();
    } else {
        repeaterData = [];
        repeatersLoaded = false;
        displayRepeaters([]);
        _updateMapCountLabel(
            sitesData.length ? applyClientFilters(sitesData).length : 0,
            0
        );
        if (!_hasActiveFilters() && !sitesData.length) {
            _showEmptyState();
        }
    }
}

function displaySites(sites) {
    siteMarkers.forEach(m => map.removeLayer(m));
    siteMarkers = [];

    if (!sites || !sites.length) return;

    sites.forEach(site => {
        const { iconSize, iconAnchor } = sitePinIconMetrics();
        const icon = L.divIcon({
            className: 'site-marker',
            html: sitePinInnerHtml(site, { highlight: false }),
            iconSize,
            iconAnchor,
        });

        const marker = L.marker([site.latitude, site.longitude], { icon }).addTo(map);
        marker.on('click', () => showSiteDetails(site.site_id));
        siteMarkers.push(marker);
    });
}

// ─── Site detail: draw sector wedges ─────────────────────────────────────────

/** One token per cell for wedge overlay (band / UARFCN / PCI fallback by tech). */
function _wedgeCellBandLabel(c) {
    const tech = String(c.technology || '');
    let t = String(c.frequency_band != null ? c.frequency_band : '').trim();
    if (t) {
        t = t.replace(/\s+/g, ' ').replace(/^band\s*/i, 'B').replace(/\s*MHz\s*$/i, '').trim();
        if (t.length > 14) t = `${t.slice(0, 13)}…`;
        return t;
    }
    if (c.pci != null && /4G|LTE/i.test(tech)) return `PCI${c.pci}`;
    if (c.pci != null && tech === '3G') return `SC${c.pci}`;
    if (c.pci != null && tech === '2G') return `ARFCN${c.pci}`;
    return tech || '—';
}

/** Map text on wedge: cell count + slash-separated band/category per cell (e.g. ``3 · L18/L21/B3``). */
function _wedgeMapLabelText(group) {
    const cells = Array.isArray(group.cells) ? group.cells : [];
    const n = cells.length;
    if (!n) return '';
    const parts = cells.map(_wedgeCellBandLabel);
    return `${n} · ${parts.join('/')}`;
}

async function showSiteDetails(siteId) {
    try {
        clearSectorLayers();
        selectedSiteId = String(siteId || '');
        const res  = await fetch(`/api/map/site/${siteId}`);
        const data = await res.json();
        if (!data.success) return;

        const site = data.site;

        // Prefer backend/site-list enriched cluster+area to avoid "Unknown" when inferred.
        const sourceSite = sitesData.find(s => String(s.site_id) === String(site.site_id));
        if (site.cluster == null && sourceSite?.cluster != null) site.cluster = sourceSite.cluster;
        if (!site.area && sourceSite?.area) site.area = sourceSite.area;
        if (site.cluster == null) site.cluster = Math.floor(site.site_id / 100);
        if (!site.area) site.area = CLUSTER_AREA[site.cluster] || 'Unknown';

        // Filter to active tech; keep all when 'all'
        const cells = (activeTech === 'all')
            ? site.cells
            : site.cells.filter(cellMatchesMapTechFilter);

        // Wedges only for on-air cells; offline cells stay in the list panel only.
        const wedgeCells = cells.filter(cellOperational);
        lastNeighborSiteContext = { site, wedgeCells };

        displaySiteInfo(site, cells);
        if (neighborEnabled && !NEIGHBOR_ONLY_MODE) {
            await refreshNeighborOverlay();
        } else {
            const groups = _groupCellsIntoWedges(site, wedgeCells);
            groups.forEach(g => drawSectorWedge(site, g));
        }
    } catch (e) {
        console.error('Site detail error:', e);
        showNotification('Failed to load site details', 'error');
    }
}

/**
 * Draw a sector wedge polygon.
 *
 * Geographic azimuth convention:
 *   0° = North, 90° = East, 180° = South, 270° = West
 *
 *   lat  offset = R * cos(azimuth)   (North component)
 *   lng  offset = R * sin(azimuth)   (East component, scaled for latitude)
 */
function drawSectorWedge(site, group) {
    const az    = group.azimuth || 0;
    const half  = SECTOR_BEAMWIDTH / 2;
    const rLat  = SECTOR_RADIUS_M / 111320;
    const rLng  = SECTOR_RADIUS_M / (111320 * Math.cos(site.latitude * Math.PI / 180));

    const pts = [[site.latitude, site.longitude]];
    for (let a = az - half; a <= az + half; a += 3) {
        const rad = a * Math.PI / 180;
        pts.push([
            site.latitude  + rLat * Math.cos(rad),
            site.longitude + rLng * Math.sin(rad)
        ]);
    }
    pts.push([site.latitude, site.longitude]);

    const tech = group.technology || '';
    const color   = TECH_COLORS[tech] || '#34495e';
    const anyOnAir = group.cells.some(cellOperational);
    const polygon = L.polygon(pts, {
        color,
        fillColor: color,
        fillOpacity: anyOnAir ? 0.35 : 0.2,
        weight: 1.5
    }).addTo(map);

    // Store group payload for click handlers (avoid giant inline JSON in HTML).
    const groupId = group.groupId;
    const elevationId = `nm-elev-${String(groupId || '').replace(/[^a-zA-Z0-9_-]/g, '-')}`;
    wedgeGroups[groupId] = group;

    const cellCount = group.cells.length;
    const header = cellCount === 1
        ? group.cells[0].cell_name
        : `${cellCount} cells (select one)`;

    const cellsHtml = cellCount === 1
        ? ''
        : `<div style="margin-top:10px; display:flex; flex-direction:column; gap:6px;">
              ${group.cells.map(c => {
                  const meta = `${c.frequency_band ? ' · ' + c.frequency_band : ''}${c.pci != null ? ' · PCI/SC/BCCH: ' + c.pci : ''}`;
                  if (cellOperational(c)) {
                      const kpi = { cell_name: c.cell_name, technology: c.technology, vendor: c.vendor };
                      const nbr = { ...kpi, site_id: site.site_id };
                      const click = NEIGHBOR_ONLY_MODE
                          ? `neighborDrawRelationsForCell(${JSON.stringify(nbr)})`
                          : `showCellKPIs(${JSON.stringify(kpi)})`;
                      return `<button onclick='${click}'
                        style="padding:6px 10px;background:${color};
                               color:white;border:none;border-radius:6px;cursor:pointer;
                               width:100%;font-weight:600;text-align:left;">
                    ${NEIGHBOR_ONLY_MODE ? '<strong>Draw relations</strong>' : c.cell_name}
                    <span style="font-weight:500;opacity:.9;font-size:.85em;display:block;margin-top:2px;">${NEIGHBOR_ONLY_MODE ? `${escapeHtml(c.cell_name)}${meta}` : meta}</span>
                </button>`;
                  }
                  return `<div style="padding:6px 10px;border-radius:6px;background:#eee;color:#555;
                               font-size:0.9em;border:1px solid #ddd;">
                    <strong>${c.cell_name}</strong>${meta}
                    <div style="margin-top:4px;font-size:0.82em;color:#888;">Offline — no KPI panel</div>
                  </div>`;
              }).join('')}
           </div>`;

    // Use the first cell for summary metadata (band/tilt can vary per cell, but is usually identical).
    const ref = group.cells[0] || {};

    polygon.bindPopup(`
        <div style="min-width:220px;font-family:sans-serif;">
            <div style="font-weight:700;font-size:1em;margin-bottom:6px;">
                ${header}
            </div>
            <div style="color:${color};font-weight:600;margin-bottom:6px;">
                ${tech}
                ${ref.frequency_band ? ' · ' + ref.frequency_band : ''}
            </div>
            <table style="font-size:0.88em;border-collapse:collapse;width:100%;">
                <tr><td style="color:#777;">Azimuth</td>
                    <td style="font-weight:600;">${az}°</td></tr>
                ${ref.mechanical_tilt != null
                    ? `<tr><td style="color:#777;">M.Tilt</td>
                           <td>${ref.mechanical_tilt}°</td></tr>` : ''}
                ${ref.electrical_tilt != null
                    ? `<tr><td style="color:#777;">E.Tilt</td>
                           <td>${ref.electrical_tilt}°</td></tr>` : ''}
                ${ref.pci != null
                    ? `<tr><td style="color:#777;">PCI/SC/BCCH</td>
                           <td>${ref.pci}</td></tr>` : ''}
                <tr><td style="color:#777;">Elevation</td>
                    <td id="${elevationId}" style="font-weight:600;">loading...</td></tr>
            </table>
            ${cellCount === 1 ? (
                cellOperational(ref)
                    ? (() => {
                        const kpi = { cell_name: ref.cell_name, technology: ref.technology, vendor: ref.vendor };
                        const nbr = { ...kpi, site_id: site.site_id };
                        const click = NEIGHBOR_ONLY_MODE
                            ? `neighborDrawRelationsForCell(${JSON.stringify(nbr)})`
                            : `showCellKPIs(${JSON.stringify(kpi)})`;
                        const label = NEIGHBOR_ONLY_MODE ? 'Draw relations' : 'View cell details';
                        return `<button onclick='${click}'
                      style="margin-top:10px;padding:6px 14px;background:${color};
                             color:white;border:none;border-radius:6px;cursor:pointer;
                             width:100%;font-weight:700;">
                  ${label}
              </button>`;
                    })()
                    : `<p style="margin-top:10px;color:#888;font-size:0.88em;line-height:1.35;">
                  Offline cell — KPI details are hidden.
                </p>`
            ) : cellsHtml}
        </div>
    `);

    polygon.on('popupopen', () => fillElevationText(elevationId, site.latitude, site.longitude));
    polygon.on('click', e => { L.DomEvent.stopPropagation(e); polygon.openPopup(); });
    sectorLayers.push(polygon);

    const wedgeLabelText = _wedgeMapLabelText(group);
    if (wedgeLabelText) {
        const labelDistM = SECTOR_RADIUS_M * 0.5;
        const rLatL = labelDistM / 111320;
        const rLngL = labelDistM / (111320 * Math.cos(site.latitude * Math.PI / 180));
        const rad = az * Math.PI / 180;
        const latL = site.latitude + rLatL * Math.cos(rad);
        const lngL = site.longitude + rLngL * Math.sin(rad);
        const labelIcon = L.divIcon({
            className: 'wedge-sector-label-marker',
            html: `<div class="wedge-sector-label-inner">${escapeHtml(wedgeLabelText)}</div>`,
            iconSize: [168, 44],
            iconAnchor: [84, 22],
        });
        const labelMk = L.marker([latL, lngL], {
            icon: labelIcon,
            interactive: false,
            keyboard: false,
            zIndexOffset: 450,
        }).addTo(map);
        sectorLayers.push(labelMk);
    }
}

function clearSectorLayers() {
    sectorLayers.forEach(l => map.removeLayer(l));
    sectorLayers = [];
}

// ─── Site info panel ─────────────────────────────────────────────────────────

function displaySiteInfo(site, cells) {
    const panel = document.getElementById('site-info-panel');

    // Group cells by technology
    const byTech = {};
    cells.forEach(c => {
        (byTech[c.technology] = byTech[c.technology] || []).push(c);
    });

    let techHtml = '';
    CELL_TECH_SORT_ORDER.concat(
        Object.keys(byTech).filter(t => !CELL_TECH_SORT_ORDER.includes(t))
    ).forEach(tech => {
        if (!byTech[tech]) return;
        const color = TECH_COLORS[tech] || '#34495e';
        techHtml += `<div class="tech-group">
            <div class="tech-group-label" style="color:${color};">${tech}</div>`;
        byTech[tech].forEach(c => {
            const onAir = cellOperational(c);
            const cellPayload = { cell_name: c.cell_name, technology: c.technology, vendor: c.vendor };
            const drawPayload = { ...cellPayload, site_id: site.site_id };
            const rowClick = onAir && !NEIGHBOR_ONLY_MODE
                ? `onclick='showCellKPIs(${JSON.stringify(cellPayload)})'`
                : '';
            const drawBtn = NEIGHBOR_ONLY_MODE && onAir
                ? `<button type="button" class="neighbor-draw-cell-btn" onclick='neighborDrawRelationsForCell(${JSON.stringify(drawPayload)})'>Draw relations</button>`
                : '';
            const metaLine = [`Az: ${c.azimuth ?? '—'}°`, c.frequency_band ? String(c.frequency_band).trim() : '']
                .filter(Boolean)
                .join(' · ');
            const rowInner = NEIGHBOR_ONLY_MODE && onAir
                ? `<div class="cell-row-neighbor-info">
                    <span class="cell-name">${escapeHtml(String(c.cell_name || ''))}</span>
                    <div class="cell-row-neighbor-meta">${escapeHtml(metaLine)}</div>
                </div>${drawBtn}`
                : `<span class="cell-name">${c.cell_name}</span>
                ${onAir ? '' : '<span class="cell-offline-badge">Offline</span>'}
                <span class="cell-meta">Az: ${c.azimuth ?? '—'}°</span>
                ${c.frequency_band ? `<span class="cell-meta">${c.frequency_band}</span>` : ''}
                ${drawBtn}`;
            techHtml += `
            <div class="cell-row${onAir ? '' : ' cell-row-offline'}${NEIGHBOR_ONLY_MODE && onAir ? ' cell-row-neighbor-action' : ''}"
                 ${rowClick}>
                ${rowInner}
            </div>`;
        });
        techHtml += '</div>';
    });

    const offlineN = cells.filter(c => !cellOperational(c)).length;
    const offlineNote = offlineN > 0
        ? `<div class="site-meta-row site-offline-summary"><strong>Offline:</strong> ${offlineN} cell${offlineN === 1 ? '' : 's'} (no sector wedges)</div>`
        : '';


    panel.innerHTML = `
        <h3 class="site-panel-title">📡 ${site.site_name}</h3>
        <div class="site-meta-row"><strong>Site ID:</strong> ${site.site_id}</div>
        <div class="site-meta-row"><strong>Cluster:</strong> ${site.cluster ?? '—'}</div>
        <div class="site-meta-row"><strong>Area:</strong> ${site.area || '—'}</div>
        <div class="site-meta-row"><strong>Vendor:</strong> ${site.vendor || '—'}</div>
        <div class="site-meta-row"><strong>Elevation:</strong> <span id="site-elevation-value">loading...</span></div>
        <div class="site-meta-row"><strong>Cells shown:</strong> ${cells.length}</div>
        ${offlineNote}
        ${techHtml}
        <div class="site-panel-actions">
        <a href="/performance?site_id=${encodeURIComponent(site.site_id)}"
           class="kpi-link">
            📈 In-depth KPI
        </a>
        <a href="${escapeHtmlAttr(SITE_AUDITS_TOOL_URL)}" class="kpi-link site-audits-link" target="_blank" rel="noopener noreferrer">📋 Site Audits</a>
        </div>
    `;
    panel.style.display = 'block';
    fillElevationText('site-elevation-value', site.latitude, site.longitude);
}

// ─── Cell KPI modal ───────────────────────────────────────────────────────────

/** When wedge payload omits ``technology``, neighbor chips scope LTE to FDD on the server (no TDD in HO stats). */
function mapChipTechnologyForKpi(tech) {
    if (!tech || tech === 'all') return '';
    if ([
        '2G-2G', '3G-3G',
        '4G-4G',
        '4G-4G Intra-eNB', '4G-4G Inter-eNB',
        '4G-4G Intra', '4G-4G Inter',
    ].includes(tech)) return tech;
    return '';
}

async function showCellKPIs(cellId) {
    try {
        const cellReq = (typeof cellId === 'object' && cellId !== null)
            ? cellId
            : { cell_name: cellId };
        const cellName = String(cellReq.cell_name || '');
        const cellTechRaw = String(cellReq.technology || '').trim();
        const cellVendor = String(cellReq.vendor || '');
        const techForQuery = cellTechRaw || mapChipTechnologyForKpi(activeTech);
        if (typeof cellId !== 'number') {
            selectedNeighborCell = cellName;
            if (neighborEnabled && NEIGHBOR_ONLY_MODE) {
                _syncActiveTechFromNeighborRatSelect();
                const vendor = document.getElementById('vendor-filter')?.value || 'all';
                const minEl = document.getElementById('neighbor-min-attempts');
                const minRaw = Number(minEl?.value);
                const minFilterValue = Number.isFinite(minRaw)
                    ? minRaw
                    : (_neighborFailuresMode() ? 1 : 10);
                await renderNeighborExplorerPanel(vendor, activeTech, null, minFilterValue);
            } else if (neighborEnabled) {
                await refreshNeighborOverlay();
            }
        }
        const url = (typeof cellId === 'number')
            ? `/api/map/cell/${cellId}/kpis`
            : `/api/map/cell/kpis?cell_name=${encodeURIComponent(cellName)}`
                + (techForQuery ? `&technology=${encodeURIComponent(techForQuery)}` : '')
                + (cellVendor ? `&vendor=${encodeURIComponent(cellVendor)}` : '');

        const res = await fetch(url);
        let data;
        try {
            data = await res.json();
        } catch (_) {
            showNotification('Could not read KPI response', 'error');
            return;
        }
        if (!data.success) {
            showNotification(
                data.error || (res.status === 404 ? 'Cell not found for this filter' : 'Could not load KPIs'),
                res.status === 404 ? 'info' : 'error'
            );
            return;
        }
        renderKPIModal(data.cell);
    } catch (e) {
        console.error('KPI error:', e);
        showNotification('Could not load cell KPIs', 'error');
    }
}

function renderKPIModal(cell) {
    const color = TECH_COLORS[cell.technology] || '#34495e';
    const kpis  = cell.kpis;
    const metadata = cell.metadata;

    const kpiRow = (label, val, unit = '') =>
        `<div class="kpi-item">
            <div class="kpi-label">${label}</div>
            <div class="kpi-value">${val != null ? val + unit : '—'}</div>
         </div>`;

    const known = kpis ? {
        avg_users: 'Users',
        data_volume_gb: 'Data (GB)',
        rsrp: 'RSRP (dBm)',
        rsrq: 'RSRQ (dB)',
        sinr: 'SINR (dB)',
        throughput_dl_mbps: 'DL Throughput (Mbps)',
        throughput_ul_mbps: 'UL Throughput (Mbps)',
        rrc_success_rate: 'RRC Success (%)',
        erab_success_rate: 'ERAB Success (%)',
        call_drop_rate: 'Drop Rate (%)',
        handover_success_rate: 'HO Success (%)',
        availability_percent: 'Availability (%)',
    } : {};

    const _fmt = (v) => {
        if (v == null) return null;
        if (typeof v === 'number') return Number.isFinite(v) ? v : null;
        // Try numeric strings
        const asNum = Number(v);
        return Number.isFinite(asNum) && String(v).trim() !== '' ? asNum : v;
    };

    const summaryGrid = kpis ? (() => {
        const entries = Object.entries(known)
            .map(([key, label]) => [label, _fmt(kpis[key])])
            .filter(([, v]) => v != null);
        if (!entries.length) return '';
        return `<div class="kpi-grid">
            ${entries.map(([label, v]) => kpiRow(label, (typeof v === 'number' ? v.toFixed(2) : v))).join('')}
        </div>`;
    })() : '';

    const detailsTable = kpis ? (() => {
        const skip = new Set(['id', 'cell_name', 'timestamp']);
        const rows = Object.keys(kpis)
            .filter(k => !skip.has(k))
            .sort()
            .map(k => ({ k, v: kpis[k] }))
            .filter(r => r.v != null && String(r.v).trim() !== '');

        if (!rows.length) return '';
        const max = 40;
        const shown = rows.slice(0, max);
        const more = rows.length - shown.length;
        return `
            <div style="margin-top:14px;">
                <div style="font-weight:800;color:#2c3e50;margin-bottom:8px;">All KPI fields</div>
                <div style="max-height:260px; overflow:auto; border:1px solid #eee; border-radius:8px;">
                    <table style="width:100%; border-collapse:collapse; font-size:0.88em;">
                        ${shown.map(r => `
                          <tr>
                            <td style="padding:8px 10px; border-bottom:1px solid #f1f1f1; color:#666; width:55%;">${r.k}</td>
                            <td style="padding:8px 10px; border-bottom:1px solid #f1f1f1; font-weight:700; color:#2c3e50;">${r.v}</td>
                          </tr>
                        `).join('')}
                    </table>
                </div>
                ${more > 0 ? `<div style="margin-top:6px;color:#7f8c8d;font-size:0.82em;">Showing ${shown.length}/${rows.length} fields</div>` : ''}
            </div>
        `;
    })() : '';

    const metadataTable = metadata ? (() => {
        const rows = Object.keys(metadata)
            .sort()
            .map(k => ({ k, v: metadata[k] }))
            .filter(r => r.v != null && String(r.v).trim() !== '');
        if (!rows.length) return '';
        const max = 80;
        const shown = rows.slice(0, max);
        const more = rows.length - shown.length;
        return `
            <div style="margin-top:14px;">
                <div style="font-weight:800;color:#2c3e50;margin-bottom:8px;">All cell metadata fields</div>
                <div style="max-height:260px; overflow:auto; border:1px solid #eee; border-radius:8px;">
                    <table style="width:100%; border-collapse:collapse; font-size:0.88em;">
                        ${shown.map(r => `
                          <tr>
                            <td style="padding:8px 10px; border-bottom:1px solid #f1f1f1; color:#666; width:55%;">${r.k}</td>
                            <td style="padding:8px 10px; border-bottom:1px solid #f1f1f1; font-weight:700; color:#2c3e50;">${r.v}</td>
                          </tr>
                        `).join('')}
                    </table>
                </div>
                ${more > 0 ? `<div style="margin-top:6px;color:#7f8c8d;font-size:0.82em;">Showing ${shown.length}/${rows.length} fields</div>` : ''}
            </div>
        `;
    })() : '';

    const kpiHtml = kpis
        ? `${summaryGrid}
           <div style="font-size:0.82em;color:#7f8c8d;margin-top:10px;">
               Last: ${kpis.timestamp ? new Date(kpis.timestamp).toLocaleString() : '—'}
           </div>
           ${detailsTable}`
        : `<p style="color:#95a5a6;">No KPI data available</p>`;

    const perfUrl = (() => {
        const params = new URLSearchParams();
        if (cell.site_id != null) params.set('site_id', String(cell.site_id));
        if (cell.cell_name) params.set('cell_name', String(cell.cell_name));
        if (cell.technology) params.set('technology', String(cell.technology));
        const qs = params.toString();
        return qs ? `/performance?${qs}` : '/performance';
    })();

    document.getElementById('kpi-content').innerHTML = `
        <span class="close-modal" onclick="closeKPIModal()">&times;</span>
        <h2 style="margin-top:0;color:#0a0a0a;border-bottom:3px solid ${color};
                   padding-bottom:8px;">
            ${cell.cell_name}
        </h2>
        <div style="margin-bottom:14px;color:#444;font-size:0.9em;line-height:1.7;">
            <strong style="color:#0a0a0a;">Site:</strong> <span style="color:#0a0a0a;font-weight:600;">${cell.site_name || '—'}</span> &nbsp;|&nbsp;
            <strong style="color:${color};">${cell.technology || '—'}</strong>
            &nbsp;|&nbsp; Vendor: ${cell.vendor || '—'}
            &nbsp;|&nbsp; Az: ${cell.azimuth ?? '—'}°
            &nbsp;|&nbsp; PCI/SC/BCCH: ${cell.pci ?? '—'}
            <br/>
            <strong>Activity:</strong> ${cell.activity_status || cell.status || '—'}
            &nbsp;|&nbsp; <strong>Band:</strong> ${cell.frequency_band || '—'}
            &nbsp;|&nbsp; <strong>Tilts:</strong> M ${cell.mechanical_tilt ?? '—'}° / E ${cell.electrical_tilt ?? '—'}°
        </div>
        <a href="${perfUrl}"
           style="display:inline-block;margin:2px 0 12px;padding:8px 12px;background:${color};
                  color:#fff;text-decoration:none;border-radius:8px;font-weight:700;font-size:0.88em;">
            📈 Open in Performance Page
        </a>
        ${kpiHtml}
        ${metadataTable}
    `;
    document.getElementById('kpi-modal').style.display = 'flex';
}

function closeKPIModal() {
    document.getElementById('kpi-modal').style.display = 'none';
}

// ─── Cell-code search (SC / PCI / BCCH) ──────────────────────────────────────

function _activeCellCodeSearch() {
    const code = (document.getElementById('cell-code-search')?.value || '').trim();
    if (!code || Number.isNaN(Number(code))) return null;
    return code;
}

/** Re-apply PCI/BCCH/PSC highlights after map filters reload. */
function _maybeRerunCodeSearch() {
    if (!_activeCellCodeSearch()) return;
    clearTimeout(codeSearchTimer);
    codeSearchTimer = setTimeout(doCodeSearch, 50);
}

function cellCodeSearch() {
    clearTimeout(codeSearchTimer);
    const val = document.getElementById('cell-code-search').value.trim();
    if (!val) { clearHighlights(); return; }
    codeSearchTimer = setTimeout(doCodeSearch, 400);
}

async function doCodeSearch() {
    const code = _activeCellCodeSearch();
    if (!code) return;

    clearHighlights();

    const techParam = activeTech !== 'all'
        ? `&tech=${encodeURIComponent(activeTech)}` : '';
    const techValue = activeTechSpecific !== 'all'
        ? `&tech_value=${encodeURIComponent(activeTechSpecific)}` : '';

    try {
        const res  = await fetch(`/api/map/search/cell-code?code=${code}${techParam}${techValue}`);
        const data = await res.json();
        if (!data.success) return;

        const panel = document.getElementById('site-info-panel');
        if (!data.matches.length) {
            const techLabel = _codeLabel();
            panel.innerHTML = `<div class="code-no-results">No cells found with ${techLabel} = ${code}</div>`;
            panel.style.display = 'block';
            return;
        }

        drawCodeSearchResults(data.matches, parseInt(code));
    } catch (e) {
        console.error('Code search error:', e);
    }
}

function conflictMapTechFromCellTech(techRaw) {
    const t = String(techRaw || '').trim().toUpperCase();
    if (!t || t === '2G' || t.includes('GSM')) return null;
    if (t === '3G' || t.includes('UMTS') || t.includes('WCDMA')) return '3G';
    if (t === '5G' || t.includes('NR')) return '5G';
    if (t.includes('4G') || t.includes('LTE')) return '4G';
    return null;
}

function conflictMapTechFromMatches(matches) {
    const techs = new Set();
    for (const cell of matches || []) {
        const mapped = conflictMapTechFromCellTech(cell.technology);
        if (mapped) techs.add(mapped);
    }
    if (!techs.size) return null;
    if (techs.size === 1) return [...techs][0];
    if (techs.has('4G')) return '4G';
    if (techs.has('3G')) return '3G';
    return '5G';
}

function conflictMapTechFromActive() {
    const t = activeTech || '';
    if (t === 'all') return null;
    if (t === '3G-3G' || t === '3G') return '3G';
    if (t === '5G') return '5G';
    if (t === '4G-4G' || t === '4G-FDD' || t === '4G' || t.startsWith('4G')) return '4G';
    return null;
}

function conflictMapUrlForCode(code, matches) {
    const tech = conflictMapTechFromActive() || conflictMapTechFromMatches(matches);
    if (!tech) return null;
    const qs = new URLSearchParams({
        technology: tech,
        pci: String(code),
        strictness: 'standard',
        risk: 'all',
        area: 'all',
        band: 'all',
        auto: '1',
    });
    return `/conflict-map?${qs.toString()}`;
}

function drawCodeSearchResults(matches, code) {
    // Hide all regular site markers — only show matching ones
    siteMarkers.forEach(m => map.removeLayer(m));

    // Group by site
    const siteMap = {};
    matches.forEach(cell => {
        if (!siteMap[cell.site_id]) {
            siteMap[cell.site_id] = {
                site_id:   cell.site_id,
                site_name: cell.site_name,
                latitude:  cell.latitude,
                longitude: cell.longitude,
                cells: []
            };
        }
        siteMap[cell.site_id].cells.push(cell);
    });

    // Draw highlight wedges for every matching cell that has azimuth data
    matches.forEach(cell => {
        if (cellOperational(cell) && cell.azimuth != null) drawHighlightWedge(cell);
    });

    // Drop highlight markers on matching sites only
    Object.values(siteMap).forEach(site => {
        site.offline_cell_count = site.cells.filter(c => !cellOperational(c)).length;
        const fromList = sitesData.find(s => String(s.site_id) === String(site.site_id));
        site.full_sector_offline_count = fromList != null && fromList.full_sector_offline_count != null
            ? Number(fromList.full_sector_offline_count) || 0
            : 0;
        const { iconSize, iconAnchor } = sitePinIconMetrics();
        const icon = L.divIcon({
            className: 'site-marker',
            html: sitePinInnerHtml(site, { highlight: true }),
            iconSize,
            iconAnchor,
        });
        const marker = L.marker([site.latitude, site.longitude], { icon }).addTo(map);
        marker.on('click', () => showSiteDetails(site.site_id));
        highlightMarkers.push(marker);
    });

    // Populate side panel
    const techLabel = _codeLabel();
    const techParam = activeTech !== 'all' ? activeTech : '';
    let siteHtml = '';
    Object.values(siteMap).forEach(site => {
        siteHtml += `
            <div class="code-result-site" onclick="showSiteDetails('${site.site_id}')">
                <div class="code-result-site-name">📡 ${site.site_name}</div>`;
        site.cells.forEach(c => {
            const color = TECH_COLORS[c.technology] || '#34495e';
            const off = !cellOperational(c);
            siteHtml += `
                <div class="code-result-cell${off ? ' code-result-cell-offline' : ''}">
                    <span class="cell-tech-badge" style="background:${color}">${c.technology}</span>
                    <span class="cell-name">${c.cell_name}</span>
                    ${off ? '<span class="code-offline-hint">offline</span>' : ''}
                    <span class="cell-meta">Az: ${c.azimuth ?? '—'}°</span>
                </div>`;
        });
        siteHtml += '</div>';
    });

    const panel = document.getElementById('site-info-panel');
    const conflictUrl = conflictMapUrlForCode(code, matches);
    const conflictBtn = conflictUrl
        ? `<a class="export-btn conflict-map-link" href="${conflictUrl}" target="_blank" rel="noopener">⚡ Check conflicts</a>`
        : '';
    panel.innerHTML = `
        <h3 class="site-panel-title">🔍 ${techLabel} = ${code}</h3>
        <div class="site-meta-row" style="margin-bottom:8px;">
            ${matches.length} cell${matches.length !== 1 ? 's' : ''}
            across ${Object.keys(siteMap).length} site${Object.keys(siteMap).length !== 1 ? 's' : ''}
        </div>
        <div class="code-search-actions">
            ${conflictBtn}
            <button class="export-btn" onclick="exportCodeSearch(${code}, '${techParam}')">
                ⬇ Export to Excel
            </button>
        </div>
        ${siteHtml}
    `;
    panel.style.display = 'block';
    requestAnimationFrame(() => {
        panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    });

    const bounds = [];
    matches.forEach((cell) => {
        const lat = Number(cell.latitude);
        const lng = Number(cell.longitude);
        if (Number.isFinite(lat) && Number.isFinite(lng)) bounds.push([lat, lng]);
    });
    if (map && bounds.length === 1) {
        map.setView(bounds[0], Math.max(map.getZoom(), 14));
    } else if (map && bounds.length > 1) {
        map.fitBounds(bounds, { padding: [40, 40], maxZoom: 15 });
    }
}

/** Download matching cells as an Excel file. */
function exportCodeSearch(code, tech) {
    const techParam = tech ? `&tech=${encodeURIComponent(tech)}` : '';
    const techValueParam = activeTechSpecific !== 'all'
        ? `&tech_value=${encodeURIComponent(activeTechSpecific)}`
        : '';
    window.location.href = `/api/map/export/cell-code?code=${code}${techParam}${techValueParam}`;
}

function drawHighlightWedge(cell) {
    if (!cellOperational(cell)) return;
    const az    = cell.azimuth || 0;
    const half  = SECTOR_BEAMWIDTH / 2;
    const rLat  = SECTOR_RADIUS_M / 111320;
    const rLng  = SECTOR_RADIUS_M / (111320 * Math.cos(cell.latitude * Math.PI / 180));

    const pts = [[cell.latitude, cell.longitude]];
    for (let a = az - half; a <= az + half; a += 3) {
        const rad = a * Math.PI / 180;
        pts.push([
            cell.latitude  + rLat * Math.cos(rad),
            cell.longitude + rLng * Math.sin(rad)
        ]);
    }
    pts.push([cell.latitude, cell.longitude]);

    const techColor = TECH_COLORS[cell.technology] || '#34495e';
    const polygon   = L.polygon(pts, {
        color:       '#f1c40f',   // bright yellow border = highlighted
        fillColor:   techColor,
        fillOpacity: 0.65,
        weight:      3,
    }).addTo(map);

    polygon.bindPopup(`
        <div style="min-width:190px;font-family:sans-serif;">
            <div style="font-weight:700;font-size:1em;margin-bottom:6px;">
                ${cell.cell_name}
            </div>
            <div style="color:${techColor};font-weight:600;margin-bottom:6px;">
                ${cell.technology || ''}
                ${cell.frequency_band ? ' · ' + cell.frequency_band : ''}
            </div>
            <table style="font-size:0.88em;border-collapse:collapse;width:100%;">
                <tr><td style="color:#777;">${_codeLabel()}</td>
                    <td style="font-weight:600;color:#e67e22;">${cell.pci}</td></tr>
                <tr><td style="color:#777;">Azimuth</td>
                    <td style="font-weight:600;">${az}°</td></tr>
                ${cell.mechanical_tilt != null
                    ? `<tr><td style="color:#777;">M.Tilt</td><td>${cell.mechanical_tilt}°</td></tr>` : ''}
                ${cell.electrical_tilt != null
                    ? `<tr><td style="color:#777;">E.Tilt</td><td>${cell.electrical_tilt}°</td></tr>` : ''}
            </table>
            ${cellOperational(cell)
        ? `<button onclick='showCellKPIs(${JSON.stringify({ cell_name: cell.cell_name, technology: cell.technology, vendor: cell.vendor })})'
                    style="margin-top:10px;padding:5px 14px;background:${techColor};
                           color:white;border:none;border-radius:5px;cursor:pointer;
                           width:100%;font-weight:600;">
                View KPIs
            </button>`
        : `<p style="margin-top:10px;color:#888;font-size:0.85em;">Offline — KPIs hidden.</p>`}
        </div>
    `);
    polygon.on('click', e => { L.DomEvent.stopPropagation(e); polygon.openPopup(); });
    highlightLayers.push(polygon);
}

function clearHighlights() {
    highlightLayers.forEach(l => map && map.removeLayer(l));
    highlightLayers = [];
    highlightMarkers.forEach(m => map && map.removeLayer(m));
    highlightMarkers = [];
    // Restore all regular site markers
    siteMarkers.forEach(m => { try { m.addTo(map); } catch (_) {} });
}

function _neighborColor(rate) {
    const r = Number(rate);
    if (!Number.isFinite(r)) return '#7f8c8d';
    if (r >= 95) return '#27ae60';
    if (r >= 90) return '#2e86c1';
    if (r >= 80) return '#f39c12';
    return '#e74c3c';
}

/** Neighbor map metric: ``attempts_sr`` (default) or ``failures`` (API ``failures_only``). */
function _neighborMetricMode() {
    const el = document.getElementById('neighbor-metric-mode');
    const v = String(el?.value || 'attempts_sr').trim();
    return v === 'failures' ? 'failures' : 'attempts_sr';
}

function _neighborFailuresMode() {
    return _neighborMetricMode() === 'failures';
}

function updateNeighborMetricHint() {
    const lab = document.querySelector('label[for="neighbor-min-attempts"]');
    const inp = document.getElementById('neighbor-min-attempts');
    const fm = _neighborFailuresMode();
    if (lab) lab.textContent = fm ? 'Min failures' : 'Min attempts';
    if (inp) {
        inp.placeholder = fm ? 'e.g. 1' : 'e.g. 10';
        inp.title = fm
            ? 'Only links with estimated failures ≥ this number (default 1 hides rows with no real failures).'
            : 'Only links with at least this many handover attempts.';
    }
}

/** Neighbor-only: short panel copy (no auto-loaded lines until Draw relations). */
function _neighborPanelIdle() {
    const panel = document.getElementById('neighbor-explorer-panel');
    if (!panel || !neighborEnabled || !NEIGHBOR_ONLY_MODE) return;
    panel.style.display = 'block';
    const n = neighborLineData.length;
    if (selectedNeighborCell) {
        panel.innerHTML = `
            <div class="site-meta-row">Cell: <strong>${escapeHtml(selectedNeighborCell)}</strong></div>
            <div class="site-meta-row">Lines on map: ${n}. Use <strong>Draw relations</strong> on a cell after changing export vendor or RAT.</div>`;
    } else {
        panel.innerHTML = `
            <div class="site-meta-row">Lines on map: ${n}. Open a site, pick a cell, then <strong>Draw relations</strong> (export vendor and RAT choose which file is queried).</div>`;
    }
}

async function drawNeighborRelations() {
    if (!neighborEnabled) return;
    if (NEIGHBOR_ONLY_MODE) {
        const sid = String(selectedSiteId || '').trim();
        const cn = String(selectedNeighborCell || '').trim();
        if (!sid || !cn) {
            showNotification('Open a site in the panel, then use Draw relations on a cell.', 'info');
            return;
        }
    }
    await refreshNeighborOverlay();
}

/**
 * Neighbor-only: set site + source cell from UI, load HO lines and cell summary.
 * On the main map, falls back to opening the KPI modal.
 */
async function neighborDrawRelationsForCell(payload) {
    const p = typeof payload === 'object' && payload != null ? payload : {};
    if (!NEIGHBOR_ONLY_MODE || !neighborEnabled) {
        await showCellKPIs(p);
        return;
    }
    const siteId = String(p.site_id != null ? p.site_id : selectedSiteId || '').trim();
    const cellName = String(p.cell_name || '').trim();
    if (!siteId || !cellName) {
        showNotification('Select a site and cell to draw relations.', 'info');
        return;
    }
    selectedSiteId = siteId;
    selectedNeighborCell = cellName;
    await drawNeighborRelations();
}

function _neighborColorGradient(rate) {
    const r = Number(rate);
    if (!Number.isFinite(r)) return '#95a5a6';
    const x = Math.max(0, Math.min(1, r / 100));
    const r0 = 0xe7, g0 = 0x4c, b0 = 0x3c;
    const r1 = 0x27, g1 = 0xae, b1 = 0x60;
    const rr = Math.round(r0 + (r1 - r0) * x);
    const gg = Math.round(g0 + (g1 - g0) * x);
    const bb = Math.round(b0 + (b1 - b0) * x);
    return `#${rr.toString(16).padStart(2, '0')}${gg.toString(16).padStart(2, '0')}${bb.toString(16).padStart(2, '0')}`;
}

function _neighborLineColor(ln) {
    const fo = _neighborFailuresMode();
    if (fo && ln.ho_failure_rate_percent != null && Number.isFinite(Number(ln.ho_failure_rate_percent))) {
        const fauxSr = 100 - Number(ln.ho_failure_rate_percent);
        return _neighborColorGradient(fauxSr);
    }
    const tech = String(ln.technology || activeTech || '');
    const u = tech.toUpperCase();
    if (u.startsWith('3G') || u.includes('4G') || u.includes('LTE')) {
        return _neighborColorGradient(ln.ho_success_rate);
    }
    return _neighborColor(ln.ho_success_rate);
}

/** Stroke width from attempts, scaled to the largest attempt in the current batch (better relative contrast). */
function _neighborLineWeight(attempts, maxAttemptsInBatch) {
    const a = Number(attempts);
    const m = Number(maxAttemptsInBatch);
    if (!Number.isFinite(a) || a <= 0) return 1.8;
    if (!Number.isFinite(m) || m <= 0) return 2.5;
    const r = Math.min(1, a / m);
    const minW = 2;
    const maxW = 14;
    return minW + (maxW - minW) * Math.pow(r, 0.85);
}

/** Offset line endpoint along azimuth from cell coords (toward sector boresight). */
function _neighborLineEndpoint(lat, lng, azimuthDeg, offsetM) {
    if (!Number.isFinite(lat) || !Number.isFinite(lng)) return [lat, lng];
    const az = Number(azimuthDeg);
    if (!Number.isFinite(az) || offsetM <= 0) return [lat, lng];
    const rad = az * Math.PI / 180;
    const rLat = offsetM / 111320;
    const rLng = offsetM / (111320 * Math.cos(lat * Math.PI / 180));
    return [lat + rLat * Math.cos(rad), lng + rLng * Math.sin(rad)];
}

function clearNeighborOverlay() {
    neighborLineData = [];
    if (neighborLinesLayer) neighborLinesLayer.clearLayers();
    const panel = document.getElementById('neighbor-explorer-panel');
    if (panel && !neighborEnabled) panel.style.display = 'none';
    if (NEIGHBOR_ONLY_MODE && neighborEnabled) _neighborPanelIdle();
}

function onMapModuleChange() {
    if (NEIGHBOR_ONLY_MODE) {
        mapModule = 'neighbor-explorer';
        neighborEnabled = true;
        _neighborPanelIdle();
        return;
    }
    const sel = document.getElementById('map-module-select');
    mapModule = String(sel?.value || 'site-explorer');
    neighborEnabled = mapModule === 'neighbor-explorer';
    const controls = document.getElementById('neighbor-controls');
    if (controls) controls.style.display = neighborEnabled ? '' : 'none';
    if (!neighborEnabled) {
        clearNeighborOverlay();
        const panel = document.getElementById('neighbor-explorer-panel');
        if (panel) panel.style.display = 'none';
        return;
    }
    refreshNeighborOverlay();
}

function onNeighborFiltersChanged() {
    updateNeighborMetricHint();
    if (neighborEnabled && !NEIGHBOR_ONLY_MODE) refreshNeighborOverlay();
}

function _neighborPanelUnavailable(reason) {
    const panel = document.getElementById('neighbor-explorer-panel');
    if (!panel) return;
    panel.style.display = 'block';
    panel.innerHTML = `<div class="site-meta-row">${escapeHtml(reason)}</div>`;
}

function toggleNeighborExplorer() {
    if (!neighborEnabled) {
        clearNeighborOverlay();
        const panel = document.getElementById('neighbor-explorer-panel');
        if (panel) panel.style.display = 'none';
        return;
    }
    if (NEIGHBOR_ONLY_MODE) {
        _neighborPanelIdle();
        return;
    }
    refreshNeighborOverlay();
}

async function refreshNeighborOverlay() {
    if (!neighborEnabled) return;
    const vendor = document.getElementById('vendor-filter')?.value || 'all';
    if (NEIGHBOR_ONLY_MODE) {
        _syncActiveTechFromNeighborRatSelect();
    }
    if (activeTech === 'all') {
        showNotification('Select a technology (RAT) for Neighbor Explorer', 'info');
        clearNeighborOverlay();
        _neighborPanelUnavailable('Select vendor and technology (RAT), then choose a site or cell.');
        return;
    }
    const minEl = document.getElementById('neighbor-min-attempts');
    const minRaw = Number(minEl?.value);
    const minFilterValue = Number.isFinite(minRaw)
        ? minRaw
        : (_neighborFailuresMode() ? 1 : 10);
    const maxLines = Number(document.getElementById('neighbor-max-lines')?.value || 300);
    const qs = new URLSearchParams();
    qs.set('vendor', vendor);
    qs.set('technology', activeTech);
    qs.set('max_lines', String(Number.isFinite(maxLines) ? Math.max(10, maxLines) : 300));
    if (selectedSiteId) qs.set('site_id', selectedSiteId);
    if (selectedNeighborCell) qs.set('cell_name', selectedNeighborCell);
    if (_neighborFailuresMode()) {
        qs.set('failures_only', '1');
        const mf = Number.isFinite(minRaw) ? Math.max(0, minRaw) : 1;
        qs.set('min_failures', String(mf));
    } else {
        const ma = Number.isFinite(minRaw) ? Math.max(0, minRaw) : 10;
        qs.set('min_attempts', String(ma));
    }

    try {
        const res = await fetch(`/api/network-map/neighbors/lines?${qs.toString()}`);
        let data;
        try {
            data = await res.json();
        } catch (_) {
            throw new Error(res.ok ? 'Invalid JSON from server' : `HTTP ${res.status}`);
        }
        if (!data.success) throw new Error(data.error || 'neighbors lines failed');
        neighborLineData = Array.isArray(data.lines) ? data.lines : [];
        renderNeighborLines(neighborLineData);
        await refreshNeighborWedgePresentation();
        await renderNeighborExplorerPanel(vendor, activeTech, data.period_start, minFilterValue, Boolean(data.raw_neighbor_tables));
        if (data.skipped_missing_coords > 0) {
            showNotification(
                `Neighbor Explorer: skipped ${data.skipped_missing_coords} row(s) — could not resolve both ends to cells with coordinates in metadata (ID/name/ECI mismatch or inactive cells).`,
                'info'
            );
        }
    } catch (e) {
        console.error('Neighbor lines error:', e);
        showNotification('Failed to load neighbor lines', 'error');
    }
}

async function refreshNeighborWedgePresentation() {
    if (!neighborEnabled || !map) return;
    clearSectorLayers();
    wedgeGroups = {};

    const norm = (n) => String(n || '').trim().toLowerCase().replace(/\s+/g, ' ');

    /** Wedges for every cell a neighbor line touches (source + target), including remote sites. */
    if (neighborLineData.length > 0) {
        const nameSet = new Set();
        if (selectedNeighborCell) nameSet.add(norm(selectedNeighborCell));
        neighborLineData.forEach((ln) => {
            nameSet.add(norm(ln.source_cell));
            nameSet.add(norm(ln.target_cell));
        });
        const names = [...nameSet].filter(Boolean).slice(0, 280);
        if (!names.length) return;
        const qs = new URLSearchParams();
        qs.set('technology', activeTech);
        names.forEach((n) => qs.append('cell', n));
        try {
            const res = await fetch(`/api/map/cells/wedge-data?${qs.toString()}`);
            const data = await res.json();
            if (!data.success || !Array.isArray(data.cells)) return;
            data.cells.forEach((row, idx) => {
                const la = Number(row.latitude);
                const lo = Number(row.longitude);
                if (!Number.isFinite(la) || !Number.isFinite(lo)) return;
                const siteStub = {
                    site_id: row.site_id,
                    site_name: row.site_name || row.cell_name,
                    latitude: la,
                    longitude: lo,
                };
                const az = row.azimuth != null ? Number(row.azimuth) : null;
                const group = {
                    groupId: `nbr-${idx}-${String(row.cell_name || '').replace(/\W+/g, '_')}`,
                    azimuth: Number.isFinite(az) ? az : 0,
                    technology: row.technology,
                    cells: [{
                        cell_name: row.cell_name,
                        technology: row.technology,
                        vendor: row.vendor,
                        frequency_band: row.frequency_band,
                        pci: row.pci,
                        activity_status: row.activity_status,
                        status: row.status,
                        azimuth: row.azimuth,
                        mechanical_tilt: row.mechanical_tilt,
                        electrical_tilt: row.electrical_tilt,
                    }],
                };
                drawSectorWedge(siteStub, group);
            });
        } catch (e) {
            console.error('wedge-data error:', e);
        }
        return;
    }

    if (lastNeighborSiteContext) {
        const { site, wedgeCells } = lastNeighborSiteContext;
        const groups = _groupCellsIntoWedges(site, wedgeCells);
        groups.forEach(g => drawSectorWedge(site, g));
    }
}

function renderNeighborLines(lines) {
    if (!neighborLinesLayer) return;
    neighborLinesLayer.clearLayers();
    const offM = Math.max(40, SECTOR_RADIUS_M * 0.55);
    const arr = Array.isArray(lines) ? lines : [];
    const fo = _neighborFailuresMode();
    const maxAttempts = arr.reduce((mx, ln) => {
        const a = fo ? Number(ln.ho_failures) : Number(ln.ho_attempts);
        return Number.isFinite(a) && a > 0 ? Math.max(mx, a) : mx;
    }, 0);
    arr.forEach((ln) => {
        const laS = Number(ln.source_lat);
        const loS = Number(ln.source_lng);
        const laT = Number(ln.target_lat);
        const loT = Number(ln.target_lng);
        if (!Number.isFinite(laS) || !Number.isFinite(loS) || !Number.isFinite(laT) || !Number.isFinite(loT)) {
            return;
        }
        const src = _neighborLineEndpoint(laS, loS, ln.source_azimuth, offM);
        const dst = _neighborLineEndpoint(laT, loT, ln.target_azimuth, offM);
        const poly = L.polyline([src, dst], {
            color: _neighborLineColor(ln),
            weight: _neighborLineWeight(
                fo ? (Number(ln.ho_failures) || 0) : ln.ho_attempts,
                maxAttempts,
            ),
            opacity: 0.72,
            pane: 'overlayPane',
        }).addTo(neighborLinesLayer);
        const sr = ln.ho_success_rate;
        const srText = (sr == null || !Number.isFinite(Number(sr))) ? '—' : `${Number(sr).toFixed(2)}%`;
        const hf = ln.ho_failures;
        const hfText = (hf == null || !Number.isFinite(Number(hf)))
            ? '—'
            : Math.trunc(Number(hf)).toLocaleString();
        const hfr = ln.ho_failure_rate_percent;
        const hfrText = (hfr == null || !Number.isFinite(Number(hfr))) ? '—' : `${Number(hfr).toFixed(2)}%`;
        const suc = ln.ho_successes;
        const relationScope = String(ln.relation_scope || '').toLowerCase();
        const relationLabel = relationScope === 'intra'
            ? 'Intra relation'
            : (relationScope === 'inter' ? 'Inter relation' : '');
        const metricsRows = fo
            ? `<tr><td style="color:#666;padding:4px 10px 4px 0;vertical-align:top;">Attempts</td>
                        <td style="font-weight:600;">${Number(ln.ho_attempts || 0).toLocaleString()}</td></tr>
                    <tr><td style="color:#666;padding:4px 10px 4px 0;vertical-align:top;">Est. failures</td>
                        <td style="font-weight:600;">${hfText}</td></tr>
                    <tr><td style="color:#666;padding:4px 10px 4px 0;vertical-align:top;">Failure rate</td>
                        <td style="font-weight:600;">${hfrText}</td></tr>`
            : `<tr><td style="color:#666;padding:4px 10px 4px 0;vertical-align:top;">Attempts</td>
                        <td style="font-weight:600;">${Number(ln.ho_attempts || 0).toLocaleString()}</td></tr>
                    ${(suc != null && Number.isFinite(Number(suc)))
                ? `<tr><td style="color:#666;padding:4px 10px 4px 0;vertical-align:top;">Successes</td>
                        <td style="font-weight:600;">${Number(suc).toLocaleString(undefined, { maximumFractionDigits: 2 })}</td></tr>`
                : ''}
                    <tr><td style="color:#666;padding:4px 10px 4px 0;vertical-align:top;">Success rate</td>
                        <td style="font-weight:600;">${srText}</td></tr>`;
        const popupHtml = `
            <div style="font-size:12px;line-height:1.45;min-width:240px;font-family:sans-serif;">
                <div style="font-weight:700;margin-bottom:8px;color:#2c3e50;">Handover link</div>
                <table style="width:100%;border-collapse:collapse;font-size:12px;">
                    <tr><td style="color:#666;padding:4px 10px 4px 0;vertical-align:top;">Source</td>
                        <td style="font-weight:600;">${escapeHtml(String(ln.source_cell || '—'))}</td></tr>
                    <tr><td style="color:#666;padding:4px 10px 4px 0;vertical-align:top;">Target</td>
                        <td style="font-weight:600;">${escapeHtml(String(ln.target_cell || '—'))}</td></tr>
                    ${relationLabel ? `<tr><td style="color:#666;padding:4px 10px 4px 0;vertical-align:top;">Relation</td>
                        <td style="font-weight:600;">${escapeHtml(relationLabel)}</td></tr>` : ''}
                    ${metricsRows}
                </table>
            </div>`;
        poly.bindPopup(popupHtml, { maxWidth: 320 });
    });
}

async function renderNeighborExplorerPanel(vendor, technology, periodStart, minAttempts, rawNeighborTables = false) {
    const panel = document.getElementById('neighbor-explorer-panel');
    if (!panel) return;
    panel.style.display = 'block';
    if (!selectedNeighborCell) {
        panel.innerHTML = `
            <div class="site-meta-row">Select a cell for outgoing/incoming ranking.</div>
            <div class="site-meta-row">Lines on map: ${neighborLineData.length}</div>`;
        return;
    }
    if (rawNeighborTables) {
        const cellKey = String(selectedNeighborCell || '').trim().toLowerCase();
        const rows = neighborLineData
            .filter((ln) => String(ln.source_cell || '').trim().toLowerCase() === cellKey)
            .slice(0, 10);
        const mkRows = (items) => items.length
            ? items.map((r) => {
                const rel = String(r.relation_scope || '').toLowerCase();
                const relText = rel === 'intra' ? ' · intra' : (rel === 'inter' ? ' · inter' : '');
                return `
                <div class="neighbor-row">
                    <div class="neighbor-row-name">${escapeHtml(r.target_cell || '')}${relText}</div>
                    <div class="neighbor-row-attempts">${Number(r.ho_attempts || 0).toLocaleString()}</div>
                    <div class="neighbor-row-rate">${r.ho_success_rate == null ? '—' : Number(r.ho_success_rate).toFixed(1) + '%'}</div>
                </div>`;
            }).join('')
            : '<div class="site-meta-row">No outgoing rows in current scope.</div>';
        panel.innerHTML = `
            <div class="neighbor-subtitle">
                Cell: <strong>${escapeHtml(selectedNeighborCell)}</strong>
            </div>
            <div class="neighbor-list-head">Outgoing neighbors</div>
            ${mkRows(rows)}
            <div class="site-meta-row">Relation flag: intra when source and target eNB/site are the same.</div>`;
        return;
    }
    const qs = new URLSearchParams({
        vendor,
        technology,
        cell_name: selectedNeighborCell,
        top_n: '10',
        min_attempts: String(Math.max(0, Number(minAttempts) || 0)),
    });
    try {
        const res = await fetch(`/api/network-map/neighbors/cell-summary?${qs.toString()}`);
        const data = await res.json();
        if (!data.success) throw new Error(data.error || 'cell summary failed');
        const outgoing = data.outgoing || [];
        const incoming = data.incoming || [];
        const mkRows = (rows) => rows.length
            ? rows.map((r) => `
                <div class="neighbor-row">
                    <div class="neighbor-row-name">${escapeHtml(r.neighbor_cell)}</div>
                    <div class="neighbor-row-attempts">${Number(r.ho_attempts || 0).toLocaleString()}</div>
                    <div class="neighbor-row-rate">${r.ho_success_rate == null ? '—' : Number(r.ho_success_rate).toFixed(1) + '%'}</div>
                </div>
            `).join('')
            : '<div class="site-meta-row">No rows in current scope.</div>';
        panel.innerHTML = `
            <div class="neighbor-subtitle">
                Cell: <strong>${escapeHtml(selectedNeighborCell)}</strong>
            </div>
            <div class="neighbor-list-head">Outgoing neighbors</div>
            ${mkRows(outgoing)}
            <div class="neighbor-list-head">Incoming neighbors</div>
            ${mkRows(incoming)}`;
    } catch (e) {
        panel.innerHTML = '<div class="site-meta-row" style="color:#e74c3c;">Failed to load cell summary.</div>';
    }
}

function clearCodeSearch() {
    document.getElementById('cell-code-search').value = '';
    clearHighlights();
    document.getElementById('site-info-panel').style.display = 'none';
}

/** Returns the human label for the active-tech code type. */
function _codeLabel() {
    if (activeTech === '3G-3G' || activeTech === '3G') return 'SC';
    if (
        activeTech === '4G-4G' ||
        activeTech === '4G-4G Intra-eNB' || activeTech === '4G-4G Inter-eNB' ||
        activeTech === '4G-4G Intra' || activeTech === '4G-4G Inter' ||
        activeTech === '4G-FDD' || activeTech === '4G-TDD' || activeTech === '5G'
    ) return 'PCI';
    if (activeTech === '2G-2G' || activeTech === '2G') return 'BCCH';
    return 'Code';
}

// ─── Filter builders ──────────────────────────────────────────────────────────

function buildClusterFilter(sites) {
    const select  = document.getElementById('cluster-filter');
    const current = select.value;
    const selectedArea = document.getElementById('area-filter')?.value || 'all';
    const scopedSites = selectedArea === 'all' ? sites : sites.filter(s => s.area === selectedArea);
    const clusters = [...new Set(scopedSites.map(s => s.cluster).filter(c => c != null))]
        .sort((a, b) => a - b);

    select.innerHTML = '<option value="all">All Clusters</option>';
    clusters.forEach(c => {
        const opt = document.createElement('option');
        opt.value = String(c);
        opt.textContent = `Cluster ${c}`;
        if (String(c) === current) opt.selected = true;
        select.appendChild(opt);
    });
    if (current !== 'all' && !clusters.some(c => String(c) === current)) {
        select.value = 'all';
    }
}

function buildAreaFilter(sites) {
    const select  = document.getElementById('area-filter');
    const current = select.value;
    const areas = [...new Set(sites.map(s => s.area).filter(Boolean))].sort();

    select.innerHTML = '<option value="all">All Areas</option>';
    areas.forEach(a => {
        const opt = document.createElement('option');
        opt.value = a;
        opt.textContent = a;
        if (a === current) opt.selected = true;
        select.appendChild(opt);
    });
}

// ─── Filter callbacks (all funnel into runFilters) ────────────────────────────

function searchSites() {
    if (!sitesData.length) {
        loadNetworkSites();
        return;
    }
    runFilters();
}

function filterByVendor() {
    if (NEIGHBOR_ONLY_MODE) {
        rebuildNeighborRatSelectForExportVendor();
        if (neighborEnabled) {
            clearNeighborOverlay();
            void (async () => {
                await updateTechSpecificFilter();
                await refreshNeighborWedgePresentation();
            })();
        }
    }
    if (!sitesData.length) {
        loadNetworkSites();
        return;
    }
    runFilters();
}

function filterByArea() {
    if (!sitesData.length) {
        loadNetworkSites();
        return;
    }
    buildClusterFilter(sitesData);
    runFilters();
}

function filterByCluster() {
    if (!sitesData.length) {
        loadNetworkSites();
        return;
    }
    runFilters();
}

// ─── Metadata refresh ────────────────────────────────────────────────────────

async function refreshMetadata() {
    const btn = document.getElementById('refresh-btn');
    btn.disabled = true;
    btn.textContent = '↻ Syncing…';

    try {
        const res  = await fetch('/api/map/refresh', { method: 'POST' });
        const data = await res.json();

        if (data.success) {
            btn.textContent = '✓ Started — reloading in 15 s…';
            // Give the background sync time to download + process files,
            // then automatically reload the map data.
            setTimeout(async () => {
                await loadNetworkStats();
                await loadNetworkSites();
                btn.textContent = '↻ Refresh Data';
                btn.disabled = false;
            }, 15000);
        } else {
            btn.textContent = '✗ Failed: ' + (data.error || 'unknown');
            setTimeout(() => {
                btn.textContent = '↻ Refresh Data';
                btn.disabled = false;
            }, 4000);
        }
    } catch (e) {
        btn.textContent = '✗ Error';
        setTimeout(() => {
            btn.textContent = '↻ Refresh Data';
            btn.disabled = false;
        }, 3000);
    }
}

// ─── Measuring tool ───────────────────────────────────────────────────────────

function toggleMeasure() {
    measureActive = !measureActive;
    const btn = document.getElementById('measure-btn');
    if (measureActive) {
        btn.classList.add('active');
        btn.textContent = '✕ Stop Measuring';
        map.getContainer().style.cursor = 'crosshair';
        map.on('click', onMeasureClick);
    } else {
        btn.classList.remove('active');
        btn.textContent = '📏 Measure Distance';
        map.getContainer().style.cursor = '';
        map.off('click', onMeasureClick);
        clearMeasure();
    }
}

function onMeasureClick(e) {
    measurePoints.push(e.latlng);

    const pt = L.circleMarker(e.latlng, {
        radius: 5, color: '#e74c3c', fillColor: '#fff',
        fillOpacity: 1, weight: 2.5
    }).addTo(map);
    measurePtMarkers.push(pt);

    if (measurePoints.length < 2) return;

    // Redraw polyline through all points
    if (measurePolyline) map.removeLayer(measurePolyline);
    measurePolyline = L.polyline(measurePoints, {
        color: '#e74c3c', weight: 2, dashArray: '7,5', opacity: 0.85
    }).addTo(map);

    // Accumulate total distance
    let totalM = 0;
    for (let i = 1; i < measurePoints.length; i++) {
        totalM += measurePoints[i - 1].distanceTo(measurePoints[i]);
    }
    const distText = totalM >= 1000
        ? `${(totalM / 1000).toFixed(2)} km`
        : `${Math.round(totalM)} m`;

    // Segment distance for last segment
    const segM     = measurePoints[measurePoints.length - 2]
                        .distanceTo(measurePoints[measurePoints.length - 1]);
    const segText  = segM >= 1000
        ? `+${(segM / 1000).toFixed(2)} km`
        : `+${Math.round(segM)} m`;

    // Move/update total label to last point
    if (measureDistLabel) map.removeLayer(measureDistLabel);
    measureDistLabel = L.marker(e.latlng, {
        icon: L.divIcon({
            className: 'measure-label-icon',
            html: `<div class="measure-tooltip">
                       <span class="measure-total">${distText}</span>
                       <span class="measure-seg">${segText}</span>
                   </div>`,
            iconAnchor: [-8, 10]
        }),
        interactive: false,
        zIndexOffset: 1000
    }).addTo(map);
}

function clearMeasure() {
    measurePtMarkers.forEach(m => map && map.removeLayer(m));
    measurePtMarkers = [];
    if (measurePolyline)  { map.removeLayer(measurePolyline);  measurePolyline  = null; }
    if (measureDistLabel) { map.removeLayer(measureDistLabel); measureDistLabel = null; }
    measurePoints = [];
}

// Close modal on backdrop click
window.addEventListener('click', e => {
    if (e.target === document.getElementById('kpi-modal')) closeKPIModal();
});

window.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeKPIModal();
});

window.addEventListener('pageshow', e => {
    if (e.persisted) closeKPIModal();
});

// ─── Export (Excel / KML) ────────────────────────────────────────────────────
function exportCurrentView(format) {
    const tech   = activeTech !== 'all' ? activeTech : '';
    const vendor = document.getElementById('vendor-filter').value;
    const search = document.getElementById('site-search').value.trim();

    const params = new URLSearchParams();
    if (tech)             params.set('tech',   tech);
    if (activeTechSpecific !== 'all') params.set('tech_value', activeTechSpecific);
    if (vendor !== 'all') params.set('vendor', vendor);
    if (search)           params.set('search', search);

    const endpoint = format === 'kml'
        ? `/api/map/export/kml?${params}`
        : `/api/map/export/sites?${params}`;

    window.location.href = endpoint;
}

// ─── Wedge grouping ───────────────────────────────────────────────────────────

function _azBucket(az) {
    // bucket azimuth into 5° bins so co-sector cells combine into one wedge
    const a = Number(az);
    if (!Number.isFinite(a)) return null;
    return Math.round(a / 5) * 5;
}

function _groupCellsIntoWedges(site, cells) {
    // Reset wedgeGroups whenever we redraw site wedges
    wedgeGroups = {};

    const byKey = {};
    cells
        .filter(c => c && c.azimuth != null && Number.isFinite(Number(c.azimuth)))
        .forEach(c => {
            const tech = c.technology || 'Unknown';
            const bucket = _azBucket(c.azimuth);
            const key = `${site.site_id}|${tech}|${bucket}`;
            if (!byKey[key]) byKey[key] = { technology: tech, azimuth: bucket, cells: [] };
            byKey[key].cells.push(c);
        });

    const groups = Object.values(byKey);
    // Stable order: technology then azimuth then cell_name
    groups.sort((a, b) => {
        if (a.technology !== b.technology) return String(a.technology).localeCompare(String(b.technology));
        if (a.azimuth !== b.azimuth) return Number(a.azimuth) - Number(b.azimuth);
        return String(a.cells?.[0]?.cell_name || '').localeCompare(String(b.cells?.[0]?.cell_name || ''));
    });

    // Attach group ids
    groups.forEach((g, idx) => {
        g.groupId = `${site.site_id}-${g.technology}-${g.azimuth}-${idx}`;
        // Sort cells in the popup list for readability
        g.cells.sort((x, y) => String(x.cell_name).localeCompare(String(y.cell_name)));
    });

    return groups;
}

// ─── Empty state + filter wiring ──────────────────────────────────────────────

function _hasActiveFilters() {
    const term    = (document.getElementById('site-search')?.value || '').trim();
    const vendor  = document.getElementById('vendor-filter')?.value || 'all';
    const area    = document.getElementById('area-filter')?.value || 'all';
    const cluster = document.getElementById('cluster-filter')?.value || 'all';
    const code    = (document.getElementById('cell-code-search')?.value || '').trim();
    const techSpecific = document.getElementById('tech-specific-filter')?.value || 'all';
    const lat     = (document.getElementById('coord-lat')?.value || '').trim();
    const lng     = (document.getElementById('coord-lng')?.value || '').trim();

    return Boolean(
        activeTech !== 'all' ||
        vendor !== 'all' ||
        area !== 'all' ||
        cluster !== 'all' ||
        techSpecific !== 'all' ||
        term ||
        code ||
        (lat && lng)
    );
}

async function updateTechSpecificFilter() {
    const select = document.getElementById('tech-specific-filter');
    if (!select) return;

    // Only show for requested technologies.
    const apiTech =
        activeTech === '2G-2G' ? '2G' :
        activeTech === '3G-3G' ? '3G' :
        (activeTech === '4G-4G' ||
         activeTech === '4G-4G Intra-eNB' || activeTech === '4G-4G Inter-eNB' ||
         activeTech === '4G-4G Intra' || activeTech === '4G-4G Inter') ? '4G-FDD' :
        activeTech;
    if (!['2G', '3G', '4G-FDD', '4G-TDD'].includes(apiTech)) {
        select.style.display = 'none';
        select.innerHTML = '<option value="all">All</option>';
        activeTechSpecific = 'all';
        return;
    }

    try {
        const res = await fetch(`/api/map/tech-filter-options?tech=${encodeURIComponent(apiTech)}`);
        const data = await res.json();
        if (!data.success) throw new Error(data.error || 'Failed to load filter values');

        const label = data.label || 'Value';
        const values = Array.isArray(data.values) ? data.values : [];
        select.innerHTML = `<option value="all">All ${label}</option>` +
            values.map(v => `<option value="${String(v)}">${String(v)}</option>`).join('');
        select.style.display = 'block';
        select.value = 'all';
        activeTechSpecific = 'all';
    } catch (e) {
        console.error('Tech-specific filter error:', e);
        select.style.display = 'none';
        select.innerHTML = '<option value="all">All</option>';
        activeTechSpecific = 'all';
    }
}

function filterByTechSpecific() {
    const select = document.getElementById('tech-specific-filter');
    activeTechSpecific = (select?.value || 'all').trim() || 'all';
    _onFilterChanged(false, true);
}

function _showEmptyState() {
    if (showRepeaters && repeaterData.length) {
        _updateMapCountLabel(0, repeaterData.length);
        return;
    }
    const sitesCountEl = document.getElementById('sites-count');
    if (sitesCountEl) sitesCountEl.textContent = '0';
    const panel = document.getElementById('site-info-panel');
    if (!panel) return;
    if (NEIGHBOR_ONLY_MODE) {
        panel.innerHTML = `
        <div style="color:#2c3e50;font-weight:800;margin-bottom:6px;">Neighbor Analysis</div>
        <div style="color:#555;font-size:0.88em;line-height:1.6;">
            Search or filter sites, open a site, choose export vendor and RAT, then use <strong>Draw relations</strong> on a cell in the site list to plot handovers.
        </div>
    `;
    } else {
        panel.innerHTML = `
        <div style="color:#2c3e50;font-weight:800;margin-bottom:6px;">Map is ready</div>
        <div style="color:#555;font-size:0.88em;line-height:1.6;">
            Select <strong>Technology</strong>, <strong>Vendor</strong>, <strong>Area</strong> or <strong>Cluster</strong>
            (or use <strong>SC/PCI/BCCH</strong> search) to load sites.
            Or enable <strong>Show repeaters</strong> to plot all repeater devices on the map.
        </div>
    `;
    }
    panel.style.display = 'block';
}

function _wireInitialFilterListeners() {
    // UI controls already use inline handlers (onchange / onkeyup),
    // so keep this as a no-op to avoid duplicate requests.
}

let _filterDebounce = null;
function _onFilterChanged(isTyping = false, forceServerReload = false) {
    // Clear selections when filters change
    clearSectorLayers();
    clearHighlights();
    clearNeighborOverlay();
    selectedNeighborCell = '';
    selectedSiteId = null;
    lastNeighborSiteContext = null;
    document.getElementById('site-info-panel').style.display = 'none';

    if (isTyping) {
        clearTimeout(_filterDebounce);
        _filterDebounce = setTimeout(() => {
            if (forceServerReload) {
                sitesData = [];
                lastLoadedScopeKey = '';
            }
            loadNetworkSites();
        }, 250);
        return;
    }
    if (forceServerReload) {
        sitesData = [];
        lastLoadedScopeKey = '';
        repeaterData = [];
        repeatersLoaded = false;
    }
    loadNetworkSites();
}

// ─── Coordinate search (lat/lng) ──────────────────────────────────────────────

function goToCoordinates() {
    const lat = parseFloat(document.getElementById('coord-lat')?.value);
    const lng = parseFloat(document.getElementById('coord-lng')?.value);
    if (!Number.isFinite(lat) || !Number.isFinite(lng)) {
        showNotification('Enter valid latitude & longitude', 'error');
        return;
    }
    if (!map) return;

    // Pan/zoom and drop a marker
    map.setView([lat, lng], Math.max(map.getZoom(), 14));
    if (coordMarker) map.removeLayer(coordMarker);
    coordMarker = L.marker([lat, lng]).addTo(map);
    coordMarker.bindPopup(`
        <div style="font-weight:700;">📍 Coordinate</div>
        <div>${lat.toFixed(6)}, ${lng.toFixed(6)}</div>
        <div>Elevation: <span id="coord-elevation-value">loading...</span></div>
    `).openPopup();
    fillElevationText('coord-elevation-value', lat, lng);

    // If sites are not loaded yet, load them (filters now active via lat/lng)
    if (!sitesData.length) {
        loadNetworkSites();
    }
}

function showNearestSitesFromCoordinates() {
    const lat = parseFloat(document.getElementById('coord-lat')?.value);
    const lng = parseFloat(document.getElementById('coord-lng')?.value);
    if (!Number.isFinite(lat) || !Number.isFinite(lng)) {
        showNotification('Enter valid latitude & longitude first', 'error');
        return;
    }
    if (!sitesData.length) {
        showNotification('Load sites first by applying a filter', 'info');
        return;
    }

    // Highlight nearest sites (top 10 within 10km) only on explicit user request.
    const target = L.latLng(lat, lng);
    const withinKm = 10;
    const nearest = sitesData
        .map(s => ({ s, d: target.distanceTo([s.latitude, s.longitude]) / 1000 }))
        .filter(x => Number.isFinite(x.d))
        .sort((a, b) => a.d - b.d)
        .slice(0, 10)
        .filter(x => x.d <= withinKm);

    if (!nearest.length) {
        showNotification(`No sites within ${withinKm} km`, 'info');
        return;
    }

    // Render only the nearest sites as markers (temporary view)
    displaySites(nearest.map(x => x.s));
    const panel = document.getElementById('site-info-panel');
    panel.innerHTML = `
        <h3 class="site-panel-title">📍 Nearest sites</h3>
        <div class="site-meta-row">Showing ${nearest.length} within ${withinKm} km</div>
        ${nearest.map(x => `
          <div class="cell-row" onclick="showSiteDetails('${x.s.site_id}')">
            <span class="cell-name">${x.s.site_name}</span>
            <span class="cell-meta">${x.d.toFixed(2)} km</span>
          </div>
        `).join('')}
    `;
    panel.style.display = 'block';
}

// ─── Saved views adapter (snapshot + restore filter/UI state) ────────────────

function _val(id) {
    const el = document.getElementById(id);
    return el ? String(el.value || '') : '';
}

function _setIfExists(id, value) {
    const el = document.getElementById(id);
    if (el && value != null) el.value = value;
}

/**
 * Capture all user-controlled filter / map state required to reproduce the
 * current network-map view. Kept intentionally small (under a few KB) so the
 * blob stays well within the saved_views payload limit on the server.
 */
function getNetworkMapState() {
    const state = {
        v: 1,
        activeTech: activeTech,
        activeTechSpecific: activeTechSpecific,
        siteSearch: _val('site-search'),
        coordLat: _val('coord-lat'),
        coordLng: _val('coord-lng'),
        cellCodeSearch: _val('cell-code-search'),
        vendor: _val('vendor-filter') || 'all',
        area: _val('area-filter') || 'all',
        cluster: _val('cluster-filter') || 'all',
        techSpecific: _val('tech-specific-filter') || 'all',
        showRepeaters: Boolean(document.getElementById('show-repeaters')?.checked),
        selectedSiteId: typeof selectedSiteId !== 'undefined' ? selectedSiteId : null,
    };
    try {
        if (map) {
            const c = map.getCenter();
            state.mapCenter = [c.lat, c.lng];
            state.mapZoom = map.getZoom();
        }
    } catch (_) { /* ignore */ }
    return state;
}

/**
 * Apply a previously captured map state. Reloads sites once at the end so
 * that filters take effect against fresh server data.
 */
async function applyNetworkMapState(state /* , opts */) {
    if (!state || typeof state !== 'object') return;

    if (state.activeTech) {
        try { await setTechFilter(state.activeTech); } catch (_) { /* ignore */ }
    }

    _setIfExists('vendor-filter', state.vendor || 'all');
    _setIfExists('area-filter', state.area || 'all');
    // Cluster list depends on area, so rebuild it before assigning.
    if (sitesData && sitesData.length) {
        try { buildClusterFilter(sitesData); } catch (_) { /* ignore */ }
    }
    _setIfExists('cluster-filter', state.cluster || 'all');
    _setIfExists('site-search', state.siteSearch || '');
    _setIfExists('coord-lat', state.coordLat || '');
    _setIfExists('coord-lng', state.coordLng || '');
    _setIfExists('cell-code-search', state.cellCodeSearch || '');

    if (state.activeTechSpecific) activeTechSpecific = state.activeTechSpecific;
    _setIfExists('tech-specific-filter', state.techSpecific || 'all');

    showRepeaters = Boolean(state.showRepeaters);
    const repCb = document.getElementById('show-repeaters');
    if (repCb) repCb.checked = showRepeaters;

    // Trigger server reload now that all filters are restored.
    try {
        sitesData = [];
        lastLoadedScopeKey = '';
        repeaterData = [];
        repeatersLoaded = false;
        await loadNetworkSites();
        if (showRepeaters) await loadRepeaters();
    } catch (_) { /* ignore */ }

    if (Array.isArray(state.mapCenter) && state.mapCenter.length === 2 && Number.isFinite(state.mapZoom)) {
        try {
            map.setView([Number(state.mapCenter[0]), Number(state.mapCenter[1])], Number(state.mapZoom));
        } catch (_) { /* ignore */ }
    }

    if (state.selectedSiteId) {
        try { showSiteDetails(state.selectedSiteId); } catch (_) { /* ignore */ }
    }
}

window.getNetworkMapState = getNetworkMapState;
window.applyNetworkMapState = applyNetworkMapState;
