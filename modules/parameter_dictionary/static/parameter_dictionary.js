/**
 * Parameter Dictionary Page JavaScript
 */

/* ── Nokia browser state ── */
let nokiaColumns = [];
let nokiaMOIndex = [];
let nokiaMeta = {};
let nokiaLoaded = false;
let nokiaActiveMO = '';
let nokiaActiveRows = [];
let nokiaSearchCapped = false;
let nokiaMoSearchTimer = null;
let nokiaParamSearchTimer = null;
let nokiaParamFetchToken = 0;

/* ── Huawei TOC search state ── */
let hwToc = [];
let hwTocLoaded = false;
let hwActiveUrl = '';
let hwSearchTimer = null;

function hideAllVendorSections() {
    const gate = document.getElementById('vendor-gate');
    const nokiaContent = document.getElementById('nokia-content');
    const nokiaGraphContent = document.getElementById('nokia-graph-content');
    const huaweiContent = document.getElementById('huawei-content');

    if (gate) gate.style.display = 'none';
    if (nokiaContent) nokiaContent.style.display = 'none';
    if (nokiaGraphContent) nokiaGraphContent.style.display = 'none';
    if (huaweiContent) huaweiContent.style.display = 'none';
}

function showVendorGate() {
    const gate = document.getElementById('vendor-gate');
    const nokiaContent = document.getElementById('nokia-content');
    const nokiaGraphContent = document.getElementById('nokia-graph-content');
    const huaweiContent = document.getElementById('huawei-content');

    if (nokiaContent) nokiaContent.style.display = 'none';
    if (nokiaGraphContent) nokiaGraphContent.style.display = 'none';
    if (huaweiContent) huaweiContent.style.display = 'none';
    if (gate) gate.style.display = '';
}

function readParameterDictionaryDeepLink() {
    const params = new URLSearchParams(window.location.search);
    const vendor = (params.get('vendor') || '').trim().toLowerCase();
    if (!vendor) return null;
    return {
        vendor,
        mo: (params.get('mo') || '').trim(),
        param: (params.get('param') || '').trim(),
        q: (params.get('q') || '').trim(),
        page: (params.get('page') || '').trim(),
    };
}

async function applyParameterDictionaryDeepLink(link) {
    if (!link) return;

    hideAllVendorSections();
    if (typeof window.setParameterDictionaryAiVendor === 'function') {
        window.setParameterDictionaryAiVendor(link.vendor === 'huawei' ? 'huawei' : 'nokia');
    }

    if (link.vendor === 'huawei') {
        const huaweiContent = document.getElementById('huawei-content');
        if (huaweiContent) huaweiContent.style.display = '';
        if (!hwTocLoaded) {
            await loadHuaweiToc();
        }
        const hwSearch = document.getElementById('huawei-search');
        if (link.page) {
            navigateHuawei(link.page);
        } else if (link.q && hwSearch) {
            hwSearch.value = link.q;
            renderHuaweiResults();
            const first = document.querySelector('#huawei-results .hw-toc-item');
            if (first) first.click();
        }
        return;
    }

    const nokiaContent = document.getElementById('nokia-content');
    if (nokiaContent) nokiaContent.style.display = '';
    if (!nokiaLoaded) {
        await loadNokiaData();
    }

    const searchTerm = link.param || link.q;
    if (link.mo && nokiaMOIndex.some((item) => item.mo === link.mo)) {
        selectNokiaMO(link.mo);
    }

    if (searchTerm) {
        const paramSearch = document.getElementById('nokia-param-search');
        if (paramSearch) paramSearch.value = searchTerm;
        await fetchAndRenderNokiaParamTable();

        const exact = nokiaActiveRows.find(
            (row) => String(row['Abbreviated Name'] || '').toLowerCase() === searchTerm.toLowerCase()
        );
        const partial = nokiaActiveRows.find(
            (row) => String(row['Abbreviated Name'] || '').toLowerCase().includes(searchTerm.toLowerCase())
        );
        const match = exact || partial || nokiaActiveRows[0];
        if (match) {
            if (match._mo && match._mo !== nokiaActiveMO) {
                selectNokiaMO(match._mo);
                const paramSearchAgain = document.getElementById('nokia-param-search');
                if (paramSearchAgain) paramSearchAgain.value = searchTerm;
                await fetchAndRenderNokiaParamTable();
                const rematch = nokiaActiveRows.find(
                    (row) => String(row['Abbreviated Name'] || '').toLowerCase() === String(match['Abbreviated Name'] || '').toLowerCase()
                );
                if (rematch) openNokiaDetail(rematch);
            } else {
                openNokiaDetail(match);
            }
        }
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const nokiaBtn = document.getElementById('vendor-nokia-btn');
    const nokiaTreeBtn = document.getElementById('vendor-nokia-tree-btn');
    const huaweiBtn = document.getElementById('vendor-huawei-btn');
    const nokiaContent = document.getElementById('nokia-content');
    const nokiaGraphContent = document.getElementById('nokia-graph-content');
    const huaweiContent = document.getElementById('huawei-content');
    const nokiaBackBtn = document.getElementById('nokia-back-btn');
    const nokiaGraphBackBtn = document.getElementById('nokia-graph-back-btn');
    const huaweiBackBtn = document.getElementById('huawei-back-btn');
    const hwSearch = document.getElementById('huawei-search');

    if (nokiaBtn) {
        nokiaBtn.addEventListener('click', async () => {
            hideAllVendorSections();
            if (nokiaContent) nokiaContent.style.display = '';
            if (typeof window.setParameterDictionaryAiVendor === 'function') {
                window.setParameterDictionaryAiVendor('nokia');
            }
            if (!nokiaLoaded) {
                await loadNokiaData();
            }
        });
    }

    if (nokiaTreeBtn) {
        nokiaTreeBtn.addEventListener('click', async () => {
            hideAllVendorSections();
            if (nokiaGraphContent) nokiaGraphContent.style.display = '';
            if (typeof window.setParameterDictionaryAiVendor === 'function') {
                window.setParameterDictionaryAiVendor('nokia');
            }
            if (typeof window.initNokiaMrbtsGraph === 'function') {
                await window.initNokiaMrbtsGraph();
            }
        });
    }

    if (huaweiBtn) {
        huaweiBtn.addEventListener('click', async () => {
            hideAllVendorSections();
            if (huaweiContent) huaweiContent.style.display = '';
            if (typeof window.setParameterDictionaryAiVendor === 'function') {
                window.setParameterDictionaryAiVendor('huawei');
            }
            if (!hwTocLoaded) {
                await loadHuaweiToc();
            }
        });
    }

    if (nokiaBackBtn) {
        nokiaBackBtn.addEventListener('click', showVendorGate);
    }

    if (nokiaGraphBackBtn) {
        nokiaGraphBackBtn.addEventListener('click', showVendorGate);
    }

    if (huaweiBackBtn) {
        huaweiBackBtn.addEventListener('click', showVendorGate);
    }

    const nokiaMoSearch = document.getElementById('nokia-mo-search');
    const nokiaParamSearch = document.getElementById('nokia-param-search');
    const nokiaTechFilter = document.getElementById('nokia-tech-filter');
    const nokiaCategoryFilter = document.getElementById('nokia-category-filter');
    const detailClose = document.getElementById('nokia-detail-close');
    const detailBackdrop = document.getElementById('nokia-detail-backdrop');

    if (nokiaMoSearch) {
        nokiaMoSearch.addEventListener('input', () => {
            clearTimeout(nokiaMoSearchTimer);
            nokiaMoSearchTimer = setTimeout(renderNokiaMOList, 180);
        });
    }
    if (nokiaParamSearch) {
        nokiaParamSearch.addEventListener('input', () => {
            clearTimeout(nokiaParamSearchTimer);
            nokiaParamSearchTimer = setTimeout(() => fetchAndRenderNokiaParamTable(), 280);
        });
    }
    if (nokiaTechFilter) nokiaTechFilter.addEventListener('change', renderNokiaMOList);
    if (nokiaCategoryFilter) nokiaCategoryFilter.addEventListener('change', renderNokiaMOList);
    if (detailClose) detailClose.addEventListener('click', closeNokiaDetail);
    if (detailBackdrop) detailBackdrop.addEventListener('click', closeNokiaDetail);

    if (hwSearch) {
        hwSearch.addEventListener('input', () => {
            clearTimeout(hwSearchTimer);
            hwSearchTimer = setTimeout(renderHuaweiResults, 180);
        });
    }

    applyParameterDictionaryDeepLink(readParameterDictionaryDeepLink());
});

/* ── Nokia browser ── */
async function loadNokiaData() {
    const countEl = document.getElementById('nokia-mo-count');
    if (countEl) countEl.textContent = 'Loading Nokia parameters…';
    try {
        const response = await fetch('/api/parameter-dictionary/list');
        const data = await response.json();
        if (!data.success) {
            throw new Error(data.error || 'Failed to load Nokia parameters');
        }
        nokiaColumns = Array.isArray(data.columns) ? data.columns : [];
        nokiaMOIndex = Array.isArray(data.mo_index) ? data.mo_index : [];
        nokiaMeta = data.meta || {};
        nokiaLoaded = true;

        const sourceEl = document.getElementById('nokia-source-label');
        if (sourceEl && nokiaMeta.source) {
            sourceEl.textContent = nokiaMeta.source;
        }

        populateNokiaFilters();
        updateNokiaStats(nokiaMOIndex.length, nokiaMeta.param_count || 0);
        renderNokiaMOList();

        if (nokiaMOIndex.length) {
            selectNokiaMO(nokiaMOIndex[0].mo);
        }
    } catch (error) {
        if (countEl) countEl.textContent = 'Error loading data';
        showNotification('Error loading Nokia parameters: ' + error.message, 'error');
    }
}

function populateNokiaFilters() {
    const techFilter = document.getElementById('nokia-tech-filter');
    const categoryFilter = document.getElementById('nokia-category-filter');
    const techs = nokiaMeta.technologies || [];
    const cats = nokiaMeta.categories || [];

    if (techFilter) {
        techFilter.innerHTML = '<option value="">All Technologies</option>';
        techs.forEach((tech) => {
            const opt = document.createElement('option');
            opt.value = tech;
            opt.textContent = tech;
            techFilter.appendChild(opt);
        });
    }
    if (categoryFilter) {
        categoryFilter.innerHTML = '<option value="">All Categories</option>';
        cats.forEach((cat) => {
            const opt = document.createElement('option');
            opt.value = cat;
            opt.textContent = cat;
            categoryFilter.appendChild(opt);
        });
    }
}

function renderNokiaMOList() {
    const container = document.getElementById('nokia-mo-list');
    const countEl = document.getElementById('nokia-mo-count');
    if (!container) return;

    const term = (document.getElementById('nokia-mo-search')?.value || '').trim().toLowerCase();
    const tech = document.getElementById('nokia-tech-filter')?.value || '';
    const category = document.getElementById('nokia-category-filter')?.value || '';

    let filtered = nokiaMOIndex.filter((item) => {
        if (tech && item.technology !== tech) return false;
        if (category && item.category !== category) return false;
        if (!term) return true;
        const hay = `${item.mo} ${item.leaf}`.toLowerCase();
        const words = term.split(/\s+/).filter(Boolean);
        return words.every((w) => hay.includes(w));
    });

    if (countEl) {
        countEl.textContent = term || tech || category
            ? `${filtered.length} MO class${filtered.length !== 1 ? 'es' : ''}`
            : `${nokiaMOIndex.length} MO classes`;
    }

    container.innerHTML = '';
    const frag = document.createDocumentFragment();
    filtered.forEach((item) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'nokia-mo-item' + (item.mo === nokiaActiveMO ? ' active' : '');
        btn.innerHTML = `
            <span class="nokia-mo-item-name">${term ? highlightMatch(item.leaf || item.mo, term) : escapeHtml(item.leaf || item.mo)}</span>
            <span class="nokia-mo-item-path">${escapeHtml(item.mo)}</span>
            <span class="nokia-mo-item-meta">${escapeHtml(item.technology || '')} · ${item.parameter_count} params</span>
        `;
        btn.addEventListener('click', () => selectNokiaMO(item.mo));
        frag.appendChild(btn);
    });
    container.appendChild(frag);
}

function selectNokiaMO(moName) {
    nokiaActiveMO = moName;
    const indexItem = nokiaMOIndex.find((item) => item.mo === moName) || {};
    const titleEl = document.getElementById('nokia-selected-mo');
    const metaEl = document.getElementById('nokia-selected-meta');
    const paramSearch = document.getElementById('nokia-param-search');

    if (titleEl) titleEl.textContent = moName;
    if (metaEl) {
        metaEl.textContent = [
            indexItem.technology || '',
            indexItem.category || '',
            `${indexItem.parameter_count || 0} parameters`,
        ].filter(Boolean).join(' · ');
    }
    if (paramSearch) paramSearch.value = '';

    renderNokiaMOList();
    fetchAndRenderNokiaParamTable();
    updateNokiaStats(nokiaMOIndex.length, nokiaMeta.param_count || 0);
}

async function fetchAndRenderNokiaParamTable() {
    const host = document.getElementById('nokia-param-table');
    const term = (document.getElementById('nokia-param-search')?.value || '').trim();
    const token = ++nokiaParamFetchToken;

    if (host) {
        host.innerHTML = '<p class="nokia-empty">Loading parameters…</p>';
    }

    try {
        let rows = [];
        let capped = false;

        if (term.length >= 2) {
            const resp = await fetch(`/api/parameter-dictionary/nokia/search?q=${encodeURIComponent(term)}&limit=500`, {
                credentials: 'same-origin',
                headers: { Accept: 'application/json' },
            });
            const data = await resp.json();
            if (!resp.ok || !data.success) {
                throw new Error(data.error || 'Search failed');
            }
            rows = (data.parameters || []).map((row) => ({ ...row, _mo: row._mo || row['MO Class'] || '' }));
            capped = !!data.capped;
        } else if (nokiaActiveMO) {
            const resp = await fetch(`/api/parameter-dictionary/nokia/mo?mo=${encodeURIComponent(nokiaActiveMO)}`, {
                credentials: 'same-origin',
                headers: { Accept: 'application/json' },
            });
            const data = await resp.json();
            if (!resp.ok || !data.success) {
                throw new Error(data.error || 'Failed to load MO parameters');
            }
            rows = (data.parameters || []).map((row) => ({ ...row, _mo: nokiaActiveMO }));
        }

        if (token !== nokiaParamFetchToken) return;

        nokiaActiveRows = rows;
        nokiaSearchCapped = capped;
        renderNokiaParamTable();
    } catch (error) {
        if (token !== nokiaParamFetchToken) return;
        if (host) {
            host.innerHTML = `<p class="nokia-empty">Error: ${escapeHtml(error.message)}</p>`;
        }
        showNotification('Failed to load parameters: ' + error.message, 'error');
    }
}

function renderNokiaParamTable() {
    const host = document.getElementById('nokia-param-table');
    if (!host) return;

    const rows = nokiaActiveRows;
    const term = (document.getElementById('nokia-param-search')?.value || '').trim();
    const showMoColumn = term.length >= 2;

    if (!rows.length) {
        host.innerHTML = '<p class="nokia-empty">No parameters to display. Select an MO class or search (min 2 characters).</p>';
        return;
    }

    const cols = [...nokiaColumns];
    if (showMoColumn && !cols.includes('MO Class')) {
        cols.unshift('MO Class');
    }

    const header = cols.map((col) => `<th>${escapeHtml(col)}</th>`).join('');
    const body = rows.map((row, idx) => {
        const cells = cols.map((col) => {
            const val = col === 'MO Class' && showMoColumn ? (row._mo || row['MO Class'] || '') : (row[col] || '');
            return `<td>${escapeHtml(truncateCell(val))}</td>`;
        }).join('');
        return `<tr class="nokia-param-row" data-row-index="${idx}" tabindex="0">${cells}</tr>`;
    }).join('');

    const capNote = nokiaSearchCapped
        ? '<p class="nokia-cap-note">Showing first 500 matching parameters. Refine your search to narrow results.</p>'
        : '';

    host.innerHTML = `
        ${capNote}
        <div class="param-table-wrap nokia-table-wrap">
            <table class="param-table nokia-excel-table">
                <thead><tr>${header}</tr></thead>
                <tbody>${body}</tbody>
            </table>
        </div>
        <p class="nokia-table-hint">Click a row to view all fields. Scroll horizontally for all Excel columns.</p>
    `;

    host.querySelectorAll('.nokia-param-row').forEach((tr) => {
        tr.addEventListener('click', () => {
            const index = Number(tr.getAttribute('data-row-index'));
            openNokiaDetail(rows[index]);
        });
        tr.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                const index = Number(tr.getAttribute('data-row-index'));
                openNokiaDetail(rows[index]);
            }
        });
    });
}

function openNokiaDetail(row) {
    const modal = document.getElementById('nokia-detail-modal');
    const body = document.getElementById('nokia-detail-body');
    const title = document.getElementById('nokia-detail-title');
    if (!modal || !body || !row) return;

    if (title) {
        title.textContent = `${row['Abbreviated Name'] || 'Parameter'} — ${row._mo || row['MO Class'] || ''}`;
    }

    body.innerHTML = nokiaColumns.map((col) => {
        const val = row[col] || '';
        if (!val) return '';
        return `
            <div class="nokia-detail-field">
                <div class="nokia-detail-label">${escapeHtml(col)}</div>
                <div class="nokia-detail-value">${escapeHtml(val).replace(/\n/g, '<br>')}</div>
            </div>
        `;
    }).filter(Boolean).join('');

    modal.hidden = false;
}

function closeNokiaDetail() {
    const modal = document.getElementById('nokia-detail-modal');
    if (modal) modal.hidden = true;
}

function updateNokiaStats(moCount, paramCount) {
    const mosEl = document.getElementById('total-mos');
    const paramsEl = document.getElementById('total-params');
    if (mosEl) mosEl.textContent = moCount;
    if (paramsEl) paramsEl.textContent = paramCount;
}

function truncateCell(value, max = 120) {
    const text = String(value || '');
    if (text.length <= max) return text;
    return text.slice(0, max - 1) + '…';
}

/* ── Huawei TOC helpers ── */
async function loadHuaweiToc() {
    const countEl = document.getElementById('huawei-result-count');
    if (countEl) countEl.textContent = 'Loading index…';
    try {
        const resp = await fetch('/api/parameter-dictionary/huawei-toc');
        const data = await resp.json();
        if (data.success) {
            hwToc = data.entries;
            hwTocLoaded = true;
            renderHuaweiResults();
        } else if (countEl) {
            countEl.textContent = 'Failed to load index';
        }
    } catch (e) {
        const countEl2 = document.getElementById('huawei-result-count');
        if (countEl2) countEl2.textContent = 'Error: ' + e.message;
    }
}

function renderHuaweiResults() {
    const container = document.getElementById('huawei-results');
    const countEl = document.getElementById('huawei-result-count');
    const term = (document.getElementById('huawei-search')?.value || '').trim().toLowerCase();
    if (!container) return;

    let filtered = hwToc;
    if (term.length >= 2) {
        const words = term.split(/\s+/).filter(Boolean);
        filtered = hwToc.filter((e) => {
            const lower = e.name.toLowerCase();
            return words.every((w) => lower.includes(w));
        });
    }

    const CAP = 500;
    const capped = filtered.length > CAP;
    const show = capped ? filtered.slice(0, CAP) : filtered;

    if (countEl) {
        countEl.textContent = term.length >= 2
            ? `${filtered.length} result${filtered.length !== 1 ? 's' : ''}${capped ? ' (showing first ' + CAP + ')' : ''}`
            : `${hwToc.length} entries — type to search`;
    }

    container.innerHTML = '';
    const frag = document.createDocumentFragment();
    show.forEach((entry) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'hw-toc-item' + (entry.url === hwActiveUrl ? ' active' : '');
        btn.innerHTML = term.length >= 2 ? highlightMatch(entry.name, term) : escapeHtml(entry.name);
        btn.addEventListener('click', () => navigateHuawei(entry.url));
        frag.appendChild(btn);
    });
    container.appendChild(frag);
}

function highlightMatch(text, term) {
    const escaped = escapeHtml(text);
    const words = term.split(/\s+/).filter(Boolean);
    let result = escaped;
    words.forEach((w) => {
        const re = new RegExp('(' + w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'gi');
        result = result.replace(re, '<mark>$1</mark>');
    });
    return result;
}

function navigateHuawei(url) {
    const frame = document.getElementById('huawei-frame');
    if (!frame) return;
    hwActiveUrl = url;
    frame.src = '/parameter-dictionary/huawei/' + url;
    renderHuaweiResults();
}

function escapeHtml(value) {
    return String(value || '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#039;');
}
