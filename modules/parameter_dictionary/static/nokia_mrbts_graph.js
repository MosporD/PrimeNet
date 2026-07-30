/**
 * Nokia Single RAN MRBTS — radial zoomable MO graph
 */

const MRBTSGraph = {
    tree: null,
    flat: [],
    meta: {},
    byId: new Map(),
    columns: [],
    focusId: 'MRBTS',
    selectedId: '',
    spreadChildren: false,
    loaded: false,
    paramCache: new Map(),
    animToken: 0,
    svg: null,
    gRoot: null,
    gLinks: null,
    gNodes: null,
    defsReady: false,
    width: 900,
    height: 600,
    view: { x: 0, y: 0, k: 1 },
    viewAnim: null,
    contentExtent: 300,
    tooltip: null,
};

const LEVEL_COLORS = {
    1: '#6366f1',
    2: '#3b82f6',
    3: '#06b6d4',
    4: '#14b8a6',
    5: '#10b981',
    6: '#f59e0b',
    7: '#f97316',
    8: '#f43f5e',
};

const SVG_NS = 'http://www.w3.org/2000/svg';

function graphParentId(id) {
    const parts = (id || '').split('/');
    if (parts.length <= 1) return null;
    return parts.slice(0, -1).join('/');
}

function graphEscapeHtml(value) {
    return String(value || '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#039;');
}

function graphTruncate(text, max) {
    const value = String(text || '');
    if (value.length <= max) return value;
    return value.slice(0, max - 1) + '…';
}

function graphShade(hex, pct) {
    const n = parseInt(hex.slice(1), 16);
    let r = (n >> 16) & 255;
    let g = (n >> 8) & 255;
    let b = n & 255;
    if (pct >= 0) {
        r += (255 - r) * pct;
        g += (255 - g) * pct;
        b += (255 - b) * pct;
    } else {
        r *= 1 + pct;
        g *= 1 + pct;
        b *= 1 + pct;
    }
    return `rgb(${Math.round(r)}, ${Math.round(g)}, ${Math.round(b)})`;
}

function graphLevelColor(level) {
    return LEVEL_COLORS[level] || '#64748b';
}

function indexGraphTree(node) {
    if (!node || !node.id) return;
    MRBTSGraph.byId.set(node.id, node);
    (node.children || []).forEach(indexGraphTree);
}

function svgEl(tag, attrs = {}) {
    const el = document.createElementNS(SVG_NS, tag);
    Object.entries(attrs).forEach(([key, value]) => el.setAttribute(key, String(value)));
    return el;
}

/* ── Layout ─────────────────────────────────────────────────────────── */

function graphLayout(focusNode) {
    const { width, height } = MRBTSGraph;
    const cx = width / 2;
    const cy = height / 2;
    const children = MRBTSGraph.spreadChildren ? (focusNode.children || []) : [];
    const count = children.length;

    const focusRadius = count > 30 ? 52 : count > 12 ? 58 : 64;
    const childRadius = count > 60 ? 15 : count > 30 ? 17 : count > 16 ? 19 : 22;

    // Grow the orbit from the circumference each child needs, so nodes
    // never overlap no matter how many branches spread out.
    const arcPerChild = childRadius * 2 + 14;
    const orbitRadius = count === 0
        ? 0
        : Math.max(focusRadius + 120, (count * arcPerChild) / (2 * Math.PI));

    const nodes = [{
        node: focusNode,
        x: cx,
        y: cy,
        r: focusRadius,
        kind: 'focus',
        angle: 0,
    }];

    children.forEach((child, index) => {
        const angle = (Math.PI * 2 * index) / count - Math.PI / 2;
        nodes.push({
            node: child,
            x: cx + orbitRadius * Math.cos(angle),
            y: cy + orbitRadius * Math.sin(angle),
            r: childRadius,
            kind: 'child',
            angle,
        });
    });

    return { nodes, cx, cy, orbitRadius, focusRadius };
}

/* ── SVG scaffolding, defs, pan & zoom ──────────────────────────────── */

function graphBuildDefs(svg) {
    if (MRBTSGraph.defsReady) return;
    const defs = svgEl('defs');

    Object.entries(LEVEL_COLORS).forEach(([level, color]) => {
        const grad = svgEl('radialGradient', {
            id: `mrbts-grad-${level}`,
            cx: '32%',
            cy: '28%',
            r: '80%',
        });
        grad.appendChild(svgEl('stop', { offset: '0%', 'stop-color': graphShade(color, 0.38) }));
        grad.appendChild(svgEl('stop', { offset: '55%', 'stop-color': color }));
        grad.appendChild(svgEl('stop', { offset: '100%', 'stop-color': graphShade(color, -0.28) }));
        defs.appendChild(grad);
    });

    svg.appendChild(defs);
    MRBTSGraph.defsReady = true;
}

function graphApplyView() {
    const { x, y, k } = MRBTSGraph.view;
    if (MRBTSGraph.gRoot) {
        MRBTSGraph.gRoot.setAttribute('transform', `translate(${x} ${y}) scale(${k})`);
    }
}

function graphAnimateViewTo(target, duration = 320) {
    if (MRBTSGraph.viewAnim) cancelAnimationFrame(MRBTSGraph.viewAnim);
    const from = { ...MRBTSGraph.view };
    const start = performance.now();
    const ease = (t) => 1 - Math.pow(1 - t, 3);

    const step = (now) => {
        const t = Math.min(1, (now - start) / duration);
        const e = ease(t);
        MRBTSGraph.view = {
            x: from.x + (target.x - from.x) * e,
            y: from.y + (target.y - from.y) * e,
            k: from.k + (target.k - from.k) * e,
        };
        graphApplyView();
        if (t < 1) {
            MRBTSGraph.viewAnim = requestAnimationFrame(step);
        } else {
            MRBTSGraph.viewAnim = null;
        }
    };
    MRBTSGraph.viewAnim = requestAnimationFrame(step);
}

function graphFitView(animate = true) {
    const { width, height, contentExtent } = MRBTSGraph;
    const cx = width / 2;
    const cy = height / 2;
    const k = Math.min(1.15, Math.min(width, height) / (contentExtent * 2));
    const target = { x: cx - cx * k, y: cy - cy * k, k };
    if (animate) graphAnimateViewTo(target);
    else {
        MRBTSGraph.view = target;
        graphApplyView();
    }
}

function graphZoomBy(factor, sx, sy) {
    const { width, height } = MRBTSGraph;
    const px = sx === undefined ? width / 2 : sx;
    const py = sy === undefined ? height / 2 : sy;
    const { x, y, k } = MRBTSGraph.view;
    const k2 = Math.min(3, Math.max(0.25, k * factor));
    MRBTSGraph.view = {
        x: px - ((px - x) * k2) / k,
        y: py - ((py - y) * k2) / k,
        k: k2,
    };
    graphApplyView();
}

function graphBindStageInteractions(svg) {
    if (svg.dataset.panBound) return;
    svg.dataset.panBound = '1';

    svg.addEventListener('wheel', (event) => {
        event.preventDefault();
        const rect = svg.getBoundingClientRect();
        const local = typeof pointerLocalXY === 'function'
            ? pointerLocalXY(event, svg)
            : { x: event.clientX - rect.left, y: event.clientY - rect.top };
        const factor = Math.exp(-event.deltaY * 0.0016);
        graphZoomBy(factor, local.x, local.y);
    }, { passive: false });

    let pressed = false;
    let panning = false;
    let last = { x: 0, y: 0 };

    svg.addEventListener('pointerdown', (event) => {
        if (event.button !== 0) return;
        pressed = true;
        panning = false;
        last = { x: event.clientX, y: event.clientY };
    });
    svg.addEventListener('pointermove', (event) => {
        if (!pressed) return;
        const dx = event.clientX - last.x;
        const dy = event.clientY - last.y;
        // Capture the pointer only once a real drag starts, so plain
        // clicks still reach the node groups underneath.
        if (!panning) {
            if (Math.abs(dx) + Math.abs(dy) < 4) return;
            panning = true;
            svg.setPointerCapture(event.pointerId);
            svg.classList.add('grabbing');
        }
        last = { x: event.clientX, y: event.clientY };
        MRBTSGraph.view.x += dx;
        MRBTSGraph.view.y += dy;
        graphApplyView();
    });
    const endDrag = (event) => {
        if (!pressed) return;
        pressed = false;
        svg.classList.remove('grabbing');
        if (svg.hasPointerCapture?.(event.pointerId)) {
            svg.releasePointerCapture(event.pointerId);
        }
        // Swallow the click that follows a real drag so nodes don't fire.
        if (panning) {
            const stop = (e) => e.stopPropagation();
            svg.addEventListener('click', stop, { capture: true, once: true });
        }
        panning = false;
    };
    svg.addEventListener('pointerup', endDrag);
    svg.addEventListener('pointercancel', endDrag);

    svg.addEventListener('dblclick', (event) => {
        event.preventDefault();
        graphFitView();
    });
}

function graphEnsureSvg() {
    const host = document.getElementById('nokia-graph-stage');
    if (!host) return null;

    let svg = document.getElementById('mrbts-graph-svg');
    if (!svg) {
        svg = svgEl('svg', { role: 'img', 'aria-label': 'MRBTS managed object hierarchy graph' });
        svg.id = 'mrbts-graph-svg';
        svg.classList.add('nokia-graph-svg');
        host.appendChild(svg);
    }

    MRBTSGraph.svg = svg;
    MRBTSGraph.width = host.clientWidth || 900;
    MRBTSGraph.height = host.clientHeight || 600;
    svg.setAttribute('viewBox', `0 0 ${MRBTSGraph.width} ${MRBTSGraph.height}`);

    graphBuildDefs(svg);
    graphBindStageInteractions(svg);

    if (!MRBTSGraph.gRoot) {
        MRBTSGraph.gRoot = svgEl('g', { class: 'graph-root' });
        svg.appendChild(MRBTSGraph.gRoot);
    }
    if (!MRBTSGraph.gLinks) {
        MRBTSGraph.gLinks = svgEl('g', { class: 'graph-links' });
        MRBTSGraph.gRoot.appendChild(MRBTSGraph.gLinks);
    }
    if (!MRBTSGraph.gNodes) {
        MRBTSGraph.gNodes = svgEl('g', { class: 'graph-nodes' });
        MRBTSGraph.gRoot.appendChild(MRBTSGraph.gNodes);
    }

    if (!MRBTSGraph.tooltip) {
        const tip = document.createElement('div');
        tip.className = 'nokia-graph-tooltip';
        tip.hidden = true;
        host.appendChild(tip);
        MRBTSGraph.tooltip = tip;
    }

    return svg;
}

/* ── Tooltip ────────────────────────────────────────────────────────── */

function graphShowTooltip(item, event) {
    const tip = MRBTSGraph.tooltip;
    const host = document.getElementById('nokia-graph-stage');
    if (!tip || !host) return;
    const mo = item.node;
    const childCount = (mo.children || []).length;
    tip.innerHTML = `
        <div class="nokia-graph-tooltip-name">${graphEscapeHtml(mo.name)}</div>
        ${mo.meaning ? `<div class="nokia-graph-tooltip-meaning">${graphEscapeHtml(graphTruncate(mo.meaning, 90))}</div>` : ''}
        <div class="nokia-graph-tooltip-meta">Level ${mo.level}${childCount ? ` · ${childCount} child MO${childCount !== 1 ? 's' : ''}` : ' · leaf'}</div>
    `;
    tip.hidden = false;
    const rect = host.getBoundingClientRect();
    let x = event.clientX - rect.left + 14;
    let y = event.clientY - rect.top + 14;
    const maxX = rect.width - tip.offsetWidth - 10;
    const maxY = rect.height - tip.offsetHeight - 10;
    tip.style.left = `${Math.min(x, maxX)}px`;
    tip.style.top = `${Math.min(y, maxY)}px`;
}

function graphHideTooltip() {
    if (MRBTSGraph.tooltip) MRBTSGraph.tooltip.hidden = true;
}

/* ── Rendering ──────────────────────────────────────────────────────── */

function graphRender() {
    const focusNode = MRBTSGraph.byId.get(MRBTSGraph.focusId);
    if (!focusNode || !graphEnsureSvg()) return;

    const layout = graphLayout(focusNode);
    const focusPoint = layout.nodes[0];
    MRBTSGraph.animToken += 1;
    MRBTSGraph.contentExtent = layout.orbitRadius
        ? layout.orbitRadius + 130
        : layout.focusRadius + 110;

    MRBTSGraph.gLinks.innerHTML = '';
    MRBTSGraph.gNodes.innerHTML = '';
    graphHideTooltip();

    const totalChildren = layout.nodes.length - 1;

    layout.nodes.forEach((item, order) => {
        const delay = item.kind === 'focus'
            ? 0
            : Math.min(240, (order - 1) * (totalChildren > 40 ? 3 : 8));

        if (item.kind !== 'focus') {
            const line = svgEl('line', {
                class: 'graph-link',
                x1: focusPoint.x,
                y1: focusPoint.y,
                x2: item.x,
                y2: item.y,
                stroke: graphLevelColor(item.node.level),
            });
            const len = Math.hypot(item.x - focusPoint.x, item.y - focusPoint.y);
            line.style.strokeDasharray = String(len);
            line.style.strokeDashoffset = String(len);
            line.style.transition = `stroke-dashoffset 0.4s ease ${delay}ms, opacity 0.2s ease`;
            MRBTSGraph.gLinks.appendChild(line);
            requestAnimationFrame(() => {
                line.style.strokeDashoffset = '0';
            });
        }

        MRBTSGraph.gNodes.appendChild(graphBuildNode(item, focusPoint, delay));
    });

    graphUpdateToolbar();
    graphUpdateCrumbs();
    graphFitView(true);
}

function graphBuildNode(item, focusPoint, delay) {
    const mo = item.node;
    const color = graphLevelColor(mo.level);
    const childCount = (mo.children || []).length;
    const isFocus = item.kind === 'focus';

    const group = svgEl('g', {
        class: 'graph-node-group'
            + (isFocus ? ' focus' : '')
            + (childCount ? ' has-children' : ' is-leaf')
            + (mo.id === MRBTSGraph.selectedId ? ' selected' : ''),
    });
    group.dataset.id = mo.id;

    // Everything inside the group uses local coordinates around (0,0);
    // the group transform places (and animates) the node.
    if (isFocus) {
        const halo = svgEl('circle', {
            class: 'graph-focus-halo',
            cx: 0, cy: 0, r: item.r + 16,
            fill: color,
        });
        const ring = svgEl('circle', {
            class: 'graph-focus-ring',
            cx: 0, cy: 0, r: item.r + 8,
            stroke: color,
        });
        group.appendChild(halo);
        group.appendChild(ring);
    }

    const circle = svgEl('circle', {
        class: 'graph-node-circle',
        cx: 0, cy: 0, r: item.r,
        fill: `url(#mrbts-grad-${mo.level})`,
        stroke: graphShade(color, -0.35),
    });
    group.appendChild(circle);

    if (isFocus) {
        const name = svgEl('text', { class: 'graph-focus-name', x: 0, y: childCount ? -2 : 4 });
        name.textContent = graphTruncate(mo.name, 14);
        group.appendChild(name);

        if (childCount) {
            const sub = svgEl('text', { class: 'graph-focus-sub', x: 0, y: 16 });
            sub.textContent = MRBTSGraph.spreadChildren
                ? `${childCount} branch${childCount !== 1 ? 'es' : ''}`
                : 'click to expand';
            group.appendChild(sub);
        }
    } else {
        if (childCount) {
            const count = svgEl('text', { class: 'graph-node-count', x: 0, y: 3.5 });
            count.textContent = childCount > 99 ? '99+' : String(childCount);
            group.appendChild(count);
        }

        // Radial label: runs along the spoke, flipped upright on the left half.
        const deg = (item.angle * 180) / Math.PI;
        const flip = deg > 90 || deg < -90;
        const dist = item.r + 8;
        const lx = dist * Math.cos(item.angle);
        const ly = dist * Math.sin(item.angle);
        const label = svgEl('text', {
            class: 'graph-node-label',
            x: lx,
            y: ly,
            'text-anchor': flip ? 'end' : 'start',
            transform: `rotate(${flip ? deg + 180 : deg} ${lx} ${ly})`,
        });
        label.setAttribute('dy', '0.35em');
        label.textContent = mo.name;
        group.appendChild(label);
    }

    group.addEventListener('click', (event) => {
        event.stopPropagation();
        graphHideTooltip();
        graphOnNodeClick(mo, item.kind);
    });
    group.addEventListener('pointermove', (event) => {
        if (!isFocus) graphShowTooltip(item, event);
    });
    group.addEventListener('pointerleave', graphHideTooltip);

    // Fly out from the focus point with a soft spring. SVG attribute
    // transforms don't animate via CSS transitions, so tween manually.
    const startScale = isFocus ? 0.7 : 0.2;
    group.setAttribute('transform', `translate(${focusPoint.x} ${focusPoint.y}) scale(${startScale})`);
    group.style.opacity = '0';
    group.style.transition = `opacity 0.25s ease ${delay}ms`;
    requestAnimationFrame(() => {
        group.style.opacity = '1';
    });
    graphTweenNode(group, focusPoint, item, delay, startScale);

    return group;
}

function graphTweenNode(group, from, to, delay, startScale) {
    const token = MRBTSGraph.animToken;
    const duration = 380;
    const start = performance.now() + delay;
    const ease = (t) => 1 - Math.pow(1 - t, 3);

    const step = (now) => {
        if (token !== MRBTSGraph.animToken || !group.isConnected) return;
        const t = Math.min(1, Math.max(0, (now - start) / duration));
        const e = ease(t);
        const x = from.x + (to.x - from.x) * e;
        const y = from.y + (to.y - from.y) * e;
        const s = startScale + (1 - startScale) * e;
        group.setAttribute('transform', `translate(${x} ${y}) scale(${s})`);
        if (t < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
}

/* ── Interaction ────────────────────────────────────────────────────── */

function graphOnNodeClick(node, kind) {
    MRBTSGraph.selectedId = node.id;
    graphShowNodePanel(node);

    if (kind === 'focus') {
        if (!MRBTSGraph.spreadChildren && (node.children || []).length > 0) {
            MRBTSGraph.spreadChildren = true;
            graphRender();
            return;
        }
        graphUpdateSelection();
        return;
    }

    if ((node.children || []).length > 0) {
        MRBTSGraph.focusId = node.id;
        MRBTSGraph.spreadChildren = true;
        graphRender();
        return;
    }

    graphUpdateSelection();
}

function graphUpdateSelection() {
    if (!MRBTSGraph.gNodes) return;
    MRBTSGraph.gNodes.querySelectorAll('.graph-node-group').forEach((group) => {
        group.classList.toggle('selected', group.dataset.id === MRBTSGraph.selectedId);
    });
}

function graphFocusNode(id, selectId) {
    if (!MRBTSGraph.byId.has(id)) return;
    MRBTSGraph.focusId = id;
    MRBTSGraph.selectedId = selectId || id;
    MRBTSGraph.spreadChildren = id !== (MRBTSGraph.tree?.id || 'MRBTS');
    graphRender();
    graphShowNodePanel(MRBTSGraph.byId.get(MRBTSGraph.selectedId));
}

function graphZoomOut() {
    const parentId = graphParentId(MRBTSGraph.focusId);
    if (!parentId) return;
    MRBTSGraph.focusId = parentId;
    MRBTSGraph.selectedId = parentId;
    MRBTSGraph.spreadChildren = true;
    graphRender();
    graphShowNodePanel(MRBTSGraph.byId.get(parentId));
}

function graphResetView() {
    MRBTSGraph.focusId = MRBTSGraph.tree?.id || 'MRBTS';
    MRBTSGraph.selectedId = MRBTSGraph.focusId;
    MRBTSGraph.spreadChildren = false;
    graphRender();
    graphShowNodePanel(MRBTSGraph.tree);
}

function graphUpdateToolbar() {
    const upBtn = document.getElementById('nokia-graph-zoom-out');
    const resetBtn = document.getElementById('nokia-graph-reset');
    const parentId = graphParentId(MRBTSGraph.focusId);
    if (upBtn) upBtn.disabled = !parentId;
    if (resetBtn) resetBtn.disabled = MRBTSGraph.focusId === (MRBTSGraph.tree?.id || 'MRBTS');
}

function graphUpdateCrumbs() {
    const host = document.getElementById('nokia-graph-crumbs');
    if (!host) return;

    const focusNode = MRBTSGraph.byId.get(MRBTSGraph.focusId);
    if (!focusNode) {
        host.innerHTML = '';
        return;
    }

    host.innerHTML = '';
    (focusNode.path || []).forEach((part, index) => {
        if (index > 0) {
            const sep = document.createElement('span');
            sep.className = 'nokia-graph-crumb-sep';
            sep.textContent = '/';
            host.appendChild(sep);
        }
        const id = focusNode.path.slice(0, index + 1).join('/');
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'nokia-graph-crumb' + (id === MRBTSGraph.focusId ? ' current' : '');
        btn.textContent = part;
        if (id !== MRBTSGraph.focusId) {
            btn.addEventListener('click', () => graphFocusNode(id, id));
        }
        host.appendChild(btn);
    });
}

/* ── Search ─────────────────────────────────────────────────────────── */

function graphJumpTo(id) {
    const node = MRBTSGraph.byId.get(id);
    if (!node) return;
    const hasChildren = (node.children || []).length > 0;
    const target = hasChildren ? id : (graphParentId(id) || id);
    graphFocusNode(target, id);
}

function graphRenderSearchResults(term) {
    const host = document.getElementById('nokia-graph-search-results');
    if (!host) return;

    const query = term.trim().toLowerCase();
    if (query.length < 2) {
        host.hidden = true;
        host.innerHTML = '';
        return;
    }

    const words = query.split(/\s+/).filter(Boolean);
    const matches = [];
    for (const entry of MRBTSGraph.flat) {
        const hay = `${entry.name} ${entry.meaning || ''}`.toLowerCase();
        if (words.every((w) => hay.includes(w))) {
            matches.push(entry);
            if (matches.length >= 12) break;
        }
    }

    if (!matches.length) {
        host.innerHTML = '<div class="nokia-graph-search-empty">No matching MOs.</div>';
        host.hidden = false;
        return;
    }

    host.innerHTML = '';
    matches.forEach((entry) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'nokia-graph-search-item';
        btn.innerHTML = `
            <span class="nokia-graph-search-name">${graphEscapeHtml(entry.name)}</span>
            <span class="nokia-graph-search-path">${graphEscapeHtml(entry.id)}</span>
        `;
        btn.addEventListener('click', () => {
            graphJumpTo(entry.id);
            host.hidden = true;
            const input = document.getElementById('nokia-graph-search');
            if (input) input.value = '';
        });
        host.appendChild(btn);
    });
    host.hidden = false;
}

/* ── Details panel ──────────────────────────────────────────────────── */

async function graphShowNodePanel(node) {
    const nameEl = document.getElementById('nokia-graph-node-name');
    const meaningEl = document.getElementById('nokia-graph-node-meaning');
    const levelEl = document.getElementById('nokia-graph-node-level');
    const pathEl = document.getElementById('nokia-graph-node-path');
    const bodyEl = document.getElementById('nokia-graph-panel-body');

    if (!node) return;
    if (nameEl) nameEl.textContent = node.name;
    if (meaningEl) meaningEl.textContent = node.meaning || 'No description available.';
    if (levelEl) {
        levelEl.textContent = `Level ${node.level}`;
        levelEl.style.background = graphLevelColor(node.level);
    }
    if (pathEl) pathEl.textContent = node.id;

    if (!bodyEl) return;
    bodyEl.innerHTML = '<p class="nokia-graph-empty">Loading parameters…</p>';

    try {
        const payload = await graphFetchMoParameters(node.id);
        graphRenderParameterPanel(node, payload, bodyEl);
    } catch (error) {
        bodyEl.innerHTML = `<p class="nokia-graph-empty">Could not load parameters: ${graphEscapeHtml(error.message)}</p>`;
    }
}

async function graphFetchMoParameters(moId) {
    if (MRBTSGraph.paramCache.has(moId)) {
        return MRBTSGraph.paramCache.get(moId);
    }
    const resp = await fetch(`/api/parameter-dictionary/nokia/mo?mo=${encodeURIComponent(moId)}`, {
        credentials: 'same-origin',
        headers: { Accept: 'application/json' },
    });
    const data = await resp.json();
    if (!resp.ok || !data.success) {
        throw new Error(data.error || 'Failed to load MO parameters');
    }
    MRBTSGraph.paramCache.set(moId, data);
    return data;
}

function graphRenderParameterPanel(node, payload, bodyEl) {
    const params = payload.parameters || [];
    const childCount = (node.children || []).length;

    if (!params.length && !childCount) {
        bodyEl.innerHTML = '<p class="nokia-graph-empty">No parameters found for this MO in the Nokia dictionary.</p>';
        return;
    }

    let html = '';

    if (childCount) {
        html += `
            <p class="nokia-graph-link">
                ${childCount} child MO${childCount !== 1 ? 's' : ''} branch from this node.
                Click a surrounding node in the graph to zoom in.
            </p>
        `;
    }

    if (!params.length) {
        html += '<p class="nokia-graph-empty">This MO has no parameter rows in the Nokia dictionary (structural/container MO).</p>';
        bodyEl.innerHTML = html;
        return;
    }

    const displayCols = ['Abbreviated Name', 'Description', 'Parameter Category', 'Data Type', 'Default Value'];
    const cols = displayCols.filter((col) => MRBTSGraph.columns.includes(col));
    const useCols = cols.length ? cols : ['Abbreviated Name', 'Description'];
    const cap = 100;
    const capped = params.length > cap;
    const shown = capped ? params.slice(0, cap) : params;

    html += `
        <h3 class="nokia-graph-section-title">${params.length} parameter${params.length !== 1 ? 's' : ''}${capped ? ` (showing first ${cap})` : ''}</h3>
        <div class="nokia-graph-param-table-wrap">
            <table class="nokia-graph-param-table">
                <thead><tr>${useCols.map((c) => `<th>${graphEscapeHtml(c)}</th>`).join('')}</tr></thead>
                <tbody>
                    ${shown.map((row, idx) => `
                        <tr data-param-index="${idx}">
                            ${useCols.map((col) => `<td>${graphEscapeHtml(graphTruncate(row[col] || '', 140))}</td>`).join('')}
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        </div>
        <p class="nokia-graph-link">Click a parameter row to open full details.</p>
    `;

    bodyEl.innerHTML = html;

    bodyEl.querySelectorAll('[data-param-index]').forEach((tr) => {
        tr.addEventListener('click', () => {
            const index = Number(tr.getAttribute('data-param-index'));
            graphOpenParamDetail(shown[index], node.id);
        });
    });
}

function graphOpenParamDetail(row, moId) {
    const modal = document.getElementById('nokia-detail-modal');
    const body = document.getElementById('nokia-detail-body');
    const title = document.getElementById('nokia-detail-title');
    if (!modal || !body || !row) return;

    const cols = MRBTSGraph.columns.length ? MRBTSGraph.columns : Object.keys(row);
    if (title) {
        title.textContent = `${row['Abbreviated Name'] || 'Parameter'} — ${moId}`;
    }

    body.innerHTML = cols.map((col) => {
        const val = row[col] || '';
        if (!val) return '';
        return `
            <div class="nokia-detail-field">
                <div class="nokia-detail-label">${graphEscapeHtml(col)}</div>
                <div class="nokia-detail-value">${graphEscapeHtml(val).replace(/\n/g, '<br>')}</div>
            </div>
        `;
    }).filter(Boolean).join('');

    modal.hidden = false;
}

/* ── Bootstrap ──────────────────────────────────────────────────────── */

async function initNokiaMrbtsGraph() {
    if (MRBTSGraph.loaded) {
        graphEnsureSvg();
        graphRender();
        graphShowNodePanel(MRBTSGraph.byId.get(MRBTSGraph.selectedId) || MRBTSGraph.tree);
        return;
    }

    const bodyEl = document.getElementById('nokia-graph-panel-body');
    if (bodyEl) bodyEl.innerHTML = '<p class="nokia-graph-empty">Loading MRBTS graph…</p>';

    try {
        const [treeResp, listResp] = await Promise.all([
            fetch('/api/parameter-dictionary/nokia/mrbts-tree', {
                credentials: 'same-origin',
                headers: { Accept: 'application/json' },
            }),
            fetch('/api/parameter-dictionary/list', {
                credentials: 'same-origin',
                headers: { Accept: 'application/json' },
            }),
        ]);

        const treeData = await treeResp.json();
        const listData = await listResp.json();

        if (!treeResp.ok || !treeData.success) {
            throw new Error(treeData.error || 'Failed to load MRBTS tree');
        }
        if (!listResp.ok || !listData.success) {
            throw new Error(listData.error || 'Failed to load Nokia parameter columns');
        }

        MRBTSGraph.tree = treeData.tree;
        MRBTSGraph.flat = treeData.flat || [];
        MRBTSGraph.meta = treeData.meta || {};
        MRBTSGraph.columns = listData.columns || [];
        MRBTSGraph.byId = new Map();
        indexGraphTree(MRBTSGraph.tree);

        MRBTSGraph.focusId = MRBTSGraph.tree.id;
        MRBTSGraph.selectedId = MRBTSGraph.tree.id;
        MRBTSGraph.spreadChildren = false;
        MRBTSGraph.loaded = true;

        graphEnsureSvg();
        graphRender();
        graphShowNodePanel(MRBTSGraph.tree);
    } catch (error) {
        if (bodyEl) {
            bodyEl.innerHTML = `<p class="nokia-graph-empty">Error: ${graphEscapeHtml(error.message)}</p>`;
        }
        showNotification('Failed to load Nokia graphical tree: ' + error.message, 'error');
    }
}

function bindNokiaGraphControls() {
    const zoomOut = document.getElementById('nokia-graph-zoom-out');
    const reset = document.getElementById('nokia-graph-reset');
    const viewZoomIn = document.getElementById('nokia-graph-view-zoom-in');
    const viewZoomOut = document.getElementById('nokia-graph-view-zoom-out');
    const fit = document.getElementById('nokia-graph-fit');
    const search = document.getElementById('nokia-graph-search');
    const searchResults = document.getElementById('nokia-graph-search-results');
    const stage = document.getElementById('nokia-graph-stage');

    if (zoomOut && !zoomOut.dataset.bound) {
        zoomOut.dataset.bound = '1';
        zoomOut.addEventListener('click', graphZoomOut);
    }
    if (reset && !reset.dataset.bound) {
        reset.dataset.bound = '1';
        reset.addEventListener('click', graphResetView);
    }
    if (viewZoomIn && !viewZoomIn.dataset.bound) {
        viewZoomIn.dataset.bound = '1';
        viewZoomIn.addEventListener('click', () => graphZoomBy(1.3));
    }
    if (viewZoomOut && !viewZoomOut.dataset.bound) {
        viewZoomOut.dataset.bound = '1';
        viewZoomOut.addEventListener('click', () => graphZoomBy(0.77));
    }
    if (fit && !fit.dataset.bound) {
        fit.dataset.bound = '1';
        fit.addEventListener('click', () => graphFitView());
    }
    if (search && !search.dataset.bound) {
        search.dataset.bound = '1';
        search.addEventListener('input', () => graphRenderSearchResults(search.value));
        search.addEventListener('keydown', (event) => {
            if (event.key === 'Escape') {
                search.value = '';
                graphRenderSearchResults('');
                search.blur();
            }
        });
        document.addEventListener('click', (event) => {
            if (searchResults && !searchResults.hidden
                && !searchResults.contains(event.target) && event.target !== search) {
                searchResults.hidden = true;
            }
        });
    }
    if (stage && !stage.dataset.bound) {
        stage.dataset.bound = '1';
        window.addEventListener('resize', () => {
            if (document.getElementById('nokia-graph-content')?.style.display === 'none') return;
            graphEnsureSvg();
            graphRender();
        });
        document.addEventListener('keydown', (event) => {
            if (event.key !== 'Escape') return;
            if (document.getElementById('nokia-graph-content')?.style.display === 'none') return;
            if (document.activeElement === document.getElementById('nokia-graph-search')) return;
            if (!document.getElementById('nokia-detail-modal')?.hidden) return;
            graphZoomOut();
        });
    }
}

document.addEventListener('DOMContentLoaded', bindNokiaGraphControls);

window.initNokiaMrbtsGraph = initNokiaMrbtsGraph;
