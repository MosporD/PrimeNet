/* ============================================================================
 * PrimeNet Portal Tower — scroll-driven 3D telecom tower (canvas 2D, no deps)
 *
 * The portal picker renders a self-supporting lattice telecom tower in 3D.
 * Scrolling descends the camera along the mast; each portal is a platform
 * level with a microwave dish. The active level glows, emits signal rings,
 * and a HUD connector line links the platform to its portal card.
 *
 * Exposes window.PrimeNetPortalTower:
 *   - init(canvas, getState): low-level renderer. getState() returns
 *       { elev, active, focus, side, cardEl }.
 *   - initPage(): wires scroll mapping, HUD, rail, reveal, then calls init.
 * ==========================================================================*/
(function () {
    'use strict';

    var REDUCE_MOTION = window.matchMedia &&
        window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    var TAU = Math.PI * 2;

    /* Tower geometry (units are metres) */
    var TOWER_H = 120;          /* lattice top */
    var MAST_TOP = 134;         /* antenna mast top */
    var BEACON_Y = 134.8;
    var SEGMENTS = 14;
    var PLATFORMS = [104, 78, 52, 26];   /* portal levels, top to bottom */
    var TOP_ELEV = 127;         /* camera eye at hero */
    var BASE_ELEV = 15;         /* camera eye at ground section */

    function clamp(v, a, b) { return v < a ? a : (v > b ? b : v); }
    function lerp(a, b, t) { return a + (b - a) * t; }

    /* Tower half-width at height y (tapered) */
    function halfW(y) {
        var t = 1 - y / TOWER_H;
        if (t < 0) t = 0;
        return 3.5 + 14.5 * Math.pow(t, 1.18);
    }

    function palette() {
        var dark = document.body.classList.contains('dark-mode');
        return dark ? {
            dark: true,
            bgTop: '#020617', bgMid: '#050e2b', bgBot: '#08183f',
            line: '125,211,252',
            lineStrong: '56,189,248',
            accent: '56,189,248',
            beacon: '255,99,110',
            ground: '96,165,250',
            star: '226,238,255',
            panelFill: 'rgba(56,189,248,0.10)',
            glow: 'rgba(56,189,248,'
        } : {
            dark: false,
            bgTop: '#eaf1f7', bgMid: '#d8e6f1', bgBot: '#c5d9e8',
            line: '96,128,156',
            lineStrong: '62,95,124',
            accent: '74,124,166',
            beacon: '224,93,93',
            ground: '79,141,184',
            star: '44,62,80',
            panelFill: 'rgba(58,115,153,0.14)',
            glow: 'rgba(58,115,153,'
        };
    }

    /* ------------------------------------------------------------------ */
    function init(canvas, getState) {
        var ctx = canvas.getContext('2d');
        var vw = 0, vh = 0, dpr = 1;
        var camY = TOP_ELEV;
        var shift = 0;               /* horizontal tower offset (-1..1 of vw fraction) */
        var pal = palette();
        var stars = [];
        var particles = [];
        var ripples = [];            /* { y, r, max, a } */
        var lastPlatRipple = 0;
        var lastBeaconRipple = 0;
        var whooshes = [];           /* Soft Steel / gate-cyan descent ribbons */
        var prevCamY = TOP_ELEV;
        var lastWhooshSpawn = 0;
        var lastPlatWhoosh = -1;
        var startT = performance.now();
        var lastT = startT;
        var frameQueued = false;

        var cx = 0, cy = 0, FOV = 0, DIST = 150;
        var cosT = 1, sinT = 0;

        function resize() {
            dpr = Math.min(window.devicePixelRatio || 1, 2);
            vw = window.innerWidth;
            vh = window.innerHeight;
            canvas.width = Math.round(vw * dpr);
            canvas.height = Math.round(vh * dpr);
            canvas.style.width = vw + 'px';
            canvas.style.height = vh + 'px';
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
            makeStars();
        }

        function makeStars() {
            stars = [];
            var n = Math.round((vw * vh) / 14000);
            for (var i = 0; i < n; i++) {
                stars.push({
                    x: Math.random() * vw,
                    y: Math.random() * vh,
                    r: 0.5 + Math.random() * 1.1,
                    ph: Math.random() * TAU,
                    sp: 0.4 + Math.random() * 1.2
                });
            }
        }

        function makeParticles() {
            particles = [];
            for (var i = 0; i < 12; i++) {
                particles.push({
                    leg: i % 4,
                    y: Math.random() * TOWER_H,
                    sp: 5 + Math.random() * 9
                });
            }
        }

        /* Perspective projection: camera orbits the tower axis at height camY */
        function project(x, y, z) {
            var xr = x * cosT - z * sinT;
            var zr = x * sinT + z * cosT;
            var d = DIST + zr;
            if (d < 8) d = 8;
            var k = FOV / d;
            return { x: cx + xr * k, y: cy + (camY - y) * k, k: k, z: zr };
        }

        function shade(z) {
            return clamp(0.95 - z / 42, 0.3, 1.15);
        }

        function line3(x1, y1, z1, x2, y2, z2, w, alpha, rgb) {
            var a = project(x1, y1, z1);
            var b = project(x2, y2, z2);
            var s = shade((a.z + b.z) / 2);
            ctx.strokeStyle = 'rgba(' + rgb + ',' + (alpha * s).toFixed(3) + ')';
            ctx.lineWidth = Math.max(0.55, w * (a.k + b.k) * 0.5 * 0.09);
            ctx.beginPath();
            ctx.moveTo(a.x, a.y);
            ctx.lineTo(b.x, b.y);
            ctx.stroke();
        }

        function ring3(y, r, n, w, alpha, rgb, azOff) {
            azOff = azOff || 0;
            ctx.beginPath();
            var zSum = 0;
            for (var i = 0; i <= n; i++) {
                var az = azOff + (i / n) * TAU;
                var p = project(Math.cos(az) * r, y, Math.sin(az) * r);
                zSum += p.z;
                if (i === 0) ctx.moveTo(p.x, p.y); else ctx.lineTo(p.x, p.y);
            }
            var s = shade(zSum / (n + 1));
            ctx.strokeStyle = 'rgba(' + rgb + ',' + (alpha * s).toFixed(3) + ')';
            ctx.lineWidth = Math.max(0.55, w);
            ctx.stroke();
        }

        /* Legs sit on the square's corners */
        var LEG_SX = [1, 1, -1, -1];
        var LEG_SZ = [1, -1, -1, 1];

        function legPoint(leg, y) {
            var w = halfW(y);
            return { x: w * LEG_SX[leg], y: y, z: w * LEG_SZ[leg] };
        }

        function drawBackground(t) {
            var hasElegant = !!document.querySelector('.elegant-gradient-bg');
            var g = ctx.createLinearGradient(0, 0, 0, vh);
            g.addColorStop(0, pal.bgTop);
            g.addColorStop(0.55, pal.bgMid);
            g.addColorStop(1, pal.bgBot);
            /* Soft Steel / gate elegant base peeks through under the tower. */
            ctx.globalAlpha = hasElegant ? (pal.dark ? 0.48 : 0.4) : 1;
            ctx.fillStyle = g;
            ctx.fillRect(0, 0, vw, vh);
            ctx.globalAlpha = 1;

            if (pal.dark) {
                for (var i = 0; i < stars.length; i++) {
                    var st = stars[i];
                    var tw = REDUCE_MOTION ? 0.55 : 0.42 + 0.38 * Math.sin(t * st.sp + st.ph);
                    ctx.fillStyle = 'rgba(' + pal.star + ',' + tw.toFixed(3) + ')';
                    ctx.beginPath();
                    ctx.arc(st.x, st.y, st.r, 0, TAU);
                    ctx.fill();
                }
            }

            /* soft aura behind the tower */
            var aur = ctx.createRadialGradient(cx, cy, 0, cx, cy, Math.max(vw, vh) * 0.42);
            aur.addColorStop(0, pal.glow + (pal.dark ? '0.07' : '0.10') + ')');
            aur.addColorStop(1, pal.glow + '0)');
            ctx.fillStyle = aur;
            ctx.fillRect(0, 0, vw, vh);
        }

        function drawGround() {
            var fade = clamp((56 - camY) / 34, 0, 1);
            if (fade <= 0) return;
            var a = fade * (pal.dark ? 0.5 : 0.55);
            var i, az;
            ring3(0, 25, 36, 1, a * 0.55, pal.ground);
            ring3(0, 40, 42, 1, a * 0.4, pal.ground);
            ring3(0, 58, 48, 1, a * 0.28, pal.ground);
            for (i = 0; i < 12; i++) {
                az = (i / 12) * TAU;
                line3(Math.cos(az) * 20, 0, Math.sin(az) * 20,
                      Math.cos(az) * 58, 0, Math.sin(az) * 58, 0.8, a * 0.22, pal.ground);
            }
            /* equipment shelter */
            var bx = 20, bz = 13, w = 7, d = 5, h = 4.6;
            var cxs = [bx - w / 2, bx + w / 2];
            var czs = [bz - d / 2, bz + d / 2];
            var xi, zi;
            for (xi = 0; xi < 2; xi++) {
                for (zi = 0; zi < 2; zi++) {
                    line3(cxs[xi], 0, czs[zi], cxs[xi], h, czs[zi], 1, a * 0.8, pal.line);
                }
            }
            for (xi = 0; xi < 2; xi++) {
                line3(cxs[xi], h, czs[0], cxs[xi], h, czs[1], 1, a * 0.8, pal.line);
                line3(cxs[0], h, czs[xi], cxs[1], h, czs[xi], 1, a * 0.8, pal.line);
                line3(cxs[xi], 0, czs[0], cxs[xi], 0, czs[1], 1, a * 0.5, pal.line);
                line3(cxs[0], 0, czs[xi], cxs[1], 0, czs[xi], 1, a * 0.5, pal.line);
            }
            /* cable run from shelter to tower base */
            line3(bx - w / 2, 0.4, bz, halfW(0) * 0.7, 0.4, halfW(0) * 0.7, 0.9, a * 0.6, pal.line);
        }

        function drawLattice() {
            var i, leg, y0, y1, p00, p01, p10, p11;
            var seg = TOWER_H / SEGMENTS;
            /* legs */
            for (leg = 0; leg < 4; leg++) {
                for (i = 0; i < SEGMENTS; i++) {
                    y0 = i * seg; y1 = y0 + seg;
                    p00 = legPoint(leg, y0);
                    p01 = legPoint(leg, y1);
                    line3(p00.x, p00.y, p00.z, p01.x, p01.y, p01.z, 3.2, 0.85, pal.line);
                }
            }
            /* horizontal rings + X-bracing per face */
            for (i = 0; i <= SEGMENTS; i++) {
                y0 = i * seg;
                for (leg = 0; leg < 4; leg++) {
                    var nleg = (leg + 1) % 4;
                    p00 = legPoint(leg, y0);
                    p10 = legPoint(nleg, y0);
                    line3(p00.x, p00.y, p00.z, p10.x, p10.y, p10.z, 1.6, 0.5, pal.line);
                    if (i < SEGMENTS) {
                        y1 = y0 + seg;
                        p01 = legPoint(leg, y1);
                        p11 = legPoint(nleg, y1);
                        line3(p00.x, p00.y, p00.z, p11.x, p11.y, p11.z, 1.1, 0.32, pal.line);
                        line3(p10.x, p10.y, p10.z, p01.x, p01.y, p01.z, 1.1, 0.32, pal.line);
                    }
                }
            }
        }

        /* One microwave dish per platform, each aimed differently */
        var DISH_AZ = [0.5, 2.6, 1.5, 4.4];

        function drawDish(py, az, active, focus, t) {
            var r = halfW(py) + 5;
            var cxd = Math.cos(az) * (r - 0.8);
            var czd = Math.sin(az) * (r - 0.8);
            var cyd = py + 3.4;
            var ux = -Math.sin(az), uz = Math.cos(az);
            var rd = 2.4;
            var n = 14, i, p;
            ctx.beginPath();
            var zSum = 0;
            for (i = 0; i <= n; i++) {
                var ph = (i / n) * TAU;
                var px = cxd + ux * Math.cos(ph) * rd;
                var pyy = cyd + Math.sin(ph) * rd;
                var pz = czd + uz * Math.cos(ph) * rd;
                p = project(px, pyy, pz);
                zSum += p.z;
                if (i === 0) ctx.moveTo(p.x, p.y); else ctx.lineTo(p.x, p.y);
            }
            ctx.closePath();
            var s = shade(zSum / (n + 1));
            var glow = active ? 0.45 + 0.55 * focus : 0;
            ctx.fillStyle = pal.panelFill;
            ctx.fill();
            ctx.strokeStyle = 'rgba(' + (active ? pal.lineStrong : pal.line) + ',' +
                ((0.55 + glow * 0.4) * s).toFixed(3) + ')';
            ctx.lineWidth = active ? 1.6 : 1;
            ctx.stroke();
            /* feed horn strut pointing outward */
            line3(cxd, cyd, czd,
                  cxd + Math.cos(az) * 2.2, cyd, czd + Math.sin(az) * 2.2,
                  1.4, 0.7 + glow * 0.3, active ? pal.lineStrong : pal.line);
            /* mount strut down to the platform */
            line3(cxd, cyd, czd, cxd * 0.92, py, czd * 0.92, 1.2, 0.5, pal.line);
            if (active && !REDUCE_MOTION) {
                /* transmit blip at the feed */
                var bp = project(cxd + Math.cos(az) * 2.2, cyd, czd + Math.sin(az) * 2.2);
                var blip = 0.5 + 0.5 * Math.sin(t * 5);
                ctx.fillStyle = 'rgba(' + pal.lineStrong + ',' + (blip * focus).toFixed(3) + ')';
                ctx.beginPath();
                ctx.arc(bp.x, bp.y, 2.4 + blip * 1.6, 0, TAU);
                ctx.fill();
            }
        }

        function drawPlatform(py, idx, activeIdx, focus, t) {
            var active = idx === activeIdx;
            var f = active ? focus : 0;
            var r = halfW(py) + 5;
            var rgb = active ? pal.lineStrong : pal.line;
            var i, az, p0, p1;
            /* floor + handrail octagons */
            ring3(py, r, 8, active ? 1.8 : 1.2, 0.55 + f * 0.4, rgb, Math.PI / 8);
            ring3(py + 2.6, r, 8, 1, 0.4 + f * 0.3, rgb, Math.PI / 8);
            /* railing posts */
            for (i = 0; i < 8; i++) {
                az = Math.PI / 8 + (i / 8) * TAU;
                line3(Math.cos(az) * r, py, Math.sin(az) * r,
                      Math.cos(az) * r, py + 2.6, Math.sin(az) * r, 1, 0.4 + f * 0.25, rgb);
            }
            /* support struts from the lattice legs */
            for (i = 0; i < 4; i++) {
                var lp = legPoint(i, py - 4);
                az = Math.atan2(LEG_SZ[i], LEG_SX[i]);
                line3(lp.x, lp.y, lp.z,
                      Math.cos(az) * r, py, Math.sin(az) * r, 1.2, 0.4 + f * 0.25, rgb);
            }
            drawDish(py, DISH_AZ[idx], active, focus, t);
            /* active halo */
            if (active && f > 0.05) {
                ring3(py, r + 1.6 + Math.sin(t * 2.2) * 0.5, 24, 2.2, 0.28 * f, pal.lineStrong);
            }
        }

        function drawMastAndAntennas(t) {
            line3(0, TOWER_H, 0, 0, MAST_TOP, 0, 2.6, 0.85, pal.line);
            /* 3 sector antenna panels */
            var i, az;
            for (i = 0; i < 3; i++) {
                az = (i / 3) * TAU + 0.5;
                var mx = Math.cos(az) * 2.8, mz = Math.sin(az) * 2.8;
                var ux = -Math.sin(az) * 0.9, uz = Math.cos(az) * 0.9;
                var yb = 122, yt = 130;
                var c = [
                    project(mx - ux, yb, mz - uz),
                    project(mx + ux, yb, mz + uz),
                    project(mx + ux, yt, mz + uz),
                    project(mx - ux, yt, mz - uz)
                ];
                ctx.beginPath();
                ctx.moveTo(c[0].x, c[0].y);
                ctx.lineTo(c[1].x, c[1].y);
                ctx.lineTo(c[2].x, c[2].y);
                ctx.lineTo(c[3].x, c[3].y);
                ctx.closePath();
                var s = shade((c[0].z + c[2].z) / 2);
                ctx.fillStyle = pal.panelFill;
                ctx.fill();
                ctx.strokeStyle = 'rgba(' + pal.line + ',' + (0.7 * s).toFixed(3) + ')';
                ctx.lineWidth = 1;
                ctx.stroke();
                /* standoff struts to the mast */
                line3(0, 123, 0, mx, 123.5, mz, 1, 0.4, pal.line);
                line3(0, 129, 0, mx, 128.5, mz, 1, 0.4, pal.line);
            }
            /* aviation beacon */
            var bp = project(0, BEACON_Y, 0);
            var pulse = REDUCE_MOTION ? 0.8 : 0.5 + 0.5 * Math.sin(t * 2.6);
            var gr = ctx.createRadialGradient(bp.x, bp.y, 0, bp.x, bp.y, 6 + pulse * 15);
            gr.addColorStop(0, 'rgba(' + pal.beacon + ',' + (0.75 * pulse).toFixed(3) + ')');
            gr.addColorStop(1, 'rgba(' + pal.beacon + ',0)');
            ctx.fillStyle = gr;
            ctx.beginPath();
            ctx.arc(bp.x, bp.y, 6 + pulse * 15, 0, TAU);
            ctx.fill();
            ctx.fillStyle = 'rgba(255,255,255,' + (0.5 + pulse * 0.5).toFixed(3) + ')';
            ctx.beginPath();
            ctx.arc(bp.x, bp.y, 1.6, 0, TAU);
            ctx.fill();
        }

        function drawParticles(dt) {
            if (REDUCE_MOTION) return;
            for (var i = 0; i < particles.length; i++) {
                var pt = particles[i];
                pt.y += pt.sp * dt;
                if (pt.y > TOWER_H) pt.y = 0;
                if (Math.abs(pt.y - camY) > 50) continue;
                var lp = legPoint(pt.leg, pt.y);
                var a = project(lp.x, lp.y, lp.z);
                var tail = legPoint(pt.leg, Math.max(0, pt.y - 2.2));
                var b = project(tail.x, tail.y, tail.z);
                var s = shade(a.z);
                ctx.strokeStyle = 'rgba(' + pal.lineStrong + ',' + (0.3 * s).toFixed(3) + ')';
                ctx.lineWidth = 1.4;
                ctx.beginPath();
                ctx.moveTo(b.x, b.y);
                ctx.lineTo(a.x, a.y);
                ctx.stroke();
                ctx.fillStyle = 'rgba(' + pal.lineStrong + ',' + (0.75 * s).toFixed(3) + ')';
                ctx.beginPath();
                ctx.arc(a.x, a.y, 1.6, 0, TAU);
                ctx.fill();
            }
        }

        function drawRipples(dt, activeIdx, focus, t) {
            if (REDUCE_MOTION) return;
            /* emit */
            if (activeIdx >= 0 && focus > 0.4 && t - lastPlatRipple > 1.5) {
                lastPlatRipple = t;
                ripples.push({ y: PLATFORMS[activeIdx] + 3.2, r: 3, max: 36, str: focus });
            }
            if (t - lastBeaconRipple > 4.2) {
                lastBeaconRipple = t;
                ripples.push({ y: BEACON_Y - 2, r: 2, max: 26, str: 0.7 });
            }
            /* update + draw */
            for (var i = ripples.length - 1; i >= 0; i--) {
                var rp = ripples[i];
                rp.r += dt * 15;
                if (rp.r >= rp.max) { ripples.splice(i, 1); continue; }
                var a = (1 - rp.r / rp.max) * 0.5 * rp.str;
                ring3(rp.y, rp.r, 40, 1.4, a, pal.lineStrong);
            }
        }

        function whooshPalette() {
            /* Match tower palette — Soft Steel light / gate cyan dark. */
            return pal.dark
                ? [pal.lineStrong, pal.line, pal.accent, '125,211,252']
                : [pal.accent, pal.lineStrong, pal.ground, '95,155,190'];
        }

        function spawnWhoosh(strength, yHint) {
            var tones = whooshPalette();
            var rgb = tones[Math.floor(Math.random() * tones.length)];
            whooshes.push({
                y: (yHint != null ? yHint : camY) + (Math.random() - 0.5) * 14,
                az: Math.random() * TAU,
                life: 1,
                str: clamp(strength, 0.25, 1.15),
                rgb: rgb,
                len: 16 + Math.random() * 28,
                twist: (0.55 + Math.random() * 0.9) * (Math.random() < 0.5 ? -1 : 1),
                rad: 6 + Math.random() * 10,
                width: 2.2 + Math.random() * 3.4
            });
            if (whooshes.length > 28) whooshes.splice(0, whooshes.length - 28);
        }

        function drawHelicalWhoosh(w, alphaMul) {
            var steps = 22;
            var i, u, yy, az, r, p, head = null;
            ctx.beginPath();
            for (i = 0; i <= steps; i++) {
                u = i / steps;
                yy = w.y - u * w.len * w.life;
                az = w.az + u * w.twist * Math.PI * w.life;
                r = halfW(Math.max(0, yy)) + w.rad + Math.sin(u * Math.PI) * 5;
                p = project(Math.cos(az) * r, yy, Math.sin(az) * r);
                if (i === 0) {
                    ctx.moveTo(p.x, p.y);
                    head = p;
                } else {
                    ctx.lineTo(p.x, p.y);
                }
            }
            var a = alphaMul * w.str * w.life * 0.85;
            ctx.strokeStyle = 'rgba(' + w.rgb + ',' + a.toFixed(3) + ')';
            ctx.lineWidth = Math.max(1.2, w.width * (0.55 + w.life * 0.7));
            ctx.lineCap = 'round';
            ctx.lineJoin = 'round';
            ctx.stroke();
            if (head && w.life > 0.35) {
                var glow = ctx.createRadialGradient(head.x, head.y, 0, head.x, head.y, 10 + w.width * 2);
                glow.addColorStop(0, 'rgba(' + w.rgb + ',' + (a * 0.55).toFixed(3) + ')');
                glow.addColorStop(1, 'rgba(' + w.rgb + ',0)');
                ctx.fillStyle = glow;
                ctx.beginPath();
                ctx.arc(head.x, head.y, 10 + w.width * 2, 0, TAU);
                ctx.fill();
            }
        }

        /* Screen-space Soft Steel / gate-cyan stripes as you descend. */
        function drawScreenWhoosh(progress, speedBoost, t) {
            var baseA = 0.08 + progress * 0.22 + speedBoost * 0.28;
            if (baseA < 0.04) return;
            var tones = whooshPalette();
            var bands = [
                { rgb: tones[0], phase: 0.00, thick: 14, bend: 0.22 },
                { rgb: tones[1], phase: 0.18, thick: 18, bend: 0.34 },
                { rgb: tones[2], phase: 0.38, thick: 11, bend: 0.18 },
                { rgb: tones[0], phase: 0.58, thick: 15, bend: 0.28 },
                { rgb: tones[3] || tones[1], phase: 0.78, thick: 9, bend: 0.14 }
            ];
            var i, b, travel, y0, x0, x1, cp1x, cp1y, cp2x, cp2y, a;
            ctx.save();
            ctx.globalCompositeOperation = pal.dark ? 'lighter' : 'source-over';
            for (i = 0; i < bands.length; i++) {
                b = bands[i];
                travel = progress * 1.15 + b.phase * 0.2 +
                    (REDUCE_MOTION ? 0 : Math.sin(t * 0.7 + b.phase * 4) * 0.02);
                y0 = -vh * 0.25 + travel * vh * 1.45;
                if (y0 < -vh * 0.4 || y0 > vh * 1.35) continue;
                x0 = -vw * 0.08;
                x1 = vw * 1.08;
                cp1x = vw * (0.28 + b.bend);
                cp1y = y0 + vh * (0.08 + b.bend * 0.4) * (i % 2 ? -1 : 1);
                cp2x = vw * (0.62 - b.bend * 0.5);
                cp2y = y0 + vh * (0.14 + speedBoost * 0.1) * (i % 2 ? 1 : -1);
                a = baseA * (i % 2 ? 0.85 : 1) * (pal.dark ? 1 : 0.72);
                ctx.strokeStyle = 'rgba(' + b.rgb + ',' + a.toFixed(3) + ')';
                ctx.lineWidth = b.thick * (0.85 + speedBoost * 0.55);
                ctx.lineCap = 'round';
                ctx.beginPath();
                ctx.moveTo(x0, y0);
                ctx.bezierCurveTo(cp1x, cp1y, cp2x, cp2y, x1, y0 + vh * 0.12);
                ctx.stroke();
            }
            ctx.restore();
        }

        function updateHelicalWhooshes(dt, t, st, progress, speedBoost) {
            if (REDUCE_MOTION) return;
            var dElev = prevCamY - camY;
            if (dElev > 0.15 && progress > 0.02 && t - lastWhooshSpawn > 0.07) {
                lastWhooshSpawn = t;
                spawnWhoosh(0.35 + speedBoost * 0.8, camY + 6);
                if (speedBoost > 0.45) spawnWhoosh(0.55 + speedBoost * 0.5, camY - 4);
            }
            if (st.active >= 0 && st.focus > 0.55 && st.active !== lastPlatWhoosh) {
                lastPlatWhoosh = st.active;
                spawnWhoosh(1.05, PLATFORMS[st.active] + 4);
                spawnWhoosh(0.85, PLATFORMS[st.active] - 2);
                spawnWhoosh(0.7, PLATFORMS[st.active] + 10);
            }
            if (st.active < 0) lastPlatWhoosh = -1;

            for (var i = whooshes.length - 1; i >= 0; i--) {
                var w = whooshes[i];
                w.life -= dt * (0.55 + speedBoost * 0.65);
                w.y -= dt * (8 + speedBoost * 22);
                w.az += dt * w.twist * 0.55;
                if (w.life <= 0) {
                    whooshes.splice(i, 1);
                    continue;
                }
                drawHelicalWhoosh(w, pal.dark ? 1 : 0.78);
            }
        }

        function whooshMetrics(dt) {
            var progress = clamp((TOP_ELEV - camY) / (TOP_ELEV - BASE_ELEV), 0, 1);
            var dElev = prevCamY - camY;
            var speedBoost = REDUCE_MOTION ? 0
                : clamp(Math.abs(dElev) / Math.max(dt * 55, 0.001), 0, 1);
            return { progress: progress, dElev: dElev, speedBoost: speedBoost };
        }

        function drawWhooshPass(dt, t, st, pass, metrics) {
            if (pass === 'helix') {
                updateHelicalWhooshes(dt, t, st, metrics.progress, metrics.speedBoost);
                if (REDUCE_MOTION && metrics.progress > 0.08) {
                    /* Quiet dual ribbons — identity without chase. */
                    var tones = whooshPalette();
                    var quiet = {
                        y: camY + 2, az: 0.9, life: 0.55, str: 0.45,
                        rgb: tones[0], len: 26, twist: 0.7, rad: 9, width: 2.8
                    };
                    drawHelicalWhoosh(quiet, 0.4);
                    quiet.rgb = tones[1];
                    quiet.az = 2.7;
                    quiet.twist = -0.55;
                    drawHelicalWhoosh(quiet, 0.35);
                }
                prevCamY = camY;
            } else if (pass === 'screen') {
                drawScreenWhoosh(metrics.progress, metrics.speedBoost, t);
            }
        }

        function drawConnector(st, t) {
            if (st.active < 0 || !st.cardEl || st.focus < 0.06 || st.side === 0) return;
            var rect = st.cardEl.getBoundingClientRect();
            if (!rect.width) return;
            var py = PLATFORMS[st.active];
            var r = halfW(py) + 5;
            /* pick the platform octagon point that projects furthest toward the card */
            var best = null, i;
            for (i = 0; i < 8; i++) {
                var az = Math.PI / 8 + (i / 8) * TAU;
                var p = project(Math.cos(az) * r, py, Math.sin(az) * r);
                if (!best || (st.side > 0 ? p.x > best.x : p.x < best.x)) best = p;
            }
            var ex = st.side > 0 ? rect.left - 14 : rect.right + 14;
            var ey = rect.top + Math.min(56, rect.height * 0.3);
            var midX = lerp(best.x, ex, 0.5);
            var a = 0.55 * st.focus;
            ctx.save();
            ctx.strokeStyle = 'rgba(' + pal.lineStrong + ',' + a.toFixed(3) + ')';
            ctx.lineWidth = 1.3;
            ctx.setLineDash([7, 6]);
            ctx.lineDashOffset = REDUCE_MOTION ? 0 : -t * 26;
            ctx.beginPath();
            ctx.moveTo(best.x, best.y);
            ctx.lineTo(midX, best.y);
            ctx.lineTo(midX, ey);
            ctx.lineTo(ex, ey);
            ctx.stroke();
            ctx.restore();
            /* endpoint nodes */
            var pr = REDUCE_MOTION ? 3 : 3 + Math.sin(t * 4) * 1.2;
            ctx.fillStyle = 'rgba(' + pal.lineStrong + ',' + a.toFixed(3) + ')';
            ctx.beginPath();
            ctx.arc(best.x, best.y, pr, 0, TAU);
            ctx.fill();
            ctx.beginPath();
            ctx.arc(ex, ey, 3, 0, TAU);
            ctx.fill();
            ctx.strokeStyle = 'rgba(' + pal.lineStrong + ',' + (a * 0.7).toFixed(3) + ')';
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.arc(best.x, best.y, pr + 4, 0, TAU);
            ctx.stroke();
        }

        function render(now) {
            var t = (now - startT) / 1000;
            var dt = clamp((now - lastT) / 1000, 0, 0.05);
            lastT = now;

            var st = getState();

            if (REDUCE_MOTION) {
                camY = st.elev;
                shift = st.side * -0.16;
            } else {
                var k = 1 - Math.exp(-dt * 4.5);
                camY += (st.elev - camY) * k;
                shift += (st.side * -0.16 - shift) * k * 0.8;
            }

            /* spiral descent: rotation follows elevation, plus a slow idle drift */
            var theta = -0.62 + (TOP_ELEV - camY) * 0.021 +
                (REDUCE_MOTION ? 0 : t * 0.045);
            cosT = Math.cos(theta);
            sinT = Math.sin(theta);

            cx = vw * 0.5 + shift * vw;
            cy = vh * 0.52;
            FOV = vh * 2.05;
            DIST = 150 + clamp((camY - 100) / 27, 0, 1) * 42;

            var zm = whooshMetrics(dt);
            drawBackground(t);
            drawGround();
            drawLattice();
            drawWhooshPass(dt, t, st, 'helix', zm);
            for (var i = 0; i < PLATFORMS.length; i++) {
                drawPlatform(PLATFORMS[i], i, st.active, st.focus, t);
            }
            drawMastAndAntennas(t);
            drawParticles(dt);
            drawRipples(dt, st.active, st.focus, t);
            drawConnector(st, t);
            drawWhooshPass(dt, t, st, 'screen', zm);
        }

        function loop(now) {
            render(now);
            requestAnimationFrame(loop);
        }

        function renderOnce() {
            if (frameQueued) return;
            frameQueued = true;
            requestAnimationFrame(function (now) {
                frameQueued = false;
                render(now);
            });
        }

        window.addEventListener('resize', function () {
            resize();
            if (REDUCE_MOTION) renderOnce();
        });
        document.addEventListener('primenet:theme-change', function () {
            pal = palette();
            if (REDUCE_MOTION) renderOnce();
        });

        resize();
        makeParticles();
        if (REDUCE_MOTION) {
            window.addEventListener('scroll', renderOnce, { passive: true });
            renderOnce();
        } else {
            requestAnimationFrame(loop);
        }

        return { renderOnce: renderOnce };
    }

    /* ------------------------------------------------------------------ */
    /* Page wiring: scroll → elevation mapping, HUD, rail, card reveal.   */
    function initPage() {
        var canvas = document.getElementById('tower-canvas');
        var hero = document.getElementById('tower-hero');
        var baseSec = document.getElementById('tower-base');
        var stops = Array.prototype.slice.call(document.querySelectorAll('.tower-stop'));
        var hudElev = document.getElementById('tower-hud-elev');
        var hudLabel = document.getElementById('tower-hud-label');
        var heroInner = hero ? hero.querySelector('.tower-hero-inner') : null;
        var rail = document.getElementById('tower-rail');
        var railDots = rail ?
            Array.prototype.slice.call(rail.querySelectorAll('.tower-rail-dot')) : [];
        if (!canvas || !hero || !stops.length) return null;

        var keys = [];
        var state = { elev: TOP_ELEV, active: -1, focus: 0, side: 0, cardEl: null };
        var ticking = false;

        function centerKey(el) {
            var r = el.getBoundingClientRect();
            return r.top + window.pageYOffset + r.height / 2 - window.innerHeight / 2;
        }

        function layout() {
            keys = [{ s: centerKey(hero), e: TOP_ELEV }];
            for (var i = 0; i < stops.length; i++) {
                keys.push({ s: centerKey(stops[i]), e: (PLATFORMS[i] || 20) + 9 });
            }
            if (baseSec) keys.push({ s: centerKey(baseSec), e: BASE_ELEV });
        }

        function elevAt(sc) {
            if (sc <= keys[0].s) return keys[0].e;
            var last = keys[keys.length - 1];
            if (sc >= last.s) return last.e;
            for (var i = 0; i < keys.length - 1; i++) {
                var a = keys[i], b = keys[i + 1];
                if (sc >= a.s && sc <= b.s) {
                    var t = b.s === a.s ? 0 : (sc - a.s) / (b.s - a.s);
                    return lerp(a.e, b.e, t);
                }
            }
            return last.e;
        }

        function update() {
            var sc = window.pageYOffset;
            var vc = window.innerHeight / 2;
            state.elev = elevAt(sc);

            var best = -1, bd = 1e9, i, r, d;
            for (i = 0; i < stops.length; i++) {
                r = stops[i].getBoundingClientRect();
                d = Math.abs(r.top + r.height / 2 - vc);
                if (d < bd) { bd = d; best = i; }
            }
            var focus = 1 - Math.min(1, bd / (window.innerHeight * 0.6));
            if (focus <= 0.001) best = -1;
            state.active = best;
            state.focus = clamp(focus, 0, 1);
            var narrow = window.innerWidth < 760;
            state.side = (best < 0 || narrow) ? 0 :
                (stops[best].getAttribute('data-side') === 'left' ? -1 : 1);
            state.cardEl = best >= 0 ? stops[best].querySelector('.tower-card') : null;

            for (i = 0; i < stops.length; i++) {
                stops[i].classList.toggle('is-active', i === best && focus > 0.35);
            }

            if (hudElev) hudElev.textContent = String(Math.max(0, Math.round(state.elev)));
            if (hudLabel) {
                var lbl = 'TOWER TOP';
                if (best >= 0 && focus > 0.3) {
                    lbl = stops[best].getAttribute('data-label') || 'LEVEL';
                } else if (keys.length && sc >= keys[keys.length - 1].s - vc) {
                    lbl = 'GROUND';
                }
                hudLabel.textContent = lbl;
            }

            if (heroInner) {
                var hf = clamp(1 - sc / (window.innerHeight * 0.55), 0, 1);
                heroInner.style.opacity = hf.toFixed(3);
                heroInner.style.transform = 'translateY(' + (-(1 - hf) * 40).toFixed(1) + 'px)';
            }

            for (i = 0; i < railDots.length; i++) {
                var g = railDots[i].getAttribute('data-goto');
                var on = (g === 'hero') ? best < 0 : parseInt(g, 10) === best;
                railDots[i].classList.toggle('is-active', on);
            }
        }

        function onScroll() {
            if (ticking) return;
            ticking = true;
            requestAnimationFrame(function () {
                ticking = false;
                update();
            });
        }

        /* one-time card reveal */
        if ('IntersectionObserver' in window) {
            var obs = new IntersectionObserver(function (entries) {
                entries.forEach(function (en) {
                    if (en.isIntersecting) {
                        en.target.classList.add('in-view');
                        obs.unobserve(en.target);
                    }
                });
            }, { threshold: 0.3 });
            stops.forEach(function (s) { obs.observe(s); });
        } else {
            stops.forEach(function (s) { s.classList.add('in-view'); });
        }

        railDots.forEach(function (dot) {
            dot.addEventListener('click', function () {
                var g = dot.getAttribute('data-goto');
                var target = g === 'hero' ? hero : stops[parseInt(g, 10)];
                if (target) target.scrollIntoView({
                    behavior: REDUCE_MOTION ? 'auto' : 'smooth',
                    block: 'center'
                });
            });
        });

        window.addEventListener('scroll', onScroll, { passive: true });
        window.addEventListener('resize', function () { layout(); update(); });

        layout();
        update();
        init(canvas, function () { return state; });

        return { relayout: function () { layout(); update(); } };
    }

    window.PrimeNetPortalTower = {
        init: init,
        initPage: initPage,
        PLATFORMS: PLATFORMS
    };
})();
