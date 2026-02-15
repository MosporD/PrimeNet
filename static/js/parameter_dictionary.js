/**
 * Parameter Dictionary Page JavaScript
 */

let allMOData = {};
let categories = new Set();

// Load MO data on page load
document.addEventListener('DOMContentLoaded', () => {
    loadMOData();
});

// Search functionality
document.getElementById('search-input').addEventListener('input', filterMOs);
document.getElementById('category-filter').addEventListener('change', filterMOs);
document.getElementById('technology-filter').addEventListener('change', filterMOs);

async function loadMOData() {
    try {
        const response = await fetch('/api/parameter-dictionary/list');
        const data = await response.json();

        if (data.success) {
            allMOData = data.mos;

            Object.values(allMOData).forEach(mo => {
                if (mo.category) {
                    categories.add(mo.category);
                }
            });

            populateCategoryFilter();
            displayMOs(allMOData);
            updateStats();
        } else {
            showNotification(data.error || 'Failed to load MO data', 'error');
        }
    } catch (error) {
        showNotification('Error loading MO data: ' + error.message, 'error');
    }
}

function populateCategoryFilter() {
    const categoryFilter = document.getElementById('category-filter');
    categories.forEach(cat => {
        const option = document.createElement('option');
        option.value = cat;
        option.textContent = cat;
        categoryFilter.appendChild(option);
    });
}

function displayMOs(mosData) {
    const moList = document.getElementById('mo-list');
    moList.innerHTML = '';

    const moNames = Object.keys(mosData).sort();

    if (moNames.length === 0) {
        moList.innerHTML = '<p style="text-align: center; color: #7f8c8d; padding: 40px;">No results found</p>';
        return;
    }

    moNames.forEach(moName => {
        const mo = mosData[moName];
        const moItem = document.createElement('div');
        moItem.className = 'mo-item';

        const moHeader = document.createElement('div');
        moHeader.className = 'mo-header';
        moHeader.onclick = () => toggleMO(moItem);

        moHeader.innerHTML = `
            <div class="mo-title">${moName}</div>
            <div class="mo-category">${mo.category || 'Other'}</div>
        `;

        const moContent = document.createElement('div');
        moContent.className = 'mo-content';

        let paramsHTML = '';
        if (mo.parameters && mo.parameters.length > 0) {
            paramsHTML = '<div class="param-list">';
            mo.parameters.forEach(param => {
                paramsHTML += `
                    <div class="param-item">
                        <div class="param-name">${param.name || param}</div>
                        <div class="param-desc">${param.description || 'No description available'}</div>
                    </div>
                `;
            });
            paramsHTML += '</div>';
        }

        moContent.innerHTML = `
            <div class="mo-description">${mo.description || 'No description available'}</div>
            ${paramsHTML}
        `;

        moItem.appendChild(moHeader);
        moItem.appendChild(moContent);
        moList.appendChild(moItem);
    });
}

function toggleMO(moItem) {
    const content = moItem.querySelector('.mo-content');
    content.classList.toggle('active');
}

function filterMOs() {
    const searchTerm = document.getElementById('search-input').value.toLowerCase();
    const categoryFilter = document.getElementById('category-filter').value;
    const techFilter = document.getElementById('technology-filter').value;

    const filtered = {};

    Object.keys(allMOData).forEach(moName => {
        const mo = allMOData[moName];

        const matchesSearch = !searchTerm ||
            moName.toLowerCase().includes(searchTerm) ||
            (mo.description && mo.description.toLowerCase().includes(searchTerm)) ||
            (mo.parameters && mo.parameters.some(p =>
                (typeof p === 'string' && p.toLowerCase().includes(searchTerm)) ||
                (p.name && p.name.toLowerCase().includes(searchTerm))
            ));

        const matchesCategory = !categoryFilter || mo.category === categoryFilter;
        const matchesTech = !techFilter || moName.includes(techFilter);

        if (matchesSearch && matchesCategory && matchesTech) {
            filtered[moName] = mo;
        }
    });

    displayMOs(filtered);
}

function updateStats() {
    const totalMOs = Object.keys(allMOData).length;
    let totalParams = 0;

    Object.values(allMOData).forEach(mo => {
        if (mo.parameters) {
            totalParams += mo.parameters.length;
        }
    });

    document.getElementById('total-mos').textContent = totalMOs;
    document.getElementById('total-params').textContent = totalParams;
}
