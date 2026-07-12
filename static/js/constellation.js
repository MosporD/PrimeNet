/*
 * PrimeNet constellation / radar canvas engine.
 * Two scenes share this file:
 *   - initLoginScene(canvas): full-screen constellation + radar sweep on the login page.
 *   - initRadar(canvas, opts): dashboard "network constellation radar" panel that
 *     renders live per-technology site counts as orbiting blips.
 * No external libraries — everything is plain canvas 2D so it works under the
 * app's self-only CSP.
 */
(function () {
    'use strict';

    var TECH_COLORS = {
        '2G': '#fbbf24',
        '3G': '#38bdf8',
        '4G-FDD': '#34d399',
        '4G-TDD': '#a78bfa',
        '5G': '#f472b6'
    };
    var DEFAULT_TECH_ORDER = ['2G', '3G', '4G-FDD', '4G-TDD', '5G'];
    var REDUCE_MOTION = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
    var TAU = Math.PI * 2;

    /* Deterministic PRNG so blip layouts stay stable between refreshes. */
    function mulberry32(seed) {
        var a = seed >>> 0;
        return function () {
            a |= 0; a = (a + 0x6D2B79F5) | 0;
            var t = Math.imul(a ^ (a >>> 15), 1 | a);
            t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
            return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
        };
    }

    function hexToRgb(hex) {
        var m = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
        return m ? [parseInt(m[1], 16), parseInt(m[2], 16), parseInt(m[3], 16)] : [125, 211, 252];
    }

    function rgba(hex, alpha) {
        var c = hexToRgb(hex);
        return 'rgba(' + c[0] + ',' + c[1] + ',' + c[2] + ',' + alpha + ')';
    }

    function normalizeAngle(a) {
        a = a % TAU;
        return a < 0 ? a + TAU : a;
    }

    function fitCanvas(canvas, cssW, cssH) {
        var dpr = Math.min(window.devicePixelRatio || 1, 2);
        canvas.width = Math.max(1, Math.round(cssW * dpr));
        canvas.height = Math.max(1, Math.round(cssH * dpr));
        var ctx = canvas.getContext('2d');
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        return ctx;
    }

    function drawSweep(ctx, cx, cy, R, angle, hex, strength) {
        var slices = 26;
        var span = 0.95;
        var i, a1, a2, alpha;
        for (i = 0; i < slices; i++) {
            a1 = angle - (i + 1) * (span / slices);
            a2 = angle - i * (span / slices);
            alpha = (strength || 0.16) * (1 - i / slices);
            ctx.beginPath();
            ctx.moveTo(cx, cy);
            ctx.arc(cx, cy, R, a1, a2);
            ctx.closePath();
            ctx.fillStyle = rgba(hex, alpha);
            ctx.fill();
        }
        ctx.beginPath();
        ctx.moveTo(cx, cy);
        ctx.lineTo(cx + Math.cos(angle) * R, cy + Math.sin(angle) * R);
        ctx.strokeStyle = rgba(hex, 0.85);
        ctx.lineWidth = 1.5;
        ctx.stroke();
    }

    function drawRadarGrid(ctx, cx, cy, R, ringRadii, baseHex) {
        var i, a, tickLen;
        ctx.save();
        for (i = 0; i < ringRadii.length; i++) {
            ctx.beginPath();
            ctx.arc(cx, cy, ringRadii[i], 0, TAU);
            ctx.strokeStyle = rgba(baseHex, 0.12);
            ctx.lineWidth = 1;
            ctx.stroke();
        }
        /* Crosshairs */
        ctx.strokeStyle = rgba(baseHex, 0.10);
        ctx.beginPath();
        ctx.moveTo(cx - R, cy); ctx.lineTo(cx + R, cy);
        ctx.moveTo(cx, cy - R); ctx.lineTo(cx, cy + R);
        ctx.stroke();
        /* Degree ticks every 15deg on the outer ring */
        for (a = 0; a < TAU - 0.001; a += TAU / 24) {
            tickLen = (Math.round(a / (TAU / 24)) % 6 === 0) ? 9 : 4;
            ctx.beginPath();
            ctx.moveTo(cx + Math.cos(a) * (R - tickLen), cy + Math.sin(a) * (R - tickLen));
            ctx.lineTo(cx + Math.cos(a) * R, cy + Math.sin(a) * R);
            ctx.strokeStyle = rgba(baseHex, 0.28);
            ctx.lineWidth = 1;
            ctx.stroke();
        }
        ctx.restore();
    }

    /* ====================================================================
     * LOGIN SCENES — one illustration per login page visit
     * (radar sweep / sonar ping / star map / hex mesh)
     * ==================================================================== */
    var BG_SCENE_KEY = 'primenet-bg-scene';

    var SCENE_PALETTES = {
        radar: {
            light: {
                bgTop: '#e8f0fa', bgBottom: '#f3f7fc',
                tint: 'rgba(37, 99, 235, 0.12)',
                accent: '#2563eb', accentSoft: '#60a5fa', grid: '#93c5fd'
            },
            dark: {
                bgTop: '#020617', bgBottom: '#061336',
                tint: 'rgba(56, 189, 248, 0.05)',
                accent: '#38bdf8', accentSoft: '#7dd3fc', grid: '#60a5fa'
            }
        },
        sonar: {
            light: {
                bgTop: '#ecfdf5', bgBottom: '#f0fdf9',
                tint: 'rgba(45, 212, 191, 0.14)',
                accent: '#059669', accentSoft: '#34d399', grid: '#6ee7b7'
            },
            dark: {
                bgTop: '#021a14', bgBottom: '#042f2a',
                tint: 'rgba(45, 212, 191, 0.06)',
                accent: '#34d399', accentSoft: '#2dd4bf', grid: '#2dd4bf'
            }
        },
        stars: {
            light: {
                bgTop: '#f5f3ff', bgBottom: '#ede9fe',
                tint: 'rgba(167, 139, 250, 0.12)',
                accent: '#7c3aed', accentSoft: '#a78bfa', grid: '#c4b5fd'
            },
            dark: {
                bgTop: '#0b0718', bgBottom: '#15082a',
                tint: 'rgba(167, 139, 250, 0.05)',
                accent: '#a78bfa', accentSoft: '#c4b5fd', grid: '#a78bfa'
            }
        },
        hexmesh: {
            light: {
                bgTop: '#eff6ff', bgBottom: '#f8fafc',
                tint: 'rgba(56, 189, 248, 0.10)',
                accent: '#0284c7', accentSoft: '#38bdf8', grid: '#7dd3fc'
            },
            dark: {
                bgTop: '#020617', bgBottom: '#031028',
                tint: 'rgba(56, 189, 248, 0.04)',
                accent: '#38bdf8', accentSoft: '#60a5fa', grid: '#60a5fa'
            }
        }
    };

    function scenePalette(sceneId) {
        var bucket = SCENE_PALETTES[sceneId] || SCENE_PALETTES.radar;
        var dark = document.body.classList.contains('dark-mode');
        return bucket[dark ? 'dark' : 'light'];
    }

    /** Random on login; reuse session scene elsewhere until next login visit. */
    function pickBackgroundSceneIndex(count, forceRandom) {
        if (!forceRandom) {
            try {
                var saved = sessionStorage.getItem(BG_SCENE_KEY);
                if (saved !== null && saved !== '') {
                    var idx = parseInt(saved, 10);
                    if (idx >= 0 && idx < count) return idx;
                }
            } catch (_) { /* ignore */ }
        }
        var picked = Math.floor(Math.random() * count);
        try { sessionStorage.setItem(BG_SCENE_KEY, String(picked)); } catch (_) { /* ignore */ }
        return picked;
    }

    function initPageBackground(canvas, options) {
        options = options || {};
        var ctx = canvas.getContext('2d');
        var vw = 0, vh = 0, cx = 0, cy = 0, R = 0;
        var mouse = { x: -1e4, y: -1e4 };
        var ripples = [];
        var last = performance.now();

        /* ---------- scene: RADAR SWEEP (constellation + rotating sweep) -- */
        var radar = {
            id: 'radar',
            name: 'RADAR SWEEP',
            tint: 'rgba(56,189,248,0.05)',
            nodes: [],
            sweep: -Math.PI / 2,
            build: function () {
                var tintPool = ['#7dd3fc', '#7dd3fc', '#7dd3fc', '#38bdf8',
                    TECH_COLORS['5G'], TECH_COLORS['4G-FDD'], TECH_COLORS['2G'], TECH_COLORS['4G-TDD']];
                var count = Math.min(170, Math.max(60, Math.round((vw * vh) / 13500)));
                var rand = mulberry32(20260705);
                this.nodes = [];
                for (var i = 0; i < count; i++) {
                    this.nodes.push({
                        x: rand() * vw, y: rand() * vh,
                        vx: (rand() - 0.5) * 14, vy: (rand() - 0.5) * 14,
                        r: 0.8 + rand() * 1.7, tw: rand() * TAU, glow: 0,
                        tint: tintPool[Math.floor(rand() * tintPool.length)]
                    });
                }
            },
            draw: function (dt, t, pal) {
                pal = pal || scenePalette('radar');
                drawRadarGrid(ctx, cx, cy, R, [R * 0.25, R * 0.5, R * 0.75, R], pal.grid);
                if (!REDUCE_MOTION) {
                    this.sweep = normalizeAngle(this.sweep + dt * (TAU / 7));
                    drawSweep(ctx, cx, cy, R, this.sweep, pal.accent, 0.13);
                }
                ctx.beginPath();
                ctx.arc(cx, cy, 3.2, 0, TAU);
                ctx.fillStyle = rgba(pal.accentSoft, 0.9);
                ctx.fill();

                var nodes = this.nodes;
                var i, j, n, m, dx, dy, dist;
                for (i = 0; i < nodes.length; i++) {
                    n = nodes[i];
                    if (!REDUCE_MOTION) {
                        n.x += n.vx * dt;
                        n.y += n.vy * dt;
                        dx = mouse.x - n.x; dy = mouse.y - n.y;
                        dist = Math.sqrt(dx * dx + dy * dy);
                        if (dist < 150 && dist > 0.001) {
                            n.x += (dx / dist) * 9 * dt;
                            n.y += (dy / dist) * 9 * dt;
                        }
                        if (n.x < -12) n.x = vw + 12; else if (n.x > vw + 12) n.x = -12;
                        if (n.y < -12) n.y = vh + 12; else if (n.y > vh + 12) n.y = -12;
                        dx = n.x - cx; dy = n.y - cy;
                        if (dx * dx + dy * dy < R * R) {
                            var diff = normalizeAngle(this.sweep - Math.atan2(dy, dx));
                            if (diff < 0.06) n.glow = 1;
                        }
                        n.glow *= Math.exp(-dt * 1.6);
                    }
                }
                for (i = 0; i < nodes.length; i++) {
                    n = nodes[i];
                    for (j = i + 1; j < nodes.length; j++) {
                        m = nodes[j];
                        dx = n.x - m.x; dy = n.y - m.y;
                        var d2 = dx * dx + dy * dy;
                        if (d2 < 110 * 110) {
                            ctx.beginPath();
                            ctx.moveTo(n.x, n.y);
                            ctx.lineTo(m.x, m.y);
                            ctx.strokeStyle = 'rgba(125,211,252,' + (0.10 * (1 - Math.sqrt(d2) / 110)).toFixed(3) + ')';
                            ctx.lineWidth = 1;
                            ctx.stroke();
                        }
                    }
                    dx = n.x - mouse.x; dy = n.y - mouse.y;
                    dist = Math.sqrt(dx * dx + dy * dy);
                    if (dist < 170) {
                        ctx.beginPath();
                        ctx.moveTo(n.x, n.y);
                        ctx.lineTo(mouse.x, mouse.y);
                        ctx.strokeStyle = 'rgba(56,189,248,' + (0.22 * (1 - dist / 170)).toFixed(3) + ')';
                        ctx.lineWidth = 1;
                        ctx.stroke();
                    }
                }
                for (i = 0; i < nodes.length; i++) {
                    n = nodes[i];
                    var alpha = 0.35 + 0.25 * Math.sin(t * 1.4 + n.tw) + n.glow * 0.55;
                    var radius = n.r + n.glow * 2.4;
                    ctx.beginPath();
                    ctx.arc(n.x, n.y, radius, 0, TAU);
                    ctx.fillStyle = rgba(n.tint, Math.max(0.08, Math.min(1, alpha)));
                    ctx.fill();
                    if (n.glow > 0.35) {
                        ctx.beginPath();
                        ctx.arc(n.x, n.y, radius + 5 * n.glow, 0, TAU);
                        ctx.strokeStyle = rgba(n.tint, 0.35 * n.glow);
                        ctx.lineWidth = 1;
                        ctx.stroke();
                    }
                }
            }
        };

        /* ---------- scene: SONAR PING (expanding waves + contacts) ------- */
        var sonar = {
            id: 'sonar',
            name: 'SONAR PING',
            tint: 'rgba(45,212,191,0.06)',
            contacts: [],
            pings: [],
            pingTimer: 0.4,
            build: function () {
                var rand = mulberry32(0x50AA12);
                this.contacts = [];
                for (var i = 0; i < 26; i++) {
                    var a = rand() * TAU;
                    var r = R * (0.15 + rand() * 0.82);
                    this.contacts.push({
                        angle: a, dist: r, drift: (rand() - 0.5) * 0.05,
                        size: 1.6 + rand() * 2.2, glow: 0
                    });
                }
                this.pings = [];
                this.pingTimer = 0.4;
            },
            draw: function (dt, t, pal) {
                pal = pal || scenePalette('sonar');
                var green = pal.accent;
                var teal = pal.accentSoft;
                /* dashed range rings + bearing ticks */
                ctx.save();
                ctx.setLineDash([4, 10]);
                for (var k = 1; k <= 4; k++) {
                    ctx.beginPath();
                    ctx.arc(cx, cy, R * k / 4, 0, TAU);
                    ctx.strokeStyle = rgba(teal, 0.13);
                    ctx.lineWidth = 1;
                    ctx.stroke();
                }
                ctx.restore();
                ctx.strokeStyle = rgba(teal, 0.10);
                ctx.beginPath();
                ctx.moveTo(cx - R, cy); ctx.lineTo(cx + R, cy);
                ctx.moveTo(cx, cy - R); ctx.lineTo(cx, cy + R);
                ctx.stroke();
                for (var a = 0; a < TAU - 0.001; a += TAU / 36) {
                    ctx.beginPath();
                    ctx.moveTo(cx + Math.cos(a) * (R - 5), cy + Math.sin(a) * (R - 5));
                    ctx.lineTo(cx + Math.cos(a) * R, cy + Math.sin(a) * R);
                    ctx.strokeStyle = rgba(teal, 0.25);
                    ctx.stroke();
                }

                /* expanding pings */
                if (!REDUCE_MOTION) {
                    this.pingTimer -= dt;
                    if (this.pingTimer <= 0) {
                        this.pings.push({ r: 6, a: 0.55 });
                        this.pingTimer = 3.2;
                    }
                }
                for (var p = this.pings.length - 1; p >= 0; p--) {
                    var ping = this.pings[p];
                    if (!REDUCE_MOTION) {
                        ping.r += dt * R * 0.30;
                        ping.a = 0.55 * (1 - ping.r / R);
                    }
                    if (ping.r >= R) { this.pings.splice(p, 1); continue; }
                    ctx.beginPath();
                    ctx.arc(cx, cy, ping.r, 0, TAU);
                    ctx.strokeStyle = rgba(teal, Math.max(0, ping.a));
                    ctx.lineWidth = 2;
                    ctx.stroke();
                    /* light up contacts as the wavefront crosses them */
                    for (var c = 0; c < this.contacts.length; c++) {
                        if (Math.abs(this.contacts[c].dist - ping.r) < 9) this.contacts[c].glow = 1;
                    }
                }

                /* contacts */
                for (var i = 0; i < this.contacts.length; i++) {
                    var ct = this.contacts[i];
                    if (!REDUCE_MOTION) {
                        ct.angle += ct.drift * dt;
                        ct.glow *= Math.exp(-dt * 0.9);
                    } else {
                        ct.glow = 0.6;
                    }
                    var x = cx + Math.cos(ct.angle) * ct.dist;
                    var y = cy + Math.sin(ct.angle) * ct.dist;
                    var alpha = 0.10 + ct.glow * 0.85;
                    ctx.beginPath();
                    ctx.arc(x, y, ct.size + ct.glow * 2, 0, TAU);
                    ctx.fillStyle = rgba(green, alpha);
                    ctx.fill();
                    if (ct.glow > 0.3) {
                        ctx.beginPath();
                        ctx.arc(x, y, ct.size + 6 * ct.glow, 0, TAU);
                        ctx.strokeStyle = rgba(green, 0.3 * ct.glow);
                        ctx.lineWidth = 1;
                        ctx.stroke();
                    }
                }

                /* hub + cursor reticle */
                ctx.beginPath();
                ctx.arc(cx, cy, 3, 0, TAU);
                ctx.fillStyle = rgba(green, 0.9);
                ctx.fill();
                if (mouse.x > -1e3) {
                    ctx.beginPath();
                    ctx.arc(mouse.x, mouse.y, 14, 0, TAU);
                    ctx.strokeStyle = rgba(green, 0.35);
                    ctx.lineWidth = 1;
                    ctx.stroke();
                    ctx.beginPath();
                    ctx.moveTo(mouse.x - 20, mouse.y); ctx.lineTo(mouse.x - 8, mouse.y);
                    ctx.moveTo(mouse.x + 8, mouse.y); ctx.lineTo(mouse.x + 20, mouse.y);
                    ctx.moveTo(mouse.x, mouse.y - 20); ctx.lineTo(mouse.x, mouse.y - 8);
                    ctx.moveTo(mouse.x, mouse.y + 8); ctx.lineTo(mouse.x, mouse.y + 20);
                    ctx.strokeStyle = rgba(green, 0.5);
                    ctx.stroke();
                }
            }
        };

        /* ---------- scene: STAR MAP (starfield + constellation figures) -- */
        var stars = {
            id: 'stars',
            name: 'STAR MAP',
            tint: 'rgba(167,139,250,0.05)',
            field: [],
            figures: [],
            shooting: null,
            shootTimer: 4,
            build: function () {
                var rand = mulberry32(0x57A125);
                var count = Math.min(260, Math.max(120, Math.round((vw * vh) / 6500)));
                this.field = [];
                for (var i = 0; i < count; i++) {
                    this.field.push({
                        x: rand() * vw, y: rand() * vh,
                        z: 0.3 + rand() * 0.7,            /* parallax depth */
                        r: 0.5 + rand() * 1.4,
                        tw: rand() * TAU
                    });
                }
                /* constellation figures: small connected clusters of bright stars */
                this.figures = [];
                for (var f = 0; f < 5; f++) {
                    var fx = vw * (0.12 + rand() * 0.76);
                    var fy = vh * (0.12 + rand() * 0.76);
                    var pts = [];
                    var px = fx, py = fy;
                    var steps = 5 + Math.floor(rand() * 3);
                    for (var s = 0; s < steps; s++) {
                        pts.push({ x: px, y: py, tw: rand() * TAU });
                        var ang = rand() * TAU;
                        px += Math.cos(ang) * (50 + rand() * 90);
                        py += Math.sin(ang) * (40 + rand() * 70);
                    }
                    this.figures.push(pts);
                }
                this.shooting = null;
                this.shootTimer = 3 + rand() * 3;
            },
            draw: function (dt, t, pal) {
                pal = pal || scenePalette('stars');
                var offX = (mouse.x > -1e3 ? (mouse.x - vw / 2) : 0) * 0.012;
                var offY = (mouse.y > -1e3 ? (mouse.y - vh / 2) : 0) * 0.012;
                var starFill = document.body.classList.contains('dark-mode') ? '226,238,255' : '30,41,59';

                for (var i = 0; i < this.field.length; i++) {
                    var st = this.field[i];
                    var alpha = 0.25 + 0.35 * (0.5 + 0.5 * Math.sin(t * 1.6 + st.tw)) * st.z;
                    ctx.beginPath();
                    ctx.arc(st.x - offX * st.z * 10, st.y - offY * st.z * 10, st.r, 0, TAU);
                    ctx.fillStyle = 'rgba(' + starFill + ',' + alpha.toFixed(3) + ')';
                    ctx.fill();
                }

                /* constellation figures */
                for (var f = 0; f < this.figures.length; f++) {
                    var pts = this.figures[f];
                    ctx.beginPath();
                    for (var p = 0; p < pts.length; p++) {
                        var x = pts[p].x - offX * 8, y = pts[p].y - offY * 8;
                        if (p === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
                    }
                    ctx.strokeStyle = rgba(pal.accentSoft, 0.22);
                    ctx.lineWidth = 1;
                    ctx.stroke();
                    for (p = 0; p < pts.length; p++) {
                        var vx = pts[p].x - offX * 8, vy = pts[p].y - offY * 8;
                        var va = 0.55 + 0.35 * Math.sin(t * 1.2 + pts[p].tw);
                        ctx.beginPath();
                        ctx.arc(vx, vy, 2.1, 0, TAU);
                        ctx.fillStyle = rgba(pal.accentSoft, va);
                        ctx.fill();
                        /* link bright vertices to a nearby cursor */
                        var dx = vx - mouse.x, dy = vy - mouse.y;
                        var dist = Math.sqrt(dx * dx + dy * dy);
                        if (dist < 190) {
                            ctx.beginPath();
                            ctx.moveTo(vx, vy);
                            ctx.lineTo(mouse.x, mouse.y);
                            ctx.strokeStyle = rgba(pal.accentSoft, 0.28 * (1 - dist / 190));
                            ctx.stroke();
                        }
                    }
                }

                /* occasional shooting star */
                if (!REDUCE_MOTION) {
                    if (!this.shooting) {
                        this.shootTimer -= dt;
                        if (this.shootTimer <= 0) {
                            var ang2 = Math.PI * (0.15 + Math.random() * 0.2);
                            this.shooting = {
                                x: vw * (0.1 + Math.random() * 0.8), y: vh * 0.08,
                                vx: Math.cos(ang2) * 620, vy: Math.sin(ang2) * 620,
                                life: 0.9
                            };
                            this.shootTimer = 4 + Math.random() * 5;
                        }
                    } else {
                        var sh = this.shooting;
                        sh.x += sh.vx * dt; sh.y += sh.vy * dt; sh.life -= dt;
                        if (sh.life <= 0 || sh.x > vw + 60 || sh.y > vh + 60) {
                            this.shooting = null;
                        } else {
                            var trail = 46;
                            var grad = ctx.createLinearGradient(sh.x, sh.y, sh.x - sh.vx / 620 * trail, sh.y - sh.vy / 620 * trail);
                            grad.addColorStop(0, 'rgba(255,255,255,' + (0.85 * sh.life).toFixed(3) + ')');
                            grad.addColorStop(1, 'rgba(255,255,255,0)');
                            ctx.beginPath();
                            ctx.moveTo(sh.x, sh.y);
                            ctx.lineTo(sh.x - sh.vx / 620 * trail, sh.y - sh.vy / 620 * trail);
                            ctx.strokeStyle = grad;
                            ctx.lineWidth = 1.6;
                            ctx.stroke();
                        }
                    }
                }
            }
        };

        /* ---------- scene: HEX MESH (cellular coverage grid) ------------- */
        var hexmesh = {
            id: 'hexmesh',
            name: 'HEX MESH',
            tint: 'rgba(56,189,248,0.04)',
            cells: [],
            waves: [],
            waveTimer: 0.6,
            size: 44,
            build: function () {
                var size = this.size;
                var w = size * Math.sqrt(3);
                var rand = mulberry32(0x4E7);
                var sitePool = [TECH_COLORS['2G'], TECH_COLORS['3G'], TECH_COLORS['4G-FDD'], TECH_COLORS['4G-TDD'], TECH_COLORS['5G']];
                this.cells = [];
                for (var row = -1; row * size * 1.5 < vh + size; row++) {
                    for (var col = -1; col * w < vw + w; col++) {
                        var x = col * w + (row % 2 ? w / 2 : 0);
                        var y = row * size * 1.5;
                        var site = rand() < 0.06;
                        this.cells.push({
                            x: x, y: y, glow: 0, tw: rand() * TAU,
                            site: site,
                            color: site ? sitePool[Math.floor(rand() * sitePool.length)] : '#60a5fa'
                        });
                    }
                }
                this.waves = [];
                this.waveTimer = 0.6;
            },
            hexPath: function (x, y, size) {
                ctx.beginPath();
                for (var k = 0; k < 6; k++) {
                    var a = Math.PI / 3 * k + Math.PI / 6;
                    var px = x + Math.cos(a) * size;
                    var py = y + Math.sin(a) * size;
                    if (k === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
                }
                ctx.closePath();
            },
            draw: function (dt, t, pal) {
                pal = pal || scenePalette('hexmesh');
                if (!REDUCE_MOTION) {
                    this.waveTimer -= dt;
                    if (this.waveTimer <= 0 && this.waves.length < 3) {
                        var seed = this.cells[Math.floor(Math.random() * this.cells.length)];
                        if (seed) this.waves.push({ x: seed.x, y: seed.y, r: 10 });
                        this.waveTimer = 2.6;
                    }
                    for (var wv = this.waves.length - 1; wv >= 0; wv--) {
                        this.waves[wv].r += dt * 340;
                        if (this.waves[wv].r > Math.max(vw, vh) * 1.1) this.waves.splice(wv, 1);
                    }
                }
                var drawSize = this.size - 3;
                for (var i = 0; i < this.cells.length; i++) {
                    var cell = this.cells[i];
                    var glow = 0;
                    /* wavefront band */
                    for (var w2 = 0; w2 < this.waves.length; w2++) {
                        var dxw = cell.x - this.waves[w2].x, dyw = cell.y - this.waves[w2].y;
                        var band = Math.abs(Math.sqrt(dxw * dxw + dyw * dyw) - this.waves[w2].r);
                        if (band < 70) glow = Math.max(glow, 1 - band / 70);
                    }
                    /* cursor highlight */
                    var dxm = cell.x - mouse.x, dym = cell.y - mouse.y;
                    var dm = Math.sqrt(dxm * dxm + dym * dym);
                    if (dm < 160) glow = Math.max(glow, 0.85 * (1 - dm / 160));

                    var base = cell.site ? 0.16 : 0.05;
                    var alpha = base + glow * 0.5 + (cell.site ? 0.06 * Math.sin(t * 1.5 + cell.tw) : 0);
                    this.hexPath(cell.x, cell.y, drawSize);
                    ctx.strokeStyle = rgba(cell.color, Math.min(0.85, alpha));
                    ctx.lineWidth = cell.site ? 1.3 : 1;
                    ctx.stroke();
                    if (cell.site) {
                        this.hexPath(cell.x, cell.y, drawSize);
                        ctx.fillStyle = rgba(cell.color, 0.05 + glow * 0.10);
                        ctx.fill();
                        ctx.beginPath();
                        ctx.arc(cell.x, cell.y, 2.2 + glow * 1.5, 0, TAU);
                        ctx.fillStyle = rgba(cell.color, 0.5 + glow * 0.5);
                        ctx.fill();
                    }
                }
            }
        };

        var scenes = [radar, sonar, stars, hexmesh];
        var current = pickBackgroundSceneIndex(scenes.length, !!options.pickRandom);

        function drawScene(scene, dt, t) {
            var pal = scenePalette(scene.id);
            var bg = ctx.createLinearGradient(0, 0, 0, vh);
            bg.addColorStop(0, pal.bgTop);
            bg.addColorStop(1, pal.bgBottom);
            ctx.fillStyle = bg;
            ctx.fillRect(0, 0, vw, vh);
            ctx.save();
            var tint = ctx.createRadialGradient(cx, cy, 0, cx, cy, Math.max(vw, vh) * 0.8);
            tint.addColorStop(0, pal.tint);
            tint.addColorStop(1, 'rgba(0,0,0,0)');
            ctx.fillStyle = tint;
            ctx.fillRect(0, 0, vw, vh);
            if (!document.body.classList.contains('dark-mode')) ctx.globalAlpha = 0.78;
            scene.draw(dt, t, pal);
            ctx.restore();
        }

        function resize() {
            vw = window.innerWidth;
            vh = window.innerHeight;
            ctx = fitCanvas(canvas, vw, vh);
            cx = vw > 980 ? vw * 0.33 : vw * 0.5;
            cy = vh * 0.52;
            R = Math.min(vw, vh) * 0.46;
            for (var i = 0; i < scenes.length; i++) scenes[i].build();
            if (REDUCE_MOTION) frame(performance.now(), true);
        }

        function frame(now, single) {
            var dt = Math.min(0.05, (now - last) / 1000);
            last = now;
            var t = now / 1000;
            ctx.clearRect(0, 0, vw, vh);
            drawScene(scenes[current], dt, t);

            var ripplePal = scenePalette(scenes[current].id);

            /* click ripples on top of any scene */
            for (var i = ripples.length - 1; i >= 0; i--) {
                var rp = ripples[i];
                rp.r += dt * 160;
                rp.a -= dt * 1.1;
                if (rp.a <= 0) { ripples.splice(i, 1); continue; }
                ctx.beginPath();
                ctx.arc(rp.x, rp.y, rp.r, 0, TAU);
                ctx.strokeStyle = rgba(ripplePal.accent, rp.a);
                ctx.lineWidth = 1.4;
                ctx.stroke();
            }

            if (!REDUCE_MOTION && !single) requestAnimationFrame(frame);
        }

        window.addEventListener('resize', resize);
        window.addEventListener('mousemove', function (e) {
            mouse.x = e.clientX;
            mouse.y = e.clientY;
        });
        window.addEventListener('mouseleave', function () {
            mouse.x = -1e4; mouse.y = -1e4;
        });
        window.addEventListener('pointerdown', function (e) {
            ripples.push({ x: e.clientX, y: e.clientY, r: 4, a: 0.8 });
        });
        document.addEventListener('primenet:theme-change', function () {
            if (REDUCE_MOTION) frame(performance.now(), true);
        });

        resize();
        if (REDUCE_MOTION) {
            frame(performance.now(), true);
        } else {
            requestAnimationFrame(frame);
        }

        return {
            names: scenes.map(function (s) { return s.name; }),
            getScene: function () { return current; },
            setActivity: function () { /* login scenes — no activity pacing */ }
        };
    }

    function initLoginScene(canvas) {
        return initPageBackground(canvas, { pickRandom: true });
    }

    function initAmbientBackground(canvas) {
        return initPageBackground(canvas, { pickRandom: false });
    }

    /* ====================================================================
     * DASHBOARD RADAR — live per-technology site counts as orbiting blips
     * ==================================================================== */
    function initRadar(canvas, opts) {
        opts = opts || {};
        var ctx = canvas.getContext('2d');
        var wrap = canvas.parentElement;
        var tooltipEl = opts.tooltipEl || null;
        var onSelect = typeof opts.onSelect === 'function' ? opts.onSelect : null;
        var vw = 0, vh = 0, cx = 0, cy = 0, R = 0;
        var orbits = [];   /* [{key,title,subtitle,color,count,vendors,radiusFactor,blips:[]}] */
        var sweep = -Math.PI / 2;
        var focusKey = null;
        var hoverBlip = null;
        var mouse = { x: -1e4, y: -1e4 };
        var last = performance.now();
        var running = false;

        function blipCountFor(count) {
            if (!count || count <= 0) return 0;
            return Math.max(4, Math.min(26, Math.round(3 + Math.sqrt(count))));
        }

        function setData(columns, total) {
            var cols = Array.isArray(columns) ? columns : [];
            orbits = [];
            var i, col, key, n, b, rand;
            for (i = 0; i < DEFAULT_TECH_ORDER.length; i++) {
                key = DEFAULT_TECH_ORDER[i];
                col = null;
                for (var k = 0; k < cols.length; k++) {
                    if (String(cols[k].key) === key) { col = cols[k]; break; }
                }
                var count = col ? Number(col.count || 0) : 0;
                var vendors = (col && col.vendor_counts) || {};
                var orbit = {
                    key: key,
                    title: (col && col.title) || key,
                    subtitle: (col && col.subtitle) || '',
                    color: TECH_COLORS[key] || '#7dd3fc',
                    count: count,
                    huawei: Number(vendors.Huawei || 0),
                    nokia: Number(vendors.Nokia || 0),
                    radiusFactor: 0.30 + 0.16 * i,
                    dir: (i % 2 === 0) ? 1 : -1,
                    blips: []
                };
                n = blipCountFor(count);
                rand = mulberry32(0x5150 + i * 977);
                for (b = 0; b < n; b++) {
                    orbit.blips.push({
                        angle0: rand() * TAU,
                        speed: (0.02 + rand() * 0.035) * orbit.dir,
                        jitter: (rand() - 0.5) * 0.05,
                        size: 2.2 + rand() * 1.6,
                        glow: 0,
                        x: 0, y: 0
                    });
                }
                orbits.push(orbit);
            }
            if (opts.centerEl) {
                opts.centerEl.textContent = (total != null ? Number(total) : 0).toLocaleString();
            }
        }

        function resize() {
            var rect = wrap.getBoundingClientRect();
            vw = Math.max(200, rect.width);
            vh = Math.max(200, rect.height);
            ctx = fitCanvas(canvas, vw, vh);
            cx = vw / 2;
            cy = vh / 2;
            R = Math.min(vw, vh) / 2 - 16;
            if (REDUCE_MOTION) frame(performance.now(), true);
        }

        function orbitRadius(orbit) {
            return R * orbit.radiusFactor;
        }

        function frame(now, single) {
            var dt = Math.min(0.05, (now - last) / 1000);
            last = now;
            var t = now / 1000;
            ctx.clearRect(0, 0, vw, vh);

            /* Background glow */
            var bg = ctx.createRadialGradient(cx, cy, R * 0.05, cx, cy, R);
            bg.addColorStop(0, 'rgba(37,99,235,0.16)');
            bg.addColorStop(0.65, 'rgba(8,24,58,0.10)');
            bg.addColorStop(1, 'rgba(2,8,26,0)');
            ctx.fillStyle = bg;
            ctx.beginPath();
            ctx.arc(cx, cy, R, 0, TAU);
            ctx.fill();

            drawRadarGrid(ctx, cx, cy, R, [], '#60a5fa');

            /* Orbit rings */
            var i, orbit, orAlpha;
            for (i = 0; i < orbits.length; i++) {
                orbit = orbits[i];
                var focused = focusKey === orbit.key;
                var dimmed = focusKey && !focused;
                orAlpha = focused ? 0.55 : (dimmed ? 0.06 : 0.18);
                ctx.beginPath();
                ctx.arc(cx, cy, orbitRadius(orbit), 0, TAU);
                ctx.strokeStyle = rgba(orbit.color, orAlpha);
                ctx.lineWidth = focused ? 1.8 : 1;
                if (orbit.count === 0) ctx.setLineDash([3, 7]);
                ctx.stroke();
                ctx.setLineDash([]);
            }

            if (!REDUCE_MOTION && !single) {
                sweep = normalizeAngle(sweep + dt * (TAU / 6.5));
            }
            drawSweep(ctx, cx, cy, R, sweep, '#38bdf8', 0.11);

            /* Blips */
            hoverBlip = null;
            var bestDist = 18 * 18;
            for (i = 0; i < orbits.length; i++) {
                orbit = orbits[i];
                var dimOrbit = focusKey && focusKey !== orbit.key;
                var orbR = orbitRadius(orbit);
                for (var b = 0; b < orbit.blips.length; b++) {
                    var blip = orbit.blips[b];
                    var ang = normalizeAngle(blip.angle0 + (REDUCE_MOTION ? 0 : blip.speed * t * TAU * 0.15));
                    var r = orbR * (1 + blip.jitter);
                    blip.x = cx + Math.cos(ang) * r;
                    blip.y = cy + Math.sin(ang) * r;

                    var diff = normalizeAngle(sweep - ang);
                    if (diff < 0.07) blip.glow = 1;
                    blip.glow *= Math.exp(-dt * 1.4);

                    var mdx = mouse.x - blip.x, mdy = mouse.y - blip.y;
                    var md2 = mdx * mdx + mdy * mdy;
                    if (md2 < bestDist && !dimOrbit) {
                        bestDist = md2;
                        hoverBlip = { orbit: orbit, blip: blip };
                    }

                    var alpha = dimOrbit ? 0.10 : (0.45 + blip.glow * 0.55);
                    var size = blip.size + blip.glow * 2.0;
                    ctx.beginPath();
                    ctx.arc(blip.x, blip.y, size, 0, TAU);
                    ctx.fillStyle = rgba(orbit.color, Math.min(1, alpha));
                    ctx.fill();
                    if (blip.glow > 0.3 && !dimOrbit) {
                        ctx.beginPath();
                        ctx.arc(blip.x, blip.y, size + 5 * blip.glow, 0, TAU);
                        ctx.strokeStyle = rgba(orbit.color, 0.35 * blip.glow);
                        ctx.lineWidth = 1;
                        ctx.stroke();
                    }
                }
            }

            /* Hovered blip halo */
            if (hoverBlip) {
                ctx.beginPath();
                ctx.arc(hoverBlip.blip.x, hoverBlip.blip.y, hoverBlip.blip.size + 6, 0, TAU);
                ctx.strokeStyle = rgba(hoverBlip.orbit.color, 0.9);
                ctx.lineWidth = 1.5;
                ctx.stroke();
            }
            canvas.style.cursor = hoverBlip ? 'pointer' : 'default';
            updateTooltip();

            /* Hub */
            ctx.beginPath();
            ctx.arc(cx, cy, R * 0.16, 0, TAU);
            ctx.strokeStyle = 'rgba(125,211,252,0.30)';
            ctx.lineWidth = 1;
            ctx.stroke();
            ctx.beginPath();
            ctx.arc(cx, cy, 2.6, 0, TAU);
            ctx.fillStyle = 'rgba(125,211,252,0.9)';
            ctx.fill();

            if (!REDUCE_MOTION && !single && running) requestAnimationFrame(frame);
        }

        function updateTooltip() {
            if (!tooltipEl) return;
            if (!hoverBlip) {
                tooltipEl.hidden = true;
                return;
            }
            var o = hoverBlip.orbit;
            tooltipEl.innerHTML =
                '<div class="radar-tip-title"><span class="radar-tip-dot" style="background:' + o.color + '"></span>' +
                o.title + (o.subtitle ? ' <small>' + o.subtitle + '</small>' : '') + '</div>' +
                '<div class="radar-tip-row"><span>On-air sites</span><strong>' + o.count.toLocaleString() + '</strong></div>' +
                '<div class="radar-tip-row"><span>Huawei</span><strong>' + o.huawei.toLocaleString() + '</strong></div>' +
                '<div class="radar-tip-row"><span>Nokia</span><strong>' + o.nokia.toLocaleString() + '</strong></div>';
            tooltipEl.hidden = false;
            var pad = 14;
            var x = hoverBlip.blip.x + pad;
            var y = hoverBlip.blip.y + pad;
            if (x + tooltipEl.offsetWidth > vw - 8) x = hoverBlip.blip.x - tooltipEl.offsetWidth - pad;
            if (y + tooltipEl.offsetHeight > vh - 8) y = hoverBlip.blip.y - tooltipEl.offsetHeight - pad;
            tooltipEl.style.left = Math.max(4, x) + 'px';
            tooltipEl.style.top = Math.max(4, y) + 'px';
        }

        canvas.addEventListener('mousemove', function (e) {
            var rect = canvas.getBoundingClientRect();
            mouse.x = e.clientX - rect.left;
            mouse.y = e.clientY - rect.top;
            if (REDUCE_MOTION) frame(performance.now(), true);
        });
        canvas.addEventListener('mouseleave', function () {
            mouse.x = -1e4; mouse.y = -1e4;
            if (tooltipEl) tooltipEl.hidden = true;
        });
        canvas.addEventListener('click', function () {
            if (hoverBlip && onSelect) onSelect(hoverBlip.orbit.key);
        });
        window.addEventListener('resize', resize);

        setData(opts.columns, opts.total);
        resize();
        running = true;
        if (REDUCE_MOTION) {
            frame(performance.now(), true);
        } else {
            requestAnimationFrame(frame);
        }

        return {
            update: function (columns, total) {
                setData(columns, total);
                if (REDUCE_MOTION) frame(performance.now(), true);
            },
            setFocus: function (key) {
                focusKey = key || null;
                if (REDUCE_MOTION) frame(performance.now(), true);
            },
            getFocus: function () { return focusKey; },
            colors: TECH_COLORS
        };
    }

    /* ====================================================================
     * JORDAN SITE MAP — real site positions on a stylized country outline
     * ==================================================================== */

    /* Simplified Jordan border, [lon, lat], clockwise from the NW corner. */
    var JORDAN_OUTLINE = [
        [35.56, 32.64], [35.79, 32.74], [36.06, 32.66], [36.41, 32.38],
        [36.83, 32.31], [37.77, 32.74], [38.79, 33.37],
        [39.15, 32.13],
        [37.00, 31.50],
        [37.98, 30.49], [37.65, 30.33],
        [36.75, 29.87], [36.07, 29.19],
        [34.96, 29.36],
        [35.00, 29.55], [35.16, 30.40], [35.29, 31.15], [35.46, 31.40],
        [35.55, 31.77], [35.53, 32.10], [35.57, 32.38]
    ];
    var JORDAN_CITIES = [
        { name: 'AMMAN', lon: 35.93, lat: 31.95 },
        { name: 'IRBID', lon: 35.85, lat: 32.55 },
        { name: 'AQABA', lon: 35.00, lat: 29.53 }
    ];

    function initJordanMap(canvas, opts) {
        opts = opts || {};
        var ctx = canvas.getContext('2d');
        var wrap = canvas.parentElement;
        var tooltipEl = opts.tooltipEl || null;
        var vw = 0, vh = 0;
        var sites = [];        /* {id, name, area, lat, lon, x, y, tw, glow} */
        var sweep = -Math.PI / 2;
        var mouse = { x: -1e4, y: -1e4 };
        var hoverSite = null;
        var last = performance.now();

        /* Equirectangular projection fitted to the canvas. */
        var proj = { scale: 1, ox: 0, oy: 0, lonK: Math.cos(31.4 * Math.PI / 180) };
        var sweepCx = 0, sweepCy = 0, sweepR = 0;

        function fitProjection() {
            var lons = JORDAN_OUTLINE.map(function (p) { return p[0]; });
            var lats = JORDAN_OUTLINE.map(function (p) { return p[1]; });
            var lonMin = Math.min.apply(null, lons), lonMax = Math.max.apply(null, lons);
            var latMin = Math.min.apply(null, lats), latMax = Math.max.apply(null, lats);
            var spanX = (lonMax - lonMin) * proj.lonK;
            var spanY = latMax - latMin;
            var pad = 22;
            proj.scale = Math.min((vw - pad * 2) / spanX, (vh - pad * 2) / spanY);
            proj.ox = (vw - spanX * proj.scale) / 2 - lonMin * proj.lonK * proj.scale;
            proj.oy = (vh - spanY * proj.scale) / 2 + latMax * proj.scale;
        }

        function px(lon) { return lon * proj.lonK * proj.scale + proj.ox; }
        function py(lat) { return proj.oy - lat * proj.scale; }

        function placeSites() {
            for (var i = 0; i < sites.length; i++) {
                sites[i].x = px(sites[i].lon);
                sites[i].y = py(sites[i].lat);
            }
            sweepCx = px(35.93);   /* sweep radiates from Amman */
            sweepCy = py(31.95);
            sweepR = Math.sqrt(vw * vw + vh * vh);
        }

        function resize() {
            var rect = wrap.getBoundingClientRect();
            vw = Math.max(200, rect.width);
            vh = Math.max(200, rect.height);
            ctx = fitCanvas(canvas, vw, vh);
            fitProjection();
            placeSites();
            if (REDUCE_MOTION) frame(performance.now(), true);
        }

        function outlinePath() {
            ctx.beginPath();
            for (var i = 0; i < JORDAN_OUTLINE.length; i++) {
                var x = px(JORDAN_OUTLINE[i][0]);
                var y = py(JORDAN_OUTLINE[i][1]);
                if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
            }
            ctx.closePath();
        }

        function frame(now, single) {
            var dt = Math.min(0.05, (now - last) / 1000);
            last = now;
            var t = now / 1000;
            ctx.clearRect(0, 0, vw, vh);

            /* Country fill + glowing border */
            outlinePath();
            var fill = ctx.createLinearGradient(0, 0, 0, vh);
            fill.addColorStop(0, 'rgba(37, 99, 235, 0.10)');
            fill.addColorStop(1, 'rgba(14, 42, 92, 0.14)');
            ctx.fillStyle = fill;
            ctx.fill();
            outlinePath();
            ctx.strokeStyle = 'rgba(125, 211, 252, 0.55)';
            ctx.lineWidth = 1.5;
            ctx.stroke();
            outlinePath();
            ctx.strokeStyle = 'rgba(56, 189, 248, 0.12)';
            ctx.lineWidth = 5;
            ctx.stroke();

            /* Sweep radiating from Amman, clipped to the country shape */
            if (!REDUCE_MOTION && !single) {
                sweep = normalizeAngle(sweep + dt * (TAU / 9));
            }
            ctx.save();
            outlinePath();
            ctx.clip();
            drawSweep(ctx, sweepCx, sweepCy, sweepR, sweep, '#38bdf8', 0.07);
            ctx.restore();

            /* City reference marks */
            ctx.font = '600 9px Consolas, Menlo, monospace';
            for (var c = 0; c < JORDAN_CITIES.length; c++) {
                var city = JORDAN_CITIES[c];
                var cxp = px(city.lon), cyp = py(city.lat);
                ctx.beginPath();
                ctx.moveTo(cxp - 5, cyp); ctx.lineTo(cxp + 5, cyp);
                ctx.moveTo(cxp, cyp - 5); ctx.lineTo(cxp, cyp + 5);
                ctx.strokeStyle = 'rgba(147, 197, 253, 0.5)';
                ctx.lineWidth = 1;
                ctx.stroke();
                ctx.fillStyle = 'rgba(147, 197, 253, 0.55)';
                ctx.fillText(city.name, cxp + 8, cyp + 3);
            }

            /* Site dots */
            hoverSite = null;
            var bestDist = 13 * 13;
            for (var i = 0; i < sites.length; i++) {
                var s = sites[i];
                if (!REDUCE_MOTION) {
                    var ang = Math.atan2(s.y - sweepCy, s.x - sweepCx);
                    if (normalizeAngle(sweep - ang) < 0.05) s.glow = 1;
                    s.glow *= Math.exp(-dt * 1.1);
                } else {
                    s.glow = 0.4;
                }
                var mdx = mouse.x - s.x, mdy = mouse.y - s.y;
                var md2 = mdx * mdx + mdy * mdy;
                if (md2 < bestDist) { bestDist = md2; hoverSite = s; }

                var alpha = 0.4 + 0.2 * Math.sin(t * 1.5 + s.tw) + s.glow * 0.5;
                ctx.beginPath();
                ctx.arc(s.x, s.y, 1.8 + s.glow * 1.6, 0, TAU);
                ctx.fillStyle = rgba('#7dd3fc', Math.min(1, alpha));
                ctx.fill();
                if (s.glow > 0.35) {
                    ctx.beginPath();
                    ctx.arc(s.x, s.y, 3.5 + 5 * s.glow, 0, TAU);
                    ctx.strokeStyle = rgba('#38bdf8', 0.3 * s.glow);
                    ctx.lineWidth = 1;
                    ctx.stroke();
                }
            }

            /* Hover halo + tooltip */
            if (hoverSite) {
                ctx.beginPath();
                ctx.arc(hoverSite.x, hoverSite.y, 7, 0, TAU);
                ctx.strokeStyle = 'rgba(125, 211, 252, 0.9)';
                ctx.lineWidth = 1.4;
                ctx.stroke();
            }
            canvas.style.cursor = hoverSite ? 'pointer' : 'default';
            updateTooltip();

            if (!REDUCE_MOTION && !single) requestAnimationFrame(frame);
        }

        function updateTooltip() {
            if (!tooltipEl) return;
            if (!hoverSite) {
                tooltipEl.hidden = true;
                return;
            }
            var name = hoverSite.name && hoverSite.name !== hoverSite.id ? ' <small>' + hoverSite.name + '</small>' : '';
            tooltipEl.innerHTML =
                '<div class="radar-tip-title"><span class="radar-tip-dot" style="background:#7dd3fc"></span>' +
                hoverSite.id + name + '</div>' +
                (hoverSite.area ? '<div class="radar-tip-row"><span>Area</span><strong>' + hoverSite.area + '</strong></div>' : '') +
                '<div class="radar-tip-row"><span>Lat / Lon</span><strong>' +
                Number(hoverSite.lat).toFixed(3) + ', ' + Number(hoverSite.lon).toFixed(3) + '</strong></div>';
            tooltipEl.hidden = false;
            var pad2 = 12;
            var x = hoverSite.x + pad2, y = hoverSite.y + pad2;
            if (x + tooltipEl.offsetWidth > vw - 6) x = hoverSite.x - tooltipEl.offsetWidth - pad2;
            if (y + tooltipEl.offsetHeight > vh - 6) y = hoverSite.y - tooltipEl.offsetHeight - pad2;
            tooltipEl.style.left = Math.max(4, x) + 'px';
            tooltipEl.style.top = Math.max(4, y) + 'px';
        }

        canvas.addEventListener('mousemove', function (e) {
            var rect = canvas.getBoundingClientRect();
            mouse.x = e.clientX - rect.left;
            mouse.y = e.clientY - rect.top;
            if (REDUCE_MOTION) frame(performance.now(), true);
        });
        canvas.addEventListener('mouseleave', function () {
            mouse.x = -1e4; mouse.y = -1e4;
            if (tooltipEl) tooltipEl.hidden = true;
        });
        window.addEventListener('resize', resize);

        resize();
        if (REDUCE_MOTION) {
            frame(performance.now(), true);
        } else {
            requestAnimationFrame(frame);
        }

        return {
            update: function (list) {
                var rand = mulberry32(0x10CA7E);
                sites = (Array.isArray(list) ? list : []).map(function (row) {
                    return {
                        id: String(row.id != null ? row.id : ''),
                        name: String(row.name || ''),
                        area: String(row.area || ''),
                        lat: Number(row.lat),
                        lon: Number(row.lon),
                        x: 0, y: 0, tw: rand() * TAU, glow: 0
                    };
                }).filter(function (s) { return isFinite(s.lat) && isFinite(s.lon); });
                placeSites();
                if (REDUCE_MOTION) frame(performance.now(), true);
            }
        };
    }

    window.PrimeNetConstellation = {
        initPageBackground: initPageBackground,
        initLoginScene: initLoginScene,
        initRadar: initRadar,
        initJordanMap: initJordanMap,
        initAmbientBackground: initAmbientBackground,
        TECH_COLORS: TECH_COLORS
    };
})();
