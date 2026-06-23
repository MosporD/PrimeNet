/**

 * RAN Features — vendor picker, tech picker, sidebar tree, and documentation viewer.

 */



let ranTech = '';

let ranHome = '';

let ranTree = [];

let ranFlat = [];

let ranActiveUrl = '';

let ranSearchTimer = null;

let ranVendor = '';



document.addEventListener('DOMContentLoaded', () => {

    const nokiaBtn = document.getElementById('ran-vendor-nokia-btn');

    const huaweiBtn = document.getElementById('ran-vendor-huawei-btn');

    const huaweiBackBtn = document.getElementById('ran-huawei-back-btn');

    const nokiaBackBtn = document.getElementById('ran-nokia-back-btn');



    if (nokiaBtn) {

        nokiaBtn.addEventListener('click', () => openVendor('nokia'));

    }



    if (huaweiBtn) {

        huaweiBtn.addEventListener('click', () => openVendor('huawei'));

    }



    if (huaweiBackBtn) {

        huaweiBackBtn.addEventListener('click', closeVendor);

    }



    if (nokiaBackBtn) {

        nokiaBackBtn.addEventListener('click', closeVendor);

    }



    document.querySelectorAll('.ran-card-btn[data-tech]').forEach((btn) => {

        btn.addEventListener('click', () => openViewer(btn.dataset.tech, btn.dataset.label));

    });



    const backBtn = document.getElementById('ran-back-btn');

    if (backBtn) {

        backBtn.addEventListener('click', closeViewer);

    }



    const search = document.getElementById('ran-search');

    if (search) {

        search.addEventListener('input', () => {

            clearTimeout(ranSearchTimer);

            ranSearchTimer = setTimeout(renderSidebar, 180);

        });

    }



    const params = new URLSearchParams(window.location.search);

    const vendor = (params.get('vendor') || '').toLowerCase().trim();

    const tech = (params.get('view') || '').toLowerCase().trim();



    if (vendor === 'huawei') {

        openVendor('huawei', { skipHistory: true });

        if (tech) {

            const card = document.querySelector(`.ran-card-btn[data-tech="${tech}"]`);

            const label = card ? card.dataset.label : tech.toUpperCase();

            openViewer(tech, label, { skipHistory: true });

        }

    } else if (vendor === 'nokia') {

        openVendor('nokia', { skipHistory: true });

    } else if (tech) {

        const card = document.querySelector(`.ran-card-btn[data-tech="${tech}"]`);

        const label = card ? card.dataset.label : tech.toUpperCase();

        openVendor('huawei', { skipHistory: true });

        openViewer(tech, label, { skipHistory: true });

    }

});



function openVendor(vendor, options = {}) {

    const gate = document.getElementById('ran-vendor-gate');

    const huaweiContent = document.getElementById('ran-huawei-content');

    const nokiaContent = document.getElementById('ran-nokia-content');



    ranVendor = vendor;

    if (gate) gate.hidden = true;

    if (huaweiContent) huaweiContent.hidden = vendor !== 'huawei';

    if (nokiaContent) nokiaContent.hidden = vendor !== 'nokia';



    if (vendor === 'huawei') {

        closeViewer({ skipHistory: true });

    }



    if (!options.skipHistory) {

        syncUrl();

    }

}



function closeVendor() {

    const gate = document.getElementById('ran-vendor-gate');

    const huaweiContent = document.getElementById('ran-huawei-content');

    const nokiaContent = document.getElementById('ran-nokia-content');



    closeViewer({ skipHistory: true });



    ranVendor = '';

    if (gate) gate.hidden = false;

    if (huaweiContent) huaweiContent.hidden = true;

    if (nokiaContent) nokiaContent.hidden = true;



    const url = new URL(window.location.href);

    url.searchParams.delete('vendor');

    url.searchParams.delete('view');

    window.history.replaceState({}, '', url.pathname + (url.search || ''));

}



async function openViewer(tech, label, options = {}) {

    const techGate = document.getElementById('ran-tech-gate');

    const viewer = document.getElementById('ran-viewer');

    const huaweiBar = document.querySelector('#ran-huawei-content > .ran-bar');

    const title = document.getElementById('ran-tech-title');

    const countEl = document.getElementById('ran-result-count');

    const treeEl = document.getElementById('ran-tree');

    const search = document.getElementById('ran-search');



    if (!ranVendor) {

        openVendor('huawei', { skipHistory: true });

    }



    ranTech = tech;

    if (techGate) techGate.hidden = true;

    if (huaweiBar) huaweiBar.hidden = true;

    if (viewer) viewer.hidden = false;

    if (title) title.textContent = label || tech.toUpperCase();

    if (search) search.value = '';

    if (countEl) countEl.textContent = 'Loading documentation index…';

    if (treeEl) treeEl.innerHTML = '';



    if (!options.skipHistory) {

        syncUrl();

    }



    try {

        const resp = await fetch(`/api/ran-features/toc/${encodeURIComponent(tech)}`);

        const data = await resp.json();

        if (!resp.ok || !data.success) {

            throw new Error(data.error || 'Failed to load index');

        }

        ranTree = Array.isArray(data.tree) ? data.tree : [];

        ranFlat = Array.isArray(data.flat) ? data.flat : [];

        ranHome = data.home || '';

        ranActiveUrl = ranHome;

        renderSidebar();

        navigateDoc(ranHome);

    } catch (err) {

        if (countEl) countEl.textContent = 'Error: ' + err.message;

    }

}



function closeViewer(options = {}) {

    const techGate = document.getElementById('ran-tech-gate');

    const viewer = document.getElementById('ran-viewer');

    const huaweiBar = document.querySelector('#ran-huawei-content > .ran-bar');

    const frame = document.getElementById('ran-frame');



    if (techGate) techGate.hidden = false;

    if (huaweiBar) huaweiBar.hidden = false;

    if (viewer) viewer.hidden = true;

    if (frame) frame.src = 'about:blank';



    ranTech = '';

    ranTree = [];

    ranFlat = [];

    ranActiveUrl = '';



    if (!options.skipHistory) {

        syncUrl();

    }

}



function syncUrl() {

    const url = new URL(window.location.href);

    if (ranVendor) {

        url.searchParams.set('vendor', ranVendor);

    } else {

        url.searchParams.delete('vendor');

    }

    if (ranTech) {

        url.searchParams.set('view', ranTech);

    } else {

        url.searchParams.delete('view');

    }

    window.history.replaceState({}, '', url.pathname + (url.search || ''));

}



function renderSidebar() {

    const container = document.getElementById('ran-tree');

    const countEl = document.getElementById('ran-result-count');

    const term = (document.getElementById('ran-search')?.value || '').trim().toLowerCase();

    if (!container) return;



    container.innerHTML = '';



    if (term.length >= 2) {

        renderSearchResults(container, countEl, term);

        return;

    }



    if (countEl) {

        countEl.textContent = `${ranFlat.length} topics — expand sections or type to search`;

    }



    const frag = document.createDocumentFragment();

    ranTree.forEach((node) => frag.appendChild(renderTreeNode(node, 0)));

    container.appendChild(frag);

}



function renderSearchResults(container, countEl, term) {

    const words = term.split(/\s+/).filter(Boolean);

    let filtered = ranFlat.filter((entry) => {

        const hay = `${entry.name} ${entry.path}`.toLowerCase();

        return words.every((w) => hay.includes(w));

    });



    const CAP = 400;

    const capped = filtered.length > CAP;

    if (capped) filtered = filtered.slice(0, CAP);



    if (countEl) {

        countEl.textContent = `${filtered.length} result${filtered.length !== 1 ? 's' : ''}${capped ? ` (showing first ${CAP})` : ''}`;

    }



    const frag = document.createDocumentFragment();

    filtered.forEach((entry) => {

        const btn = document.createElement('button');

        btn.type = 'button';

        btn.className = 'ran-search-item' + (entry.url === ranActiveUrl ? ' active' : '');

        btn.innerHTML = `

            <span class="ran-search-name">${highlightMatch(entry.name, term)}</span>

            <span class="ran-search-path">${escapeHtml(entry.path)}</span>

        `;

        btn.addEventListener('click', () => navigateDoc(entry.url));

        frag.appendChild(btn);

    });

    container.appendChild(frag);

}



function renderTreeNode(node, depth) {

    const hasChildren = Array.isArray(node.children) && node.children.length > 0;

    const wrap = document.createElement('div');

    wrap.className = 'ran-tree-node';



    const row = document.createElement('div');

    row.className = 'ran-tree-row';

    row.style.paddingLeft = `${10 + depth * 14}px`;



    if (hasChildren) {

        const toggle = document.createElement('button');

        toggle.type = 'button';

        toggle.className = 'ran-tree-toggle';

        toggle.setAttribute('aria-label', 'Expand section');

        toggle.textContent = '▾';

        toggle.addEventListener('click', (e) => {

            e.stopPropagation();

            const expanded = wrap.classList.toggle('collapsed');

            toggle.textContent = expanded ? '▸' : '▾';

        });

        row.appendChild(toggle);

    } else {

        const spacer = document.createElement('span');

        spacer.className = 'ran-tree-spacer';

        row.appendChild(spacer);

    }



    const label = document.createElement('button');

    label.type = 'button';

    label.className = 'ran-tree-label' + (node.url && node.url === ranActiveUrl ? ' active' : '');

    label.textContent = node.name;

    label.title = node.path || node.name;

    if (node.url) {

        label.addEventListener('click', () => navigateDoc(node.url));

    } else {

        label.classList.add('ran-tree-label-muted');

        label.disabled = true;

    }

    row.appendChild(label);

    wrap.appendChild(row);



    if (hasChildren) {

        const childrenEl = document.createElement('div');

        childrenEl.className = 'ran-tree-children';

        node.children.forEach((child) => childrenEl.appendChild(renderTreeNode(child, depth + 1)));

        wrap.appendChild(childrenEl);

    }



    return wrap;

}



function navigateDoc(url) {

    const frame = document.getElementById('ran-frame');

    if (!frame || !url || !ranTech) return;

    ranActiveUrl = url;

    frame.src = `/ran-features/view/${encodeURIComponent(ranTech)}/${url.split('/').map(encodeURIComponent).join('/')}`;

    renderSidebar();

}



function highlightMatch(text, term) {

    let result = escapeHtml(text);

    term.split(/\s+/).filter(Boolean).forEach((w) => {

        const re = new RegExp('(' + w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'gi');

        result = result.replace(re, '<mark>$1</mark>');

    });

    return result;

}



function escapeHtml(value) {

    return String(value || '')

        .replaceAll('&', '&amp;')

        .replaceAll('<', '&lt;')

        .replaceAll('>', '&gt;')

        .replaceAll('"', '&quot;')

        .replaceAll("'", '&#039;');

}

