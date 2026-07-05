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
     * LOGIN SCENE — full-screen constellation field + radar sweep
     * ==================================================================== */
    function initLoginScene(canvas) {
        var ctx = canvas.getContext('2d');
        var vw = 0, vh = 0;
        var cx = 0, cy = 0, R = 0;
        var nodes = [];
        var ripples = [];
        var mouse = { x: -1e4, y: -1e4, down: false };
        var sweep = -Math.PI / 2;
        var last = performance.now();
        var tintPool = ['#7dd3fc', '#7dd3fc', '#7dd3fc', '#38bdf8', TECH_COLORS['5G'], TECH_COLORS['4G-FDD'], TECH_COLORS['2G'], TECH_COLORS['4G-TDD']];

        function resize() {
            vw = window.innerWidth;
            vh = window.innerHeight;
            ctx = fitCanvas(canvas, vw, vh);
            cx = vw > 980 ? vw * 0.33 : vw * 0.5;
            cy = vh * 0.52;
            R = Math.min(vw, vh) * 0.46;
            buildNodes();
        }

        function buildNodes() {
            var count = Math.min(170, Math.max(60, Math.round((vw * vh) / 13500)));
            var rand = mulberry32(20260705);
            nodes = [];
            for (var i = 0; i < count; i++) {
                nodes.push({
                    x: rand() * vw,
                    y: rand() * vh,
                    vx: (rand() - 0.5) * 14,
                    vy: (rand() - 0.5) * 14,
                    r: 0.8 + rand() * 1.7,
                    tw: rand() * TAU,
                    glow: 0,
                    tint: tintPool[Math.floor(rand() * tintPool.length)]
                });
            }
        }

        function frame(now) {
            var dt = Math.min(0.05, (now - last) / 1000);
            last = now;
            var t = now / 1000;
            ctx.clearRect(0, 0, vw, vh);

            /* Radar grid + sweep behind the node field */
            drawRadarGrid(ctx, cx, cy, R, [R * 0.25, R * 0.5, R * 0.75, R], '#60a5fa');
            if (!REDUCE_MOTION) {
                sweep = normalizeAngle(sweep + dt * (TAU / 7));
                drawSweep(ctx, cx, cy, R, sweep, '#38bdf8', 0.13);
            }
            /* Hub */
            ctx.beginPath();
            ctx.arc(cx, cy, 3.2, 0, TAU);
            ctx.fillStyle = 'rgba(125,211,252,0.9)';
            ctx.fill();

            var i, j, n, m, dx, dy, dist;
            for (i = 0; i < nodes.length; i++) {
                n = nodes[i];
                if (!REDUCE_MOTION) {
                    n.x += n.vx * dt;
                    n.y += n.vy * dt;
                    /* Gentle pull toward the cursor when nearby */
                    dx = mouse.x - n.x; dy = mouse.y - n.y;
                    dist = Math.sqrt(dx * dx + dy * dy);
                    if (dist < 150 && dist > 0.001) {
                        n.x += (dx / dist) * 9 * dt;
                        n.y += (dy / dist) * 9 * dt;
                    }
                    if (n.x < -12) n.x = vw + 12; else if (n.x > vw + 12) n.x = -12;
                    if (n.y < -12) n.y = vh + 12; else if (n.y > vh + 12) n.y = -12;
                    /* Ping nodes as the sweep passes over them */
                    dx = n.x - cx; dy = n.y - cy;
                    if (dx * dx + dy * dy < R * R) {
                        var diff = normalizeAngle(sweep - Math.atan2(dy, dx));
                        if (diff < 0.06) n.glow = 1;
                    }
                    n.glow *= Math.exp(-dt * 1.6);
                }
            }

            /* Node-to-node constellation links */
            for (i = 0; i < nodes.length; i++) {
                n = nodes[i];
                for (j = i + 1; j < nodes.length; j++) {
                    m = nodes[j];
                    dx = n.x - m.x; dy = n.y - m.y;
                    var d2 = dx * dx + dy * dy;
                    if (d2 < 110 * 110) {
                        var a = 0.10 * (1 - Math.sqrt(d2) / 110);
                        ctx.beginPath();
                        ctx.moveTo(n.x, n.y);
                        ctx.lineTo(m.x, m.y);
                        ctx.strokeStyle = 'rgba(125,211,252,' + a.toFixed(3) + ')';
                        ctx.lineWidth = 1;
                        ctx.stroke();
                    }
                }
                /* Links to the cursor */
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

            /* Nodes */
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

            /* Click ripples */
            for (i = ripples.length - 1; i >= 0; i--) {
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

            if (!REDUCE_MOTION) requestAnimationFrame(frame);
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
            frame(performance.now());
        } else {
            requestAnimationFrame(frame);
        }
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

    window.PrimeNetConstellation = {
        initLoginScene: initLoginScene,
        initRadar: initRadar,
        TECH_COLORS: TECH_COLORS
    };
})();
