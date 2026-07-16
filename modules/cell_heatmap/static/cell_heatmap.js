(function () {
    const DEFAULT_CENTER = [31.9539, 35.9106];
    const DEFAULT_ZOOM = 10;
    const SECTOR_BEAMWIDTH = 65;
    const SECTOR_RADIUS_M = 240;
    const AURA_BEAMWIDTH_EXTRA = 28;
    const AURA_RADIUS_SCALE = 1.38;
    const EARTH_R = 6378137;

    let map = null;
    let auraCanvas = null;
    let tooltipLayer = null;
    let poiLayer = null;
    const POI_KPI_WEIGHT = 0.55;
    let kpiPresets = [];
    let kpiAuraOpacity = 0.72;
    let kpiAuraBlurPx = 18;
    let lastDetails = [];
    let lastMeta = {};
    let lastBounds = null;
    let auraRedrawTimer = null;
    let sectorCache = [];
    let sectorBuckets = new Map();
    let kpiColorLut = null;

    function $(id) {
        return document.getElementById(id);
    }

    function setDrawerCollapsed(collapsed) {
        const drawer = $("ch-drawer");
        const btn = $("ch-drawer-toggle");
        if (!drawer || !btn) return;
        drawer.classList.toggle("collapsed", collapsed);
        btn.setAttribute("aria-expanded", collapsed ? "false" : "true");
    }

    function initDrawer() {
        const drawer = $("ch-drawer");
        const btn = $("ch-drawer-toggle");
        if (!btn || !drawer) return;
        const mq = window.matchMedia("(max-width: 720px)");
        const applyMq = () => {
            if (mq.matches) {
                setDrawerCollapsed(true);
            } else {
                setDrawerCollapsed(false);
            }
        };
        mq.addEventListener("change", applyMq);
        applyMq();
        btn.addEventListener("click", () => {
            setDrawerCollapsed(!drawer.classList.contains("collapsed"));
        });
    }

    function setStatus(kind, text) {
        const wrap = $("ch-status");
        const t = $("ch-status-text");
        if (!wrap || !t) return;
        wrap.classList.remove("loading", "ok", "err");
        if (kind) wrap.classList.add(kind);
        t.textContent = text;
    }

    function formatKpiValue(d, meta) {
        if (d.kpi_value == null || !Number.isFinite(Number(d.kpi_value))) return "n/a";
        const v = Number(d.kpi_value);
        const label = (meta && meta.kpi_label) || "";
        const key = (d.kpi_name || (meta && meta.kpi)) || "";
        if (key === "drop_rate" || /%/.test(label)) return v.toFixed(2) + "%";
        return v.toFixed(3);
    }

    function kpiWeight(d) {
        if (!d) return null;
        const w = d.kpi_weight != null ? d.kpi_weight : d.weight;
        if (w == null || w === "" || !Number.isFinite(Number(w))) return null;
        return Math.max(0, Math.min(1, Number(w)));
    }

    /** Survey-style gradient stops: t=0 good (green) → t=1 bad (red). */
    const KPI_GRADIENT_STOPS = [
        [0, [46, 204, 113]],
        [0.22, [88, 214, 122]],
        [0.42, [241, 196, 15]],
        [0.62, [243, 156, 18]],
        [0.8, [230, 126, 34]],
        [1, [231, 76, 60]],
    ];

    function kpiGradientRgb(t) {
        const n = Math.max(0, Math.min(1, Number(t)));
        for (let i = 1; i < KPI_GRADIENT_STOPS.length; i++) {
            const [p1, c1] = KPI_GRADIENT_STOPS[i - 1];
            const [p2, c2] = KPI_GRADIENT_STOPS[i];
            if (n <= p2) {
                const f = p2 > p1 ? (n - p1) / (p2 - p1) : 0;
                return [
                    Math.round(c1[0] + (c2[0] - c1[0]) * f),
                    Math.round(c1[1] + (c2[1] - c1[1]) * f),
                    Math.round(c1[2] + (c2[2] - c1[2]) * f),
                ];
            }
        }
        const last = KPI_GRADIENT_STOPS[KPI_GRADIENT_STOPS.length - 1][1];
        return last.slice();
    }

    function kpiGradientCss() {
        return KPI_GRADIENT_STOPS.map(([p, c]) => `rgb(${c[0]},${c[1]},${c[2]}) ${Math.round(p * 100)}%`).join(", ");
    }

    function kpiAuraColor(w) {
        const rgb = kpiGradientRgb(w);
        return `rgb(${rgb[0]},${rgb[1]},${rgb[2]})`;
    }

    function formatKpiLegendValue(v, meta) {
        if (v == null || !Number.isFinite(Number(v))) return "—";
        const n = Number(v);
        const label = (meta && meta.kpi_label) || "";
        const key = (meta && meta.kpi) || "";
        if (key === "drop_rate" || /%/.test(label)) return n.toFixed(2) + "%";
        return n.toFixed(3);
    }

    function hexToRgba(hex, alpha) {
        const h = String(hex || "").replace("#", "");
        if (h.length !== 6) return `rgba(39,174,96,${alpha})`;
        const r = parseInt(h.slice(0, 2), 16);
        const g = parseInt(h.slice(2, 4), 16);
        const b = parseInt(h.slice(4, 6), 16);
        return `rgba(${r},${g},${b},${alpha})`;
    }

    function destLatLng(lat, lng, bearingDeg, distM) {
        const br = (bearingDeg * Math.PI) / 180;
        const lat1 = (lat * Math.PI) / 180;
        const lng1 = (lng * Math.PI) / 180;
        const d = distM / EARTH_R;
        const lat2 = Math.asin(
            Math.sin(lat1) * Math.cos(d) + Math.cos(lat1) * Math.sin(d) * Math.cos(br),
        );
        const lng2 =
            lng1 +
            Math.atan2(
                Math.sin(br) * Math.sin(d) * Math.cos(lat1),
                Math.cos(d) - Math.sin(lat1) * Math.sin(lat2),
            );
        return [(lat2 * 180) / Math.PI, (lng2 * 180) / Math.PI];
    }

    function haversineM(lat1, lng1, lat2, lng2) {
        const toRad = (x) => (x * Math.PI) / 180;
        const dLat = toRad(lat2 - lat1);
        const dLng = toRad(lng2 - lng1);
        const a =
            Math.sin(dLat / 2) ** 2 +
            Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLng / 2) ** 2;
        return 2 * EARTH_R * Math.asin(Math.sqrt(a));
    }

    function bearingDeg(lat1, lng1, lat2, lng2) {
        const phi1 = (lat1 * Math.PI) / 180;
        const phi2 = (lat2 * Math.PI) / 180;
        const dLng = ((lng2 - lng1) * Math.PI) / 180;
        const y = Math.sin(dLng) * Math.cos(phi2);
        const x = Math.cos(phi1) * Math.sin(phi2) - Math.sin(phi1) * Math.cos(phi2) * Math.cos(dLng);
        return (Math.atan2(y, x) * (180 / Math.PI) + 360) % 360;
    }

    function angularDiff(a, b) {
        const d = Math.abs(a - b) % 360;
        return d > 180 ? 360 - d : d;
    }

    function sectorCoverInfl(lat, lng, s) {
        const dist = haversineM(s.lat, s.lng, lat, lng);
        if (dist > s.radius) return 0;

        if (!s.hasAz) {
            const t = 1 - dist / s.radius;
            return t * t;
        }

        const brg = bearingDeg(s.lat, s.lng, lat, lng);
        const ang = angularDiff(brg, s.az);
        if (ang > s.half) return 0;

        const radial = 1 - dist / s.radius;
        const beam = 1 - ang / s.half;
        return radial * beam;
    }

    const SECTOR_BUCKET_DEG = 0.012;

    function bucketKey(lat, lng) {
        return `${Math.floor(lat / SECTOR_BUCKET_DEG)},${Math.floor(lng / SECTOR_BUCKET_DEG)}`;
    }

    function rebuildSectorIndex() {
        sectorCache = [];
        sectorBuckets = new Map();
        for (const d of lastDetails) {
            const kw = kpiWeight(d);
            if (kw == null) continue;
            const lat = Number(d.latitude);
            const lng = Number(d.longitude);
            if (!Number.isFinite(lat) || !Number.isFinite(lng)) continue;
            const az = Number(d.azimuth);
            const s = {
                lat,
                lng,
                kw,
                kpiValue: d.kpi_value != null ? Number(d.kpi_value) : null,
                cellName: d.cell_name || "",
                az,
                radius: (Number(d.size_radius_m) || SECTOR_RADIUS_M) * AURA_RADIUS_SCALE,
                half: (SECTOR_BEAMWIDTH + AURA_BEAMWIDTH_EXTRA) / 2,
                hasAz: Number.isFinite(az),
            };
            sectorCache.push(s);
            const key = bucketKey(lat, lng);
            if (!sectorBuckets.has(key)) sectorBuckets.set(key, []);
            sectorBuckets.get(key).push(s);
        }
    }

    function cellsNearLatLng(lat, lng) {
        const bi = Math.floor(lat / SECTOR_BUCKET_DEG);
        const bj = Math.floor(lng / SECTOR_BUCKET_DEG);
        const out = [];
        for (let di = -1; di <= 1; di++) {
            for (let dj = -1; dj <= 1; dj++) {
                const list = sectorBuckets.get(`${bi + di},${bj + dj}`);
                if (list) out.push(...list);
            }
        }
        return out;
    }

    function buildKpiColorLut() {
        const lut = new Uint8ClampedArray(256 * 4);
        for (let i = 0; i < 256; i++) {
            const t = Math.pow(i / 255, 0.88);
            const rgb = kpiGradientRgb(t);
            const o = i * 4;
            lut[o] = rgb[0];
            lut[o + 1] = rgb[1];
            lut[o + 2] = rgb[2];
            lut[o + 3] = 255;
        }
        kpiColorLut = lut;
    }

    function cellTooltipHtml(d, meta) {
        const radius = Number(d.size_radius_m) || SECTOR_RADIUS_M;
        const kpiText = formatKpiValue(d, meta);
        const distText = d.avg_distance_m != null ? Number(d.avg_distance_m).toFixed(0) + " m" : "n/a";
        const radiusText = Number.isFinite(radius) ? Math.round(radius) + " m reach" : "n/a";
        const elev = Number(d.elevation_m);
        const elevText = Number.isFinite(elev) ? `${Math.round(elev)} m` : "unavailable";
        const site = d.site_name || d.site_id || "";
        const scope = [d.vendor, d.technology].filter(Boolean).join(" · ");
        return (
            `<div class="ch-tip"><b>${escapeHtml(d.cell_name || "")}</b>` +
            (site ? `<br><span class="ch-tip-sub">${escapeHtml(String(site))}</span>` : "") +
            (scope ? `<br><span class="ch-tip-sub">${escapeHtml(scope)}</span>` : "") +
            `<br>Coverage reach: ${escapeHtml(radiusText)}` +
            `<br>${escapeHtml((meta && meta.kpi_label) || "KPI")}: ${escapeHtml(kpiText)}` +
            `<br>Elevation: ${escapeHtml(elevText)}` +
            `<br>UE distance: ${escapeHtml(distText)}</div>`
        );
    }

    function normalizeSizeWeight(radiusM, minR, maxR) {
        const r = Number(radiusM);
        if (!Number.isFinite(r)) return null;
        const lo = Number(minR);
        const hi = Number(maxR);
        if (!Number.isFinite(lo) || !Number.isFinite(hi)) return null;
        const span = hi - lo;
        if (span < 1e-6) return 0.5;
        return Math.max(0, Math.min(1, (r - lo) / span));
    }

    function enrichDetailsWithSizeWeights(details, meta) {
        const rows = Array.isArray(details) ? details : [];
        if (!rows.length) return [];

        let minR = meta && meta.size_min_m != null ? Number(meta.size_min_m) : NaN;
        let maxR = meta && meta.size_max_m != null ? Number(meta.size_max_m) : NaN;
        if (!Number.isFinite(minR) || !Number.isFinite(maxR)) {
            const radii = rows.map((d) => Number(d.size_radius_m)).filter((v) => Number.isFinite(v));
            if (radii.length) {
                minR = Math.min(...radii);
                maxR = Math.max(...radii);
            } else {
                minR = SECTOR_RADIUS_M;
                maxR = SECTOR_RADIUS_M;
            }
        }

        return rows.map((d) => {
            const copy = { ...d };
            let sw = copy.size_weight;
            if (sw == null || sw === "" || !Number.isFinite(Number(sw))) {
                const radius = Number(copy.size_radius_m);
                sw = Number.isFinite(radius)
                    ? normalizeSizeWeight(radius, minR, maxR)
                    : normalizeSizeWeight(SECTOR_RADIUS_M, minR, maxR);
            } else {
                sw = Math.max(0, Math.min(1, Number(sw)));
            }
            copy.size_weight = sw;
            if (!Number.isFinite(Number(copy.size_radius_m))) {
                copy.size_radius_m = SECTOR_RADIUS_M;
            }
            return copy;
        });
    }

    function initMap() {
        map = L.map("heatmap-map", { zoomControl: true, attributionControl: true }).setView(DEFAULT_CENTER, DEFAULT_ZOOM);
        map.zoomControl.setPosition("topright");

        const osmLight = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
            attribution: "&copy; OpenStreetMap",
            maxZoom: 19,
        });
        const dark = L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
            attribution: "&copy; OpenStreetMap &copy; CARTO",
            maxZoom: 19,
        });
        const satellite = L.tileLayer(
            "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
            { attribution: "Esri", maxZoom: 19 },
        );

        osmLight.addTo(map);
        L.control
            .layers(
                { Street: osmLight, "Dark (CARTO)": dark, Satellite: satellite },
                {},
                { position: "topright", collapsed: true },
            )
            .addTo(map);
        L.control.scale({ imperial: false, metric: true }).addTo(map);

        auraCanvas = L.DomUtil.create("canvas", "leaflet-layer ch-kpi-aura-canvas");
        map.getPanes().overlayPane.appendChild(auraCanvas);
        bindAuraMapEvents();
        updateAuraCanvasStyle();
    }

    function bindAuraMapEvents() {
        map.on("dragstart", onAuraDragStart);
        map.on("moveend zoomend resize viewreset", () => {
            scheduleAuraRedraw();
            if (lastDetails.length) renderPoiMarkers(lastMeta);
        });
        if (map.options.zoomAnimation && L.Browser.any3d) {
            map.on("zoomanim", onAuraZoomAnim);
            map.on("zoomend", clearAuraZoomAnim);
        }
    }

    function onAuraDragStart() {
        if (auraCanvas) auraCanvas.style.filter = "none";
    }

    function positionAuraCanvas() {
        if (!map || !auraCanvas) return;
        const topLeft = map.containerPointToLayerPoint([0, 0]);
        L.DomUtil.setPosition(auraCanvas, topLeft);
    }

    function onAuraZoomAnim(ev) {
        if (!auraCanvas || typeof map._latLngToNewLayerPoint !== "function") return;
        const scale = map.getZoomScale(ev.zoom);
        const nw = map.containerPointToLayerPoint([0, 0]);
        const nwLatLng = map.layerPointToLatLng(nw);
        const offset = map._latLngToNewLayerPoint(nwLatLng, ev.zoom, ev.center);
        L.DomUtil.setTransform(auraCanvas, offset, scale);
    }

    function clearAuraZoomAnim() {
        if (!auraCanvas) return;
        L.DomUtil.setTransform(auraCanvas, { x: 0, y: 0 }, 1);
        positionAuraCanvas();
    }

    function updateAuraCanvasStyle() {
        if (!auraCanvas) return;
        auraCanvas.style.opacity = String(Math.min(1, kpiAuraOpacity));
        auraCanvas.style.filter = `blur(${kpiAuraBlurPx}px)`;
    }

    function scheduleAuraRedraw() {
        if (auraRedrawTimer) cancelAnimationFrame(auraRedrawTimer);
        auraRedrawTimer = requestAnimationFrame(() => {
            auraRedrawTimer = null;
            redrawMergedAura();
        });
    }

    function gridCellPx(zoom, nSectors) {
        let px = zoom >= 15 ? 5 : zoom >= 13 ? 6 : zoom >= 11 ? 8 : 10;
        if (nSectors > 8000) px += 3;
        else if (nSectors > 4000) px += 2;
        return px;
    }

    function redrawMergedAura() {
        if (!map || !auraCanvas || !sectorCache.length) return;
        if (!kpiColorLut) buildKpiColorLut();

        positionAuraCanvas();

        const size = map.getSize();
        const w = size.x;
        const h = size.y;
        const dpr = Math.min(window.devicePixelRatio || 1, 2);
        auraCanvas.width = Math.floor(w * dpr);
        auraCanvas.height = Math.floor(h * dpr);
        auraCanvas.style.width = w + "px";
        auraCanvas.style.height = h + "px";

        const ctx = auraCanvas.getContext("2d");
        const imageData = ctx.createImageData(w, h);
        const pixels = imageData.data;
        const lut = kpiColorLut;

        const zoom = map.getZoom();
        const cellPx = gridCellPx(zoom, sectorCache.length);
        const cols = Math.ceil(w / cellPx);
        const rows = Math.ceil(h / cellPx);
        const cxHalf = cellPx * 0.5;
        const wStride = w * 4;

        for (let gy = 0; gy < rows; gy++) {
            const cy = gy * cellPx + cxHalf;
            for (let gx = 0; gx < cols; gx++) {
                const cx = gx * cellPx + cxHalf;
                const ll = map.containerPointToLatLng(L.point(cx, cy));

                let cover = 0;
                let worstKw = 0;
                const nearby = cellsNearLatLng(ll.lat, ll.lng);
                for (let i = 0; i < nearby.length; i++) {
                    const infl = sectorCoverInfl(ll.lat, ll.lng, nearby[i]);
                    if (infl > cover) cover = infl;
                    if (infl > 0.1) worstKw = Math.max(worstKw, nearby[i].kw);
                }
                if (cover < 0.07) continue;

                const t = Math.min(1, Math.pow(worstKw, 0.85));
                const li = Math.min(255, (t * 255) | 0) * 4;
                const r = lut[li];
                const g = lut[li + 1];
                const b = lut[li + 2];
                const a = Math.round(
                    255 * kpiAuraOpacity * (0.2 + 0.45 * cover + 0.35 * t),
                );
                if (a < 12) continue;

                const x0 = gx * cellPx;
                const y0 = gy * cellPx;
                const xEnd = Math.min(x0 + cellPx, w);
                const yEnd = Math.min(y0 + cellPx, h);

                for (let py = y0; py < yEnd; py++) {
                    let idx = py * wStride + x0 * 4;
                    for (let px = x0; px < xEnd; px++) {
                        pixels[idx] = r;
                        pixels[idx + 1] = g;
                        pixels[idx + 2] = b;
                        pixels[idx + 3] = a;
                        idx += 4;
                    }
                }
            }
        }

        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.putImageData(imageData, 0, 0);
        updateAuraCanvasStyle();
    }

    function clearTooltipLayer() {
        if (tooltipLayer) {
            map.removeLayer(tooltipLayer);
            tooltipLayer = null;
        }
    }

    function clearPoiLayer() {
        if (poiLayer) {
            map.removeLayer(poiLayer);
            poiLayer = null;
        }
    }

    function renderPoiMarkers(meta) {
        clearPoiLayer();
        if (!sectorCache.length || !map) return;

        const zoom = map.getZoom();
        if (zoom < 11) return;

        let poiCells = sectorCache.filter((s) => s.kw >= POI_KPI_WEIGHT);
        if (poiCells.length > 350) {
            poiCells = poiCells.sort((a, b) => b.kw - a.kw).slice(0, 350);
        }

        poiLayer = L.layerGroup().addTo(map);
        for (let i = 0; i < poiCells.length; i++) {
            const s = poiCells[i];

            const kpiText =
                s.kpiValue != null && Number.isFinite(s.kpiValue)
                    ? formatKpiLegendValue(s.kpiValue, meta)
                    : (s.kw * 100).toFixed(0) + "% of bad";
            const title =
                `<div class="ch-tip ch-tip-poi"><b>${escapeHtml(s.cellName || "Cell")}</b>` +
                `<br><span class="ch-tip-poi-val">${escapeHtml((meta && meta.kpi_label) || "KPI")}: ${escapeHtml(kpiText)}</span>` +
                `<br><span class="ch-tip-sub">Point of interest — above mid threshold</span></div>`;

            L.circleMarker([s.lat, s.lng], {
                radius: s.kw >= 0.75 ? 6 : 5,
                fillColor: s.kw >= 0.75 ? "#c0392b" : "#e67e22",
                fillOpacity: 0.95,
                color: "#fff",
                weight: 2,
                interactive: true,
                className: "ch-poi-marker",
            })
                .bindTooltip(title, { direction: "top", sticky: true })
                .addTo(poiLayer);
        }
    }

    function renderTooltipMarkers(details, meta) {
        clearTooltipLayer();
        if (!details.length) return;

        tooltipLayer = L.layerGroup().addTo(map);
        const zoom = map.getZoom();
        let step = 1;
        if (details.length > 8000 && zoom < 13) step = 2;

        for (let i = 0; i < details.length; i += step) {
            const d = details[i];
            const lat = Number(d.latitude);
            const lng = Number(d.longitude);
            if (!Number.isFinite(lat) || !Number.isFinite(lng)) continue;

            L.circleMarker([lat, lng], {
                radius: 7,
                fillOpacity: 0,
                opacity: 0,
                weight: 0,
                interactive: true,
                className: "ch-hit-marker",
            })
                .bindTooltip(cellTooltipHtml(d, meta), { direction: "top", sticky: true })
                .addTo(tooltipLayer);
        }
    }

    function clearAuraVisual() {
        if (auraCanvas) {
            const ctx = auraCanvas.getContext("2d");
            ctx.clearRect(0, 0, auraCanvas.width, auraCanvas.height);
        }
        clearTooltipLayer();
        clearPoiLayer();
    }

    function applyVisualization() {
        if (!lastDetails.length) {
            clearAuraVisual();
            sectorCache = [];
            sectorBuckets = new Map();
            updateLegend(lastMeta);
            return;
        }
        rebuildSectorIndex();
        buildKpiColorLut();
        updateAuraCanvasStyle();
        scheduleAuraRedraw();
        renderTooltipMarkers(lastDetails, lastMeta);
        renderPoiMarkers(lastMeta);
        updateLegend(lastMeta);
    }

    function escapeHtml(s) {
        return String(s)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    function updateLegend(meta) {
        const el = $("heat-legend");
        if (!el) return;
        if (!lastDetails.length) {
            el.hidden = true;
            el.setAttribute("aria-hidden", "true");
            return;
        }
        el.hidden = false;
        el.setAttribute("aria-hidden", "false");

        const kpiLabel = escapeHtml((meta && meta.kpi_label) || "KPI");
        const goodVal = meta && meta.good_threshold != null ? Number(meta.good_threshold) : null;
        const badVal = meta && meta.bad_threshold != null ? Number(meta.bad_threshold) : null;
        const avgVal =
            meta && meta.kpi_avg != null
                ? Number(meta.kpi_avg)
                : meta && meta.drop_avg != null
                  ? Number(meta.drop_avg)
                  : null;
        const goodTxt = formatKpiLegendValue(goodVal, meta);
        const badTxt = formatKpiLegendValue(badVal, meta);
        const avgTxt = formatKpiLegendValue(avgVal, meta);
        const poiCount = sectorCache.filter((s) => s.kw >= POI_KPI_WEIGHT).length;
        const grad = kpiGradientCss();

        el.innerHTML = `
            <div class="ch-legend-title">${kpiLabel}</div>
            <div class="ch-legend-survey-wrap">
                <div class="ch-legend-survey-bar" style="background:linear-gradient(to right,${grad});"></div>
                <div class="ch-legend-callout ch-legend-callout--good">
                    <span class="ch-legend-callout-val">${escapeHtml(goodTxt)}</span>
                    <span class="ch-legend-callout-lbl">Good</span>
                </div>
                <div class="ch-legend-callout ch-legend-callout--bad">
                    <span class="ch-legend-callout-val">${escapeHtml(badTxt)}</span>
                    <span class="ch-legend-callout-lbl">Bad</span>
                </div>
            </div>
            <div class="ch-legend-scale-row">
                <span>Healthy coverage</span>
                <span>Investigate</span>
            </div>
            <div class="ch-legend-stats">
                <span>Avg <strong>${escapeHtml(avgTxt)}</strong></span>
                <span class="ch-legend-poi">${poiCount} POI cells</span>
            </div>
            <div class="ch-legend-poi-hint">
                <span class="ch-legend-poi-dot ch-legend-poi-dot--warn"></span> Orange/red dots = cells above mid threshold
            </div>`;
    }

    function updateStats() {
        /* Cell count / load stats intentionally not shown in UI. */
    }

    function applyPresetToThresholds() {
        const sel = $("kpi-filter");
        const gIn = $("good-thr");
        const bIn = $("bad-thr");
        if (!sel || !kpiPresets.length) return;
        const p = kpiPresets.find((x) => x.key === sel.value);
        if (!p) return;
        if (gIn) gIn.value = String(p.good);
        if (bIn) bIn.value = String(p.bad);
    }

    async function loadConfig() {
        const res = await fetch("/api/cell-heatmap/config");
        const data = await res.json();
        if (!data.success) return;
        kpiPresets = data.kpi_presets || [];
        const kpiSel = $("kpi-filter");
        if (kpiSel) {
            kpiSel.innerHTML = kpiPresets.map((k) => `<option value="${k.key}">${k.label}</option>`).join("");
            kpiSel.disabled = kpiPresets.length <= 1;
            kpiSel.addEventListener("change", applyPresetToThresholds);
            applyPresetToThresholds();
        }
    }

    async function loadBands() {
        const bandSel = $("band-filter");
        if (!bandSel) return;
        const params = new URLSearchParams({
            vendor: String($("vendor-filter")?.value || "all"),
            technology: String($("technology-filter")?.value || "4G"),
        });
        const current = bandSel.value;
        const res = await fetch(`/api/cell-heatmap/bands?${params.toString()}`);
        const data = await res.json();
        if (!data.success) return;
        const bands = Array.isArray(data.bands) ? data.bands : [];
        bandSel.innerHTML =
            `<option value="">All bands</option>` + bands.map((b) => `<option value="${b}">${b}</option>`).join("");
        if (current && bands.includes(current)) {
            bandSel.value = current;
        }
    }

    function fitToData() {
        if (!map || !lastBounds) return;
        map.fitBounds(lastBounds, { padding: [36, 36], maxZoom: 15 });
    }

    async function loadHeatmap() {
        const dataScope = String($("data-scope-filter")?.value || "daily").trim();
        const vendor = String($("vendor-filter")?.value || "all").trim();
        const technology = String($("technology-filter")?.value || "4G").trim();
        const band = String($("band-filter")?.value || "").trim();
        const limit = String($("point-limit")?.value || "20000").trim();
        const kpi = String($("kpi-filter")?.value || "access_rrc").trim();
        const goodRaw = String($("good-thr")?.value || "").trim();
        const badRaw = String($("bad-thr")?.value || "").trim();
        const loadBtn = $("load-btn");

        const params = new URLSearchParams();
        params.set("vendor", vendor);
        params.set("technology", technology);
        params.set("data_scope", dataScope);
        params.set("kpi", kpi);
        if (band) params.set("band", band);
        params.set("limit", limit);
        if (goodRaw !== "") params.set("good", goodRaw);
        if (badRaw !== "") params.set("bad", badRaw);

        loadBtn.disabled = true;
        setStatus("loading", "Fetching cells and PM…");
        try {
            const res = await fetch(`/api/cell-heatmap/points?${params.toString()}`);
            const data = await res.json();
            if (!data.success) {
                setStatus("err", data.error || "Request failed.");
                updateStats();
                return;
            }
            lastMeta = data.meta || {};
            lastDetails = enrichDetailsWithSizeWeights(
                Array.isArray(data.details) ? data.details : [],
                lastMeta,
            );
            if (lastDetails.length) {
                lastBounds = L.latLngBounds(lastDetails.map((d) => [d.latitude, d.longitude]));
            } else {
                lastBounds = null;
            }
            applyVisualization();
            if (lastBounds) {
                fitToData();
            }
            setStatus("ok", "Heatmap loaded.");
            updateStats();
        } catch (err) {
            setStatus("err", "Network or server error.");
            console.error(err);
            updateStats();
        } finally {
            loadBtn.disabled = false;
        }
    }

    function bindHeatTuning() {
        const aura = $("heat-aura-opacity");
        const auraLabel = $("heat-aura-opacity-val");
        const blur = $("heat-aura-blur");
        const blurLabel = $("heat-aura-blur-val");
        const reapply = () => {
            if (aura) {
                kpiAuraOpacity = Math.max(0.25, Math.min(1, Number(aura.value) / 100));
                if (auraLabel) auraLabel.textContent = String(aura.value);
            }
            if (blur) {
                kpiAuraBlurPx = Math.max(6, Math.min(48, Number(blur.value)));
                if (blurLabel) blurLabel.textContent = String(blur.value);
            }
            buildKpiColorLut();
            updateAuraCanvasStyle();
            if (lastDetails.length) {
                scheduleAuraRedraw();
            }
        };
        aura?.addEventListener("input", reapply);
        blur?.addEventListener("input", reapply);
        reapply();
    }

    function bindScopeControls() {
        const reloadBands = () => {
            loadBands().catch((err) => console.error(err));
        };
        $("vendor-filter")?.addEventListener("change", reloadBands);
        $("technology-filter")?.addEventListener("change", reloadBands);
    }

    document.addEventListener("DOMContentLoaded", () => {
        initMap();
        initDrawer();
        const fixMapSize = () => {
            if (map) map.invalidateSize();
        };
        setTimeout(fixMapSize, 200);
        setTimeout(fixMapSize, 600);
        window.addEventListener("resize", fixMapSize);
        $("load-btn")?.addEventListener("click", loadHeatmap);
        $("fit-bounds-btn")?.addEventListener("click", fitToData);
        bindScopeControls();
        bindHeatTuning();
        loadConfig()
            .then(loadBands)
            .then(() => setStatus(null, "Set filters and click Load data."));
    });
})();
