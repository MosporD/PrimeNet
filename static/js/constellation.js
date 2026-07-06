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
    var LOGIN_SCENE_KEY = 'primenet-login-scene-idx';

    function pickLoginSceneIndex(count) {
        try {
            var n = parseInt(localStorage.getItem(LOGIN_SCENE_KEY) || '0', 10);
            if (!isFinite(n)) n = 0;
            var idx = ((n % count) + count) % count;
            localStorage.setItem(LOGIN_SCENE_KEY, String(n + 1));
            return idx;
        } catch (_) {
            return Math.floor(Math.random() * count);
        }
    }

    function initLoginScene(canvas) {
        var ctx = canvas.getContext('2d');
        var vw = 0, vh = 0, cx = 0, cy = 0, R = 0;
        var mouse = { x: -1e4, y: -1e4 };
        var ripples = [];
        var last = performance.now();

        /* ---------- scene: RADAR SWEEP (constellation + rotating sweep) -- */
        var radar = {
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
            draw: function (dt, t) {
                drawRadarGrid(ctx, cx, cy, R, [R * 0.25, R * 0.5, R * 0.75, R], '#60a5fa');
                if (!REDUCE_MOTION) {
                    this.sweep = normalizeAngle(this.sweep + dt * (TAU / 7));
                    drawSweep(ctx, cx, cy, R, this.sweep, '#38bdf8', 0.13);
                }
                ctx.beginPath();
                ctx.arc(cx, cy, 3.2, 0, TAU);
                ctx.fillStyle = 'rgba(125,211,252,0.9)';
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
            draw: function (dt, t) {
                var green = '#34d399';
                var teal = '#2dd4bf';
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
            draw: function (dt, t) {
                var offX = (mouse.x > -1e3 ? (mouse.x - vw / 2) : 0) * 0.012;
                var offY = (mouse.y > -1e3 ? (mouse.y - vh / 2) : 0) * 0.012;

                for (var i = 0; i < this.field.length; i++) {
                    var st = this.field[i];
                    var alpha = 0.25 + 0.35 * (0.5 + 0.5 * Math.sin(t * 1.6 + st.tw)) * st.z;
                    ctx.beginPath();
                    ctx.arc(st.x - offX * st.z * 10, st.y - offY * st.z * 10, st.r, 0, TAU);
                    ctx.fillStyle = 'rgba(226,238,255,' + alpha.toFixed(3) + ')';
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
                    ctx.strokeStyle = 'rgba(196,181,253,0.22)';
                    ctx.lineWidth = 1;
                    ctx.stroke();
                    for (p = 0; p < pts.length; p++) {
                        var vx = pts[p].x - offX * 8, vy = pts[p].y - offY * 8;
                        var va = 0.55 + 0.35 * Math.sin(t * 1.2 + pts[p].tw);
                        ctx.beginPath();
                        ctx.arc(vx, vy, 2.1, 0, TAU);
                        ctx.fillStyle = 'rgba(221,214,254,' + va.toFixed(3) + ')';
                        ctx.fill();
                        /* link bright vertices to a nearby cursor */
                        var dx = vx - mouse.x, dy = vy - mouse.y;
                        var dist = Math.sqrt(dx * dx + dy * dy);
                        if (dist < 190) {
                            ctx.beginPath();
                            ctx.moveTo(vx, vy);
                            ctx.lineTo(mouse.x, mouse.y);
                            ctx.strokeStyle = 'rgba(196,181,253,' + (0.28 * (1 - dist / 190)).toFixed(3) + ')';
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
            draw: function (dt, t) {
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
        var current = pickLoginSceneIndex(scenes.length);

        function drawScene(scene, dt, t) {
            ctx.save();
            /* per-scene mood tint */
            var tint = ctx.createRadialGradient(cx, cy, 0, cx, cy, Math.max(vw, vh) * 0.8);
            tint.addColorStop(0, scene.tint);
            tint.addColorStop(1, 'rgba(0,0,0,0)');
            ctx.fillStyle = tint;
            ctx.fillRect(0, 0, vw, vh);
            scene.draw(dt, t);
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

            /* click ripples on top of any scene */
            for (var i = ripples.length - 1; i >= 0; i--) {
                var rp = ripples[i];
                rp.r += dt * 160;
                rp.a -= dt * 1.1;
                if (rp.a <= 0) { ripples.splice(i, 1); continue; }
                ctx.beginPath();
                ctx.arc(rp.x, rp.y, rp.r, 0, TAU);
                ctx.strokeStyle = 'rgba(56,189,248,' + rp.a.toFixed(3) + ')';
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

        resize();
        if (REDUCE_MOTION) {
            frame(performance.now(), true);
        } else {
            requestAnimationFrame(frame);
        }

        return {
            names: scenes.map(function (s) { return s.name; }),
            getScene: function () { return current; }
        };
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
     * AMBIENT BACKGROUND — theme-aware constellation behind page content
     * (used as the dashboard's full-page background)
     * ==================================================================== */
    var AMBIENT_THEMES = {
        light: {
            bgTop: '#e8f0fa', bgBottom: '#f2f6fb',
            tint: 'rgba(59, 130, 246, 0.10)',
            node: '#1d4ed8', nodeAlpha: 0.55,
            hub: '#2563eb', hubAlpha: 0.6,
            link: [29, 78, 216], linkAlpha: 0.22,
            mouseLink: [14, 116, 233], mouseAlpha: 0.30,
            pulse: '#0284c7', pulseAlpha: 0.75
        },
        dark: {
            bgTop: '#0a1326', bgBottom: '#101a2e',
            tint: 'rgba(56, 189, 248, 0.10)',
            node: '#7dd3fc', nodeAlpha: 0.85,
            hub: '#38bdf8', hubAlpha: 0.9,
            link: [125, 211, 252], linkAlpha: 0.20,
            mouseLink: [56, 189, 248], mouseAlpha: 0.32,
            pulse: '#38bdf8', pulseAlpha: 0.9
        }
    };

    function initAmbientBackground(canvas) {
        var ctx = canvas.getContext('2d');
        var vw = 0, vh = 0;
        var nodes = [];
        var packets = [];
        var mouse = { x: -1e4, y: -1e4 };
        var last = performance.now();
        var packetTimer = 0;
        var LINK_DIST = 150;
        /* 0..1 network activity — paces the data-packet pulses (0.5 = neutral). */
        var activityLevel = 0.5;

        function theme() {
            return AMBIENT_THEMES[document.body.classList.contains('dark-mode') ? 'dark' : 'light'];
        }

        function resize() {
            vw = window.innerWidth;
            vh = Math.max(window.innerHeight, document.documentElement.clientHeight);
            ctx = fitCanvas(canvas, vw, vh);
            buildNodes();
            if (REDUCE_MOTION) frame(performance.now(), true);
        }

        function buildNodes() {
            var count = Math.min(150, Math.max(55, Math.round((vw * vh) / 14500)));
            var rand = mulberry32(0xC0FFEE);
            nodes = [];
            for (var i = 0; i < count; i++) {
                nodes.push({
                    x: rand() * vw,
                    y: rand() * vh,
                    vx: (rand() - 0.5) * 10,
                    vy: (rand() - 0.5) * 10,
                    r: 1.1 + rand() * 1.9,
                    tw: rand() * TAU,
                    /* every ~9th node is a glowing "hub" site */
                    hub: rand() < 0.11
                });
            }
            packets = [];
        }

        function spawnPacket() {
            /* Send a "data packet" pulse along a random existing link. */
            var tries = 12;
            while (tries-- > 0) {
                var a = nodes[(Math.random() * nodes.length) | 0];
                var b = nodes[(Math.random() * nodes.length) | 0];
                if (!a || !b || a === b) continue;
                var dx = b.x - a.x, dy = b.y - a.y;
                if (dx * dx + dy * dy < LINK_DIST * LINK_DIST) {
                    packets.push({ a: a, b: b, t: 0, speed: 0.9 + Math.random() * 0.8 });
                    return;
                }
            }
        }

        function frame(now, single) {
            var dt = Math.min(0.05, (now - last) / 1000);
            last = now;
            var t = now / 1000;
            var th = theme();

            /* Background wash */
            var bg = ctx.createLinearGradient(0, 0, 0, vh);
            bg.addColorStop(0, th.bgTop);
            bg.addColorStop(1, th.bgBottom);
            ctx.fillStyle = bg;
            ctx.fillRect(0, 0, vw, vh);
            var tint = ctx.createRadialGradient(vw * 0.2, vh * 0.1, 0, vw * 0.2, vh * 0.1, Math.max(vw, vh) * 0.7);
            tint.addColorStop(0, th.tint);
            tint.addColorStop(1, 'rgba(0,0,0,0)');
            ctx.fillStyle = tint;
            ctx.fillRect(0, 0, vw, vh);

            var i, j, n, m, dx, dy, dist;
            for (i = 0; i < nodes.length; i++) {
                n = nodes[i];
                if (!REDUCE_MOTION && !single) {
                    n.x += n.vx * dt;
                    n.y += n.vy * dt;
                    if (n.x < -12) n.x = vw + 12; else if (n.x > vw + 12) n.x = -12;
                    if (n.y < -12) n.y = vh + 12; else if (n.y > vh + 12) n.y = -12;
                }
            }

            /* Links */
            for (i = 0; i < nodes.length; i++) {
                n = nodes[i];
                for (j = i + 1; j < nodes.length; j++) {
                    m = nodes[j];
                    dx = n.x - m.x; dy = n.y - m.y;
                    var d2 = dx * dx + dy * dy;
                    if (d2 < LINK_DIST * LINK_DIST) {
                        var a = th.linkAlpha * (1 - Math.sqrt(d2) / LINK_DIST);
                        ctx.beginPath();
                        ctx.moveTo(n.x, n.y);
                        ctx.lineTo(m.x, m.y);
                        ctx.strokeStyle = 'rgba(' + th.link[0] + ',' + th.link[1] + ',' + th.link[2] + ',' + a.toFixed(3) + ')';
                        ctx.lineWidth = 1;
                        ctx.stroke();
                    }
                }
                dx = n.x - mouse.x; dy = n.y - mouse.y;
                dist = Math.sqrt(dx * dx + dy * dy);
                if (dist < 180) {
                    ctx.beginPath();
                    ctx.moveTo(n.x, n.y);
                    ctx.lineTo(mouse.x, mouse.y);
                    ctx.strokeStyle = 'rgba(' + th.mouseLink[0] + ',' + th.mouseLink[1] + ',' + th.mouseLink[2] + ',' + (th.mouseAlpha * (1 - dist / 180)).toFixed(3) + ')';
                    ctx.lineWidth = 1;
                    ctx.stroke();
                }
            }

            /* Nodes */
            for (i = 0; i < nodes.length; i++) {
                n = nodes[i];
                var alpha = th.nodeAlpha * (0.65 + 0.35 * Math.sin(t * 1.2 + n.tw));
                if (n.hub) {
                    /* Glow halo around hub nodes */
                    var halo = ctx.createRadialGradient(n.x, n.y, 0, n.x, n.y, n.r * 7);
                    halo.addColorStop(0, rgba(th.hub, 0.35 * th.hubAlpha));
                    halo.addColorStop(1, 'rgba(0,0,0,0)');
                    ctx.fillStyle = halo;
                    ctx.beginPath();
                    ctx.arc(n.x, n.y, n.r * 7, 0, TAU);
                    ctx.fill();
                    ctx.beginPath();
                    ctx.arc(n.x, n.y, n.r + 1.2, 0, TAU);
                    ctx.fillStyle = rgba(th.hub, Math.min(1, th.hubAlpha * (0.7 + 0.3 * Math.sin(t * 1.6 + n.tw))));
                    ctx.fill();
                } else {
                    ctx.beginPath();
                    ctx.arc(n.x, n.y, n.r, 0, TAU);
                    ctx.fillStyle = rgba(th.node, Math.max(0.05, alpha));
                    ctx.fill();
                }
            }

            /* Data packets travelling along links — rate follows network activity */
            if (!REDUCE_MOTION && !single) {
                var maxPackets = 2 + Math.round(activityLevel * 9);
                packetTimer -= dt;
                if (packetTimer <= 0 && packets.length < maxPackets) {
                    spawnPacket();
                    packetTimer = (0.35 + Math.random() * 0.8) * (1.7 - 1.25 * activityLevel);
                }
                for (i = packets.length - 1; i >= 0; i--) {
                    var p = packets[i];
                    p.t += dt * p.speed;
                    if (p.t >= 1) { packets.splice(i, 1); continue; }
                    var px = p.a.x + (p.b.x - p.a.x) * p.t;
                    var py = p.a.y + (p.b.y - p.a.y) * p.t;
                    var fade = Math.sin(p.t * Math.PI);
                    ctx.beginPath();
                    ctx.arc(px, py, 2.1, 0, TAU);
                    ctx.fillStyle = rgba(th.pulse, th.pulseAlpha * fade);
                    ctx.fill();
                    ctx.beginPath();
                    ctx.arc(px, py, 4.6, 0, TAU);
                    ctx.strokeStyle = rgba(th.pulse, 0.3 * th.pulseAlpha * fade);
                    ctx.lineWidth = 1;
                    ctx.stroke();
                }
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
        /* Re-render once on theme toggles when animation is disabled. */
        document.addEventListener('primenet:theme-change', function () {
            if (REDUCE_MOTION) frame(performance.now(), true);
        });

        resize();
        if (!REDUCE_MOTION) requestAnimationFrame(frame);

        return {
            setActivity: function (level) {
                var v = Number(level);
                if (isFinite(v)) activityLevel = Math.max(0, Math.min(1, v));
            }
        };
    }

    window.PrimeNetConstellation = {
        initLoginScene: initLoginScene,
        initRadar: initRadar,
        initAmbientBackground: initAmbientBackground,
        TECH_COLORS: TECH_COLORS
    };
})();
