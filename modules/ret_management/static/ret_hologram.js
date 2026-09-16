/**
 * RET Management site hologram — azimuth-true top view of one site.
 *
 * Pure Canvas 2D (no CDN dependency, works on the intranet). The default view is
 * a true top view: screen-up is geographic north and a sector lobe is drawn at
 * its real azimuth from the PrimeNet inventory (or the RET's own reported
 * bearing when the vendor gives one). The optional 3D tilt is cosmetic only and
 * is off by default so bearings stay readable off the screen.
 *
 * Lobe radius shrinks as downtilt grows; when a sector has an unapplied tilt
 * edit the committed lobe stays as a dashed ghost behind the new one.
 */
(function (global) {
    'use strict';

    const TECH_COLORS = {
        '2G': [242, 177, 52],
        '3G': [167, 119, 227],
        '4G-FDD': [58, 190, 232],
        '4G-TDD': [46, 204, 175],
        '5G': [236, 100, 190],
    };
    const TECH_RANK = ['5G', '4G-TDD', '4G-FDD', '3G', '2G'];
    const DEFAULT_COLOR = [110, 196, 240];
    const EDIT_COLOR = [247, 181, 56];
    const MIN_TILT_FOR_DISTANCE = 0.5;
    const MAX_GROUND_DISTANCE_M = 5000;
    const TILT_FULL_RANGE_DEG = 12;

    function clamp(value, min, max) {
        return Math.min(max, Math.max(min, value));
    }

    function rgba(color, alpha) {
        return `rgba(${color[0]}, ${color[1]}, ${color[2]}, ${alpha})`;
    }

    function techColor(technologies) {
        const list = Array.isArray(technologies) ? technologies : [];
        for (const tech of TECH_RANK) {
            if (list.includes(tech)) return TECH_COLORS[tech];
        }
        return DEFAULT_COLOR;
    }

    function toRadians(deg) {
        return (deg * Math.PI) / 180;
    }

    /** Main-lobe ground distance h / tan(total tilt), bounded for display. */
    function groundDistance(heightM, tiltDeg) {
        const height = Number.isFinite(heightM) && heightM > 0 ? heightM : 25;
        const tilt = Math.max(MIN_TILT_FOR_DISTANCE, Number.isFinite(tiltDeg) ? tiltDeg : 0);
        const distance = height / Math.tan(toRadians(tilt));
        return clamp(distance, 20, MAX_GROUND_DISTANCE_M);
    }

    /**
     * Monotonic lobe length: 0° tilt fills the canvas, 12°+ draws the short lobe.
     * Kept linear on purpose so a 1° edit is a visible, comparable step; the real
     * h/tan(tilt) distance is in the tooltip and the ring legend.
     */
    function lobeFactor(tiltDeg) {
        const tilt = Number.isFinite(tiltDeg) ? Math.max(0, tiltDeg) : 0;
        return clamp(1 - (tilt / TILT_FULL_RANGE_DEG) * 0.68, 0.3, 1);
    }

    function formatDegrees(value) {
        if (!Number.isFinite(value)) return '—';
        const rounded = Math.round(value * 10) / 10;
        return Number.isInteger(rounded) ? `${rounded}°` : `${rounded.toFixed(1)}°`;
    }

    function formatDistance(metres) {
        if (!Number.isFinite(metres)) return '—';
        if (metres >= 1000) return `${(metres / 1000).toFixed(2)} km`;
        return `${Math.round(metres)} m`;
    }

    /** Sector ids, bands and layer names come from the inventory DB, never trusted as markup. */
    function escapeHtml(value) {
        return String(value === undefined || value === null ? '' : value).replace(
            /[&<>"']/g,
            (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]),
        );
    }

    function create(canvas, options) {
        const opts = options || {};
        const ctx = canvas.getContext('2d');
        const wrapper = canvas.parentElement;
        const state = {
            site: {},
            sectors: [],
            selected: null,
            hovered: null,
            rotation: 0,
            pitch: 0,
            zoom: 1,
            width: 0,
            height: 0,
            frame: null,
            animating: false,
            phase: 0,
            drag: null,
            hitAreas: [],
        };

        const tooltip = document.createElement('div');
        tooltip.className = 'holo-tooltip';
        tooltip.hidden = true;
        if (wrapper) wrapper.appendChild(tooltip);

        function centre() {
            return { x: state.width / 2, y: state.height / 2 };
        }

        function baseRadius() {
            return (Math.min(state.width, state.height) / 2 - 34) * state.zoom;
        }

        /** Screen point for a bearing/radius, honouring view rotation and cosmetic pitch. */
        function project(bearingDeg, radius) {
            const { x, y } = centre();
            const angle = toRadians(bearingDeg + state.rotation - 90);
            const squash = 1 - state.pitch * 0.55;
            return {
                x: x + Math.cos(angle) * radius,
                y: y + Math.sin(angle) * radius * squash,
            };
        }

        function resize() {
            const dpr = global.devicePixelRatio || 1;
            const rect = canvas.getBoundingClientRect();
            const width = Math.max(240, Math.round(rect.width));
            const height = Math.max(240, Math.round(rect.height || width));
            state.width = width;
            state.height = height;
            canvas.width = Math.round(width * dpr);
            canvas.height = Math.round(height * dpr);
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
            draw();
        }

        function drawBackdrop() {
            const { x, y } = centre();
            const radius = baseRadius();
            ctx.save();
            const backdrop = ctx.createRadialGradient(x, y, 0, x, y, Math.max(radius, 1) * 1.5);
            backdrop.addColorStop(0, '#0d2136');
            backdrop.addColorStop(0.55, '#081726');
            backdrop.addColorStop(1, '#050d16');
            ctx.fillStyle = backdrop;
            ctx.fillRect(0, 0, state.width, state.height);

            // Range rings, labelled with the ground distance they represent.
            const rings = [0.25, 0.5, 0.75, 1];
            ctx.lineWidth = 1;
            rings.forEach((fraction) => {
                ctx.beginPath();
                ctx.strokeStyle = fraction === 1
                    ? 'rgba(96, 186, 232, 0.35)'
                    : 'rgba(96, 186, 232, 0.16)';
                for (let deg = 0; deg <= 360; deg += 4) {
                    const point = project(deg, radius * fraction);
                    if (deg === 0) ctx.moveTo(point.x, point.y);
                    else ctx.lineTo(point.x, point.y);
                }
                ctx.closePath();
                ctx.stroke();
            });

            // Compass spokes every 30°, cardinal labels at the rim.
            ctx.font = '600 11px system-ui, -apple-system, "Segoe UI", sans-serif';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            for (let deg = 0; deg < 360; deg += 30) {
                const cardinal = deg % 90 === 0;
                const inner = project(deg, radius * (cardinal ? 0.06 : 0.9));
                const outer = project(deg, radius);
                ctx.beginPath();
                ctx.strokeStyle = cardinal ? 'rgba(120, 200, 240, 0.3)' : 'rgba(120, 200, 240, 0.14)';
                ctx.moveTo(inner.x, inner.y);
                ctx.lineTo(outer.x, outer.y);
                ctx.stroke();
                if (cardinal) {
                    const label = { 0: 'N', 90: 'E', 180: 'S', 270: 'W' }[deg];
                    const at = project(deg, radius + 16);
                    ctx.fillStyle = deg === 0 ? '#7fe3ff' : 'rgba(150, 197, 226, 0.75)';
                    ctx.fillText(label, at.x, at.y);
                }
            }
            ctx.restore();
        }

        function drawScaleLegend() {
            const radius = baseRadius();
            const maxDistance = state.sectors.reduce((acc, sector) => {
                const distance = groundDistance(sector.height || state.site.antenna_height, sector.tiltDeg);
                return Math.max(acc, distance);
            }, 0);
            if (!maxDistance || !radius) return;
            ctx.save();
            ctx.font = '500 10px system-ui, -apple-system, "Segoe UI", sans-serif';
            ctx.fillStyle = 'rgba(150, 197, 226, 0.7)';
            ctx.textAlign = 'left';
            ctx.textBaseline = 'bottom';
            ctx.fillText(
                `outer ring ≈ ${formatDistance(maxDistance)} main-lobe distance · h/tan(tilt)`,
                12,
                state.height - 10,
            );
            ctx.restore();
        }

        function drawMast() {
            const { x, y } = centre();
            ctx.save();
            const glow = ctx.createRadialGradient(x, y, 0, x, y, 26);
            glow.addColorStop(0, 'rgba(127, 227, 255, 0.85)');
            glow.addColorStop(1, 'rgba(127, 227, 255, 0)');
            ctx.fillStyle = glow;
            ctx.beginPath();
            ctx.arc(x, y, 26, 0, Math.PI * 2);
            ctx.fill();
            ctx.beginPath();
            ctx.fillStyle = '#d6f4ff';
            ctx.arc(x, y, 4.5, 0, Math.PI * 2);
            ctx.fill();
            ctx.restore();
        }

        function wedgePath(sector, radius) {
            const half = clamp((sector.beamwidth || 65) / 2, 5, 180);
            const start = sector.azimuth - half;
            const end = sector.azimuth + half;
            const { x, y } = centre();
            ctx.beginPath();
            ctx.moveTo(x, y);
            for (let deg = start; deg <= end; deg += 1.5) {
                const point = project(deg, radius);
                ctx.lineTo(point.x, point.y);
            }
            const last = project(end, radius);
            ctx.lineTo(last.x, last.y);
            ctx.closePath();
        }

        function drawSector(sector) {
            const radius = baseRadius();
            const colour = sector.edited ? EDIT_COLOR : techColor(sector.technologies);
            const isSelected = state.selected === sector.key;
            const isHovered = state.hovered === sector.key;
            const lobe = radius * lobeFactor(sector.tiltDeg);

            // Ghost of the committed tilt while an edit is pending.
            if (sector.edited && Number.isFinite(sector.baselineTiltDeg)) {
                const ghost = radius * lobeFactor(sector.baselineTiltDeg);
                ctx.save();
                ctx.setLineDash([5, 5]);
                ctx.lineWidth = 1.4;
                ctx.strokeStyle = 'rgba(247, 181, 56, 0.55)';
                wedgePath(sector, ghost);
                ctx.stroke();
                ctx.restore();
            }

            ctx.save();
            const { x, y } = centre();
            const fill = ctx.createRadialGradient(x, y, 0, x, y, Math.max(lobe, 1));
            fill.addColorStop(0, rgba(colour, isSelected ? 0.62 : 0.44));
            fill.addColorStop(0.65, rgba(colour, isSelected ? 0.3 : 0.2));
            fill.addColorStop(1, rgba(colour, 0.02));
            ctx.fillStyle = fill;
            wedgePath(sector, lobe);
            ctx.fill();

            ctx.lineWidth = sector.edited ? 2.4 : (isSelected || isHovered ? 2 : 1.2);
            ctx.strokeStyle = rgba(colour, sector.edited ? 0.95 : (isSelected || isHovered ? 0.9 : 0.55));
            if (sector.edited) {
                const pulse = 0.55 + 0.45 * Math.sin(state.phase * 2.2);
                ctx.shadowColor = rgba(EDIT_COLOR, pulse);
                ctx.shadowBlur = 14;
            }
            ctx.stroke();
            ctx.restore();

            // Boresight and label.
            const tip = project(sector.azimuth, lobe);
            ctx.save();
            ctx.beginPath();
            ctx.strokeStyle = rgba(colour, 0.85);
            ctx.lineWidth = 1.5;
            ctx.moveTo(x, y);
            ctx.lineTo(tip.x, tip.y);
            ctx.stroke();

            const labelAt = project(sector.azimuth, lobe + 18);
            ctx.font = '600 12px system-ui, -apple-system, "Segoe UI", sans-serif';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillStyle = sector.edited ? '#ffd483' : rgba(colour, 0.98);
            const tiltText = Number.isFinite(sector.tiltDeg) ? formatDegrees(sector.tiltDeg) : '—';
            ctx.fillText(`S${sector.label}`, labelAt.x, labelAt.y - 7);
            ctx.font = '500 11px system-ui, -apple-system, "Segoe UI", sans-serif';
            ctx.fillStyle = sector.edited ? '#ffd483' : 'rgba(198, 226, 244, 0.85)';
            const tiltPart = sector.edited && Number.isFinite(sector.baselineTiltDeg)
                ? `${formatDegrees(sector.baselineTiltDeg)}→${tiltText}`
                : tiltText;
            ctx.fillText(
                `az ${formatDegrees(sector.azimuth)} · tilt ${tiltPart}`,
                labelAt.x,
                labelAt.y + 7,
            );
            ctx.restore();
        }

        function draw() {
            if (!state.width || !state.height) return;
            drawBackdrop();
            const ordered = state.sectors.slice().sort((a, b) => {
                const aActive = (state.selected === a.key ? 2 : 0) + (a.edited ? 1 : 0);
                const bActive = (state.selected === b.key ? 2 : 0) + (b.edited ? 1 : 0);
                return aActive - bActive;
            });
            ordered.forEach(drawSector);
            drawMast();
            drawScaleLegend();
            rebuildHitAreas();
        }

        function rebuildHitAreas() {
            const radius = baseRadius();
            state.hitAreas = state.sectors.map((sector) => ({
                key: sector.key,
                azimuth: sector.azimuth,
                half: clamp((sector.beamwidth || 65) / 2, 5, 180),
                radius: radius * lobeFactor(sector.tiltDeg),
            }));
        }

        function needsAnimation() {
            return state.sectors.some((sector) => sector.edited);
        }

        function tick() {
            state.phase += 0.05;
            draw();
            if (needsAnimation()) {
                state.frame = global.requestAnimationFrame(tick);
            } else {
                state.frame = null;
                state.animating = false;
            }
        }

        function schedule() {
            if (needsAnimation()) {
                if (!state.animating) {
                    state.animating = true;
                    state.frame = global.requestAnimationFrame(tick);
                }
            } else {
                if (state.frame) global.cancelAnimationFrame(state.frame);
                state.frame = null;
                state.animating = false;
                draw();
            }
        }

        function sectorAtPoint(clientX, clientY) {
            const rect = canvas.getBoundingClientRect();
            const px = clientX - rect.left;
            const py = clientY - rect.top;
            const { x, y } = centre();
            const squash = 1 - state.pitch * 0.55;
            const dx = px - x;
            const dy = (py - y) / (squash || 1);
            const distance = Math.sqrt(dx * dx + dy * dy);
            let bearing = (Math.atan2(dy, dx) * 180) / Math.PI + 90 - state.rotation;
            bearing = ((bearing % 360) + 360) % 360;
            let best = null;
            state.hitAreas.forEach((area) => {
                if (distance > area.radius + 16) return;
                const delta = Math.abs(((bearing - area.azimuth + 180) % 360) - 180);
                if (delta <= area.half + 2 && (!best || delta < best.delta)) {
                    best = { key: area.key, delta };
                }
            });
            return best ? best.key : null;
        }

        function tooltipHtml(sector) {
            const height = sector.height || state.site.antenna_height;
            const rows = [
                ['Azimuth', `${formatDegrees(sector.azimuth)}${sector.azimuthSource && sector.azimuthSource !== 'metadata' ? ` (${sector.azimuthSource})` : ''}`],
                ['Electrical tilt', Number.isFinite(sector.tiltDeg) ? formatDegrees(sector.tiltDeg) : 'not reported'],
            ];
            if (sector.edited && Number.isFinite(sector.baselineTiltDeg)) {
                rows.push(['Pending edit', `${formatDegrees(sector.baselineTiltDeg)} → ${formatDegrees(sector.tiltDeg)}`]);
            }
            if (Array.isArray(sector.tiltSpread)) {
                rows.push([
                    'Tilt spread',
                    `${formatDegrees(sector.tiltSpread[0])}–${formatDegrees(sector.tiltSpread[1])} `
                    + `over ${sector.retCount} RETs`,
                ]);
            }
            if (Number.isFinite(sector.mechanicalTilt)) {
                rows.push(['Mechanical tilt', formatDegrees(sector.mechanicalTilt)]);
            }
            rows.push(['Antenna height', Number.isFinite(height) ? `${Math.round(height)} m` : '—']);
            rows.push(['Main lobe ≈', formatDistance(groundDistance(height, sector.tiltDeg))]);
            if (sector.technologies && sector.technologies.length) {
                rows.push(['Layers', sector.technologies.join(', ')]);
            }
            if (sector.bands && sector.bands.length) {
                rows.push(['Bands', sector.bands.join(', ')]);
            }
            rows.push(['Cells / RETs', `${sector.cellCount || 0} / ${sector.retCount || 0}`]);
            const body = rows
                .map(([label, value]) => `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd>`)
                .join('');
            return `<strong>Sector ${escapeHtml(sector.label)}</strong><dl>${body}</dl>`
                + '<em>Click to filter the RET table</em>';
        }

        function showTooltip(key, clientX, clientY) {
            const sector = state.sectors.find((item) => item.key === key);
            if (!sector || !wrapper) {
                tooltip.hidden = true;
                return;
            }
            const rect = wrapper.getBoundingClientRect();
            const canvasRect = canvas.getBoundingClientRect();
            tooltip.innerHTML = tooltipHtml(sector);
            tooltip.hidden = false;
            const maxLeft = canvasRect.right - rect.left - tooltip.offsetWidth - 8;
            const maxTop = canvasRect.bottom - rect.top - tooltip.offsetHeight - 8;
            const left = clamp(clientX - rect.left + 14, 8, Math.max(8, maxLeft));
            const top = clamp(clientY - rect.top + 14, 8, Math.max(8, maxTop));
            tooltip.style.left = `${left}px`;
            tooltip.style.top = `${top}px`;
        }

        function onPointerMove(event) {
            if (state.drag) {
                const dx = event.clientX - state.drag.x;
                state.rotation = state.drag.rotation + dx * 0.4;
                state.drag.moved = state.drag.moved || Math.abs(dx) > 3;
                draw();
                return;
            }
            const key = sectorAtPoint(event.clientX, event.clientY);
            if (key !== state.hovered) {
                state.hovered = key;
                canvas.style.cursor = key ? 'pointer' : 'grab';
                draw();
                if (typeof opts.onHoverSector === 'function') opts.onHoverSector(key);
            }
            if (key) showTooltip(key, event.clientX, event.clientY);
            else tooltip.hidden = true;
        }

        function onPointerDown(event) {
            state.drag = { x: event.clientX, rotation: state.rotation, moved: false };
            canvas.setPointerCapture?.(event.pointerId);
        }

        function onPointerUp(event) {
            const wasDrag = state.drag && state.drag.moved;
            state.drag = null;
            canvas.releasePointerCapture?.(event.pointerId);
            if (wasDrag) return;
            const key = sectorAtPoint(event.clientX, event.clientY);
            api.setSelected(state.selected === key ? null : key);
            if (typeof opts.onSelectSector === 'function') {
                opts.onSelectSector(state.selected);
            }
        }

        function onPointerLeave() {
            state.drag = null;
            if (state.hovered) {
                state.hovered = null;
                draw();
            }
            tooltip.hidden = true;
        }

        function onWheel(event) {
            event.preventDefault();
            const factor = event.deltaY > 0 ? 0.92 : 1.08;
            state.zoom = clamp(state.zoom * factor, 0.55, 2.6);
            draw();
        }

        function onKeyDown(event) {
            if (!state.sectors.length) return;
            const keys = state.sectors.map((sector) => sector.key);
            const current = keys.indexOf(state.selected);
            if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
                event.preventDefault();
                api.setSelected(keys[(current + 1 + keys.length) % keys.length]);
                if (typeof opts.onSelectSector === 'function') opts.onSelectSector(state.selected);
            } else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
                event.preventDefault();
                api.setSelected(keys[(current - 1 + keys.length) % keys.length]);
                if (typeof opts.onSelectSector === 'function') opts.onSelectSector(state.selected);
            } else if (event.key === 'Escape') {
                api.setSelected(null);
                if (typeof opts.onSelectSector === 'function') opts.onSelectSector(null);
            }
        }

        canvas.addEventListener('pointermove', onPointerMove);
        canvas.addEventListener('pointerdown', onPointerDown);
        canvas.addEventListener('pointerup', onPointerUp);
        canvas.addEventListener('pointerleave', onPointerLeave);
        canvas.addEventListener('wheel', onWheel, { passive: false });
        canvas.addEventListener('keydown', onKeyDown);
        canvas.tabIndex = 0;
        canvas.style.cursor = 'grab';

        let observer = null;
        if (typeof ResizeObserver === 'function') {
            observer = new ResizeObserver(() => resize());
            observer.observe(canvas);
        } else {
            global.addEventListener('resize', resize);
        }

        const api = {
            setSite(site) {
                state.site = site || {};
                draw();
            },
            setSectors(sectors) {
                state.sectors = Array.isArray(sectors) ? sectors : [];
                if (state.selected && !state.sectors.some((s) => s.key === state.selected)) {
                    state.selected = null;
                }
                schedule();
            },
            setSelected(key) {
                state.selected = key || null;
                draw();
            },
            getSelected() {
                return state.selected;
            },
            setPitch(pitch) {
                state.pitch = clamp(Number(pitch) || 0, 0, 0.8);
                draw();
            },
            setRotation(deg) {
                state.rotation = Number(deg) || 0;
                draw();
            },
            reset() {
                state.rotation = 0;
                state.zoom = 1;
                draw();
            },
            resize,
            destroy() {
                if (state.frame) global.cancelAnimationFrame(state.frame);
                if (observer) observer.disconnect();
                else global.removeEventListener('resize', resize);
                canvas.removeEventListener('pointermove', onPointerMove);
                canvas.removeEventListener('pointerdown', onPointerDown);
                canvas.removeEventListener('pointerup', onPointerUp);
                canvas.removeEventListener('pointerleave', onPointerLeave);
                canvas.removeEventListener('wheel', onWheel);
                canvas.removeEventListener('keydown', onKeyDown);
                tooltip.remove();
            },
        };

        resize();
        return api;
    }

    global.RetHologram = { create, groundDistance, formatDegrees, formatDistance, TECH_COLORS };
})(window);
