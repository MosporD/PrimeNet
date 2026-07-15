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
    gLinks: null,
    gNodes: null,
    width: 900,
    height: 600,
};

const LEVEL_COLORS = {
    1: '#0f172a',
    2: '#12416b',
    3: '#1d4ed8',
    4: '#0369a1',
    5: '#0f766e',
    6: '#b45309',
    7: '#a16207',
    8: '#7c3aed',
};

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

function indexGraphTree(node) {
    if (!node || !node.id) return;
    MRBTSGraph.byId.set(node.id, node);
    (node.children || []).forEach(indexGraphTree);
}

function graphLayout(focusNode) {
    const { width, height } = MRBTSGraph;
    const cx = width / 2;
    const cy = height / 2;
    const children = MRBTSGraph.spreadChildren ? (focusNode.children || []) : [];
    const count = children.length;

    const focusRadius = count > 30 ? 46 : count > 12 ? 54 : 62;
    const childRadius = count > 50 ? 14 : count > 30 ? 17 : count > 16 ? 20 : 24;
    const orbitRadius = count === 0
        ? 0
        : Math.max(150, Math.min(340, 70 + count * (count > 40 ? 7 : 11)));

    const nodes = [{
        node: focusNode,
        x: cx,
        y: cy,
        r: focusRadius,
        kind: 'focus',
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

    return { nodes, cx, cy, orbitRadius };
}

function graphEnsureSvg() {
    const host = document.getElementById('nokia-graph-stage');
    if (!host) return null;

    let svg = document.getElementById('mrbts-graph-svg');
    if (!svg) {
        svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.id = 'mrbts-graph-svg';
        svg.classList.add('nokia-graph-svg');
        svg.setAttribute('role', 'img');
        svg.setAttribute('aria-label', 'MRBTS managed object hierarchy graph');
        host.appendChild(svg);
    }

    MRBTSGraph.svg = svg;
    MRBTSGraph.width = host.clientWidth || 900;
    MRBTSGraph.height = host.clientHeight || 600;
    svg.setAttribute('viewBox', `0 0 ${MRBTSGraph.width} ${MRBTSGraph.height}`);

    if (!MRBTSGraph.gLinks) {
        MRBTSGraph.gLinks = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        MRBTSGraph.gLinks.setAttribute('class', 'graph-links');
        svg.appendChild(MRBTSGraph.gLinks);
    }
    if (!MRBTSGraph.gNodes) {
        MRBTSGraph.gNodes = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        MRBTSGraph.gNodes.setAttribute('class', 'graph-nodes');
        svg.appendChild(MRBTSGraph.gNodes);
    }

    return svg;
}

function graphRender() {
    const focusNode = MRBTSGraph.byId.get(MRBTSGraph.focusId);
    if (!focusNode || !graphEnsureSvg()) return;

    const layout = graphLayout(focusNode);
    const focusPoint = layout.nodes[0];
    const token = ++MRBTSGraph.animToken;

    MRBTSGraph.gLinks.innerHTML = '';
    MRBTSGraph.gNodes.innerHTML = '';

    layout.nodes.forEach((item) => {
        if (item.kind === 'focus') return;
        const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        line.setAttribute('class', 'graph-link');
        line.setAttribute('x1', String(focusPoint.x));
        line.setAttribute('y1', String(focusPoint.y));
        line.setAttribute('x2', String(item.x));
        line.setAttribute('y2', String(item.y));
        MRBTSGraph.gLinks.appendChild(line);
    });

    layout.nodes.forEach((item) => {
        const mo = item.node;
        const group = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        group.setAttribute('class', 'graph-node-group'
            + (item.kind === 'focus' ? ' focus' : '')
            + (mo.id === MRBTSGraph.selectedId ? ' selected' : ''));
        group.dataset.id = mo.id;

        const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        circle.setAttribute('class', 'graph-node-circle graph-level-' + mo.level);
        circle.setAttribute('cx', String(item.x));
        circle.setAttribute('cy', String(item.y));
        circle.setAttribute('r', String(item.r));
        circle.setAttribute('fill', LEVEL_COLORS[mo.level] || '#64748b');

        const label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        label.setAttribute('class', 'graph-node-label');
        label.setAttribute('x', String(item.x));
        label.setAttribute('y', String(item.y + item.r + 14));
        label.textContent = mo.name;

        const sub = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        sub.setAttribute('class', 'graph-node-sub');
        sub.setAttribute('x', String(item.x));
        const subY = item.kind === 'focus'
            ? item.y + 5
            : item.y + item.r + 26;
        sub.setAttribute('y', String(subY));
        if (item.kind === 'focus') {
            sub.textContent = MRBTSGraph.spreadChildren
                ? graphTruncate(mo.meaning || '', 28)
                : ((mo.children || []).length
                    ? 'Click to expand branches'
                    : graphTruncate(mo.meaning || '', 28));
        } else if ((mo.children || []).length) {
            sub.textContent = `${(mo.children || []).length} children`;
        } else {
            sub.textContent = graphTruncate(mo.meaning || '', 22);
        }

        group.appendChild(circle);
        group.appendChild(label);
        if (sub.textContent) group.appendChild(sub);

        group.addEventListener('click', (event) => {
            event.stopPropagation();
            graphOnNodeClick(mo, item.kind);
        });

        MRBTSGraph.gNodes.appendChild(group);
    });

    graphUpdateToolbar();
    graphUpdateCrumbs();

    if (token === MRBTSGraph.animToken) {
        MRBTSGraph.gNodes.style.opacity = '0';
        MRBTSGraph.gLinks.style.opacity = '0';
        requestAnimationFrame(() => {
            MRBTSGraph.gNodes.style.transition = 'opacity 0.28s ease';
            MRBTSGraph.gLinks.style.transition = 'opacity 0.28s ease';
            MRBTSGraph.gNodes.style.opacity = '1';
            MRBTSGraph.gLinks.style.opacity = '1';
        });
    }
}

function graphOnNodeClick(node, kind) {
    MRBTSGraph.selectedId = node.id;
    graphShowNodePanel(node);

    if (kind === 'focus') {
        if (!MRBTSGraph.spreadChildren && (node.children || []).length > 0) {
            MRBTSGraph.spreadChildren = true;
            graphRender();
            return;
        }
    } else if ((node.children || []).length > 0) {
        MRBTSGraph.focusId = node.id;
        MRBTSGraph.spreadChildren = true;
    }

    graphRender();
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

async function graphShowNodePanel(node) {
    const nameEl = document.getElementById('nokia-graph-node-name');
    const meaningEl = document.getElementById('nokia-graph-node-meaning');
    const levelEl = document.getElementById('nokia-graph-node-level');
    const pathEl = document.getElementById('nokia-graph-node-path');
    const bodyEl = document.getElementById('nokia-graph-panel-body');

    if (nameEl) nameEl.textContent = node.name;
    if (meaningEl) meaningEl.textContent = node.meaning || 'No description available.';
    if (levelEl) {
        levelEl.textContent = `Level ${node.level}`;
        levelEl.style.background = LEVEL_COLORS[node.level] || '#64748b';
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
    const stage = document.getElementById('nokia-graph-stage');

    if (zoomOut && !zoomOut.dataset.bound) {
        zoomOut.dataset.bound = '1';
        zoomOut.addEventListener('click', graphZoomOut);
    }
    if (reset && !reset.dataset.bound) {
        reset.dataset.bound = '1';
        reset.addEventListener('click', graphResetView);
    }
    if (stage && !stage.dataset.bound) {
        stage.dataset.bound = '1';
        window.addEventListener('resize', () => {
            if (document.getElementById('nokia-graph-content')?.style.display === 'none') return;
            graphEnsureSvg();
            graphRender();
        });
    }
}

document.addEventListener('DOMContentLoaded', bindNokiaGraphControls);

window.initNokiaMrbtsGraph = initNokiaMrbtsGraph;
