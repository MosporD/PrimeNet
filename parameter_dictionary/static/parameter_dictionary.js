/**
 * Parameter Dictionary Page JavaScript
 */

let allMOData = {};
let allRows = [];
let categories = new Set();
let dataLoaded = false;
let sortState = { key: 'mo', dir: 'asc' };

// Load MO data on page load
document.addEventListener('DOMContentLoaded', () => {
    const nokiaBtn = document.getElementById('vendor-nokia-btn');
    const huaweiBtn = document.getElementById('vendor-huawei-btn');
    const gate = document.getElementById('vendor-gate');
    const content = document.getElementById('parameter-content');
    const comingSoon = document.getElementById('vendor-coming-soon');

    if (nokiaBtn) {
        nokiaBtn.addEventListener('click', async () => {
            if (comingSoon) comingSoon.style.display = 'none';
            if (gate) gate.style.display = 'none';
            if (content) content.style.display = '';
            if (!dataLoaded) {
                await loadMOData();
            }
        });
    }

    if (huaweiBtn) {
        huaweiBtn.addEventListener('click', () => {
            if (comingSoon) comingSoon.style.display = 'block';
        });
    }

    const searchInput = document.getElementById('search-input');
    const categoryFilter = document.getElementById('category-filter');
    const technologyFilter = document.getElementById('technology-filter');
    if (searchInput) searchInput.addEventListener('input', applyFiltersAndRender);
    if (categoryFilter) categoryFilter.addEventListener('change', applyFiltersAndRender);
    if (technologyFilter) technologyFilter.addEventListener('change', applyFiltersAndRender);
});

async function loadMOData() {
    try {
        const response = await fetch('/api/parameter-dictionary/list');
        const data = await response.json();

        if (data.success) {
            allMOData = data.mos;
            dataLoaded = true;

            Object.values(allMOData).forEach(mo => {
                if (mo.category) {
                    categories.add(mo.category);
                }
            });
            allRows = flattenRows(allMOData);

            populateCategoryFilter();
            applyFiltersAndRender();
        } else {
            showNotification(data.error || 'Failed to load MO data', 'error');
        }
    } catch (error) {
        showNotification('Error loading MO data: ' + error.message, 'error');
    }
}

function populateCategoryFilter() {
    const categoryFilter = document.getElementById('category-filter');
    if (!categoryFilter) return;
    categoryFilter.innerHTML = '<option value="">All Categories</option>';
    categories.forEach(cat => {
        const option = document.createElement('option');
        option.value = cat;
        option.textContent = cat;
        categoryFilter.appendChild(option);
    });
}

function flattenRows(mosData) {
    const rows = [];
    Object.keys(mosData).forEach((moName) => {
        const mo = mosData[moName] || {};
        const moDesc = mo.description || '';
        const category = mo.category || 'Other';
        const parameters = Array.isArray(mo.parameters) ? mo.parameters : [];

        if (!parameters.length) {
            rows.push({
                mo: moName,
                category,
                moDescription: moDesc,
                parameter: '',
                parameterDescription: '',
                technology: detectTechnology(moName),
            });
            return;
        }

        parameters.forEach((param) => {
            if (typeof param === 'string') {
                rows.push({
                    mo: moName,
                    category,
                    moDescription: moDesc,
                    parameter: param,
                    parameterDescription: '',
                    technology: detectTechnology(moName),
                });
            } else {
                rows.push({
                    mo: moName,
                    category,
                    moDescription: moDesc,
                    parameter: (param && param.name) || '',
                    parameterDescription: (param && param.description) || '',
                    technology: detectTechnology(moName),
                });
            }
        });
    });
    return rows;
}

function detectTechnology(moName) {
    const m = String(moName || '').toUpperCase();
    if (m.includes('NR') || m.includes('5G')) return '5G';
    if (m.includes('LTE') || m.includes('LNCEL') || m.includes('EUTRAN')) return 'LTE';
    if (m.includes('WCDMA') || m.includes('WCEL') || m.includes('UTRAN')) return 'WCDMA';
    return 'Other';
}

function applyFiltersAndRender() {
    const searchEl = document.getElementById('search-input');
    const categoryEl = document.getElementById('category-filter');
    const techEl = document.getElementById('technology-filter');
    const searchTerm = ((searchEl && searchEl.value) || '').toLowerCase();
    const categoryFilter = (categoryEl && categoryEl.value) || '';
    const techFilter = (techEl && techEl.value) || '';

    const filteredRows = allRows.filter((r) => {
        const matchesSearch = !searchTerm
            || String(r.mo).toLowerCase().includes(searchTerm)
            || String(r.parameter).toLowerCase().includes(searchTerm)
            || String(r.moDescription).toLowerCase().includes(searchTerm)
            || String(r.parameterDescription).toLowerCase().includes(searchTerm);

        const matchesCategory = !categoryFilter || r.category === categoryFilter;
        const matchesTech = !techFilter || r.technology === techFilter;
        return matchesSearch && matchesCategory && matchesTech;
    });

    const sorted = [...filteredRows].sort((a, b) => compareRows(a, b, sortState.key, sortState.dir));
    renderTable(sorted);
    updateStats(sorted);
}

function compareRows(a, b, key, dir) {
    const av = String(a[key] ?? '').toLowerCase();
    const bv = String(b[key] ?? '').toLowerCase();
    if (av < bv) return dir === 'asc' ? -1 : 1;
    if (av > bv) return dir === 'asc' ? 1 : -1;
    return 0;
}

function setSort(key) {
    if (sortState.key === key) {
        sortState.dir = sortState.dir === 'asc' ? 'desc' : 'asc';
    } else {
        sortState.key = key;
        sortState.dir = 'asc';
    }
    applyFiltersAndRender();
}

function renderTable(rows) {
    const moList = document.getElementById('mo-list');
    if (!moList) return;
    moList.innerHTML = '';

    if (!rows.length) {
        moList.innerHTML = '<p style="text-align: center; color: #7f8c8d; padding: 40px;">No results found</p>';
        return;
    }

    const th = (label, key) => {
        const active = sortState.key === key ? ` ${sortState.dir === 'asc' ? '↑' : '↓'}` : '';
        return `<th><button type="button" class="sort-btn" onclick="setSort('${key}')">${label}${active}</button></th>`;
    };

    moList.innerHTML = `
        <div class="param-table-wrap">
            <table class="param-table">
                <thead>
                    <tr>
                        ${th('MO Class', 'mo')}
                        ${th('Category', 'category')}
                        ${th('Technology', 'technology')}
                        ${th('Parameter', 'parameter')}
                        ${th('Parameter Description', 'parameterDescription')}
                        ${th('MO Description', 'moDescription')}
                    </tr>
                </thead>
                <tbody>
                    ${rows.map((r) => `
                        <tr>
                            <td>${escapeHtml(r.mo)}</td>
                            <td>${escapeHtml(r.category)}</td>
                            <td>${escapeHtml(r.technology)}</td>
                            <td>${escapeHtml(r.parameter || '-')}</td>
                            <td>${escapeHtml(r.parameterDescription || '-')}</td>
                            <td>${escapeHtml(r.moDescription || '-')}</td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        </div>
    `;
}

function escapeHtml(value) {
    return String(value || '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#039;');
}

function updateStats(filteredRows = []) {
    const totalMOs = new Set(filteredRows.map((r) => r.mo)).size;
    const totalParams = filteredRows.filter((r) => String(r.parameter || '').trim()).length;
    const mosEl = document.getElementById('total-mos');
    const paramsEl = document.getElementById('total-params');
    if (mosEl) mosEl.textContent = totalMOs;
    if (paramsEl) paramsEl.textContent = totalParams;
}
