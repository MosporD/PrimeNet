let allSites = [];
let currentSite = null;

window.addEventListener('DOMContentLoaded', () => {
    loadSummary();
    loadConflicts();
    loadSites();
});

function openTab(name, btn) {
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.add('hidden'));
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.getElementById('tab-' + name).classList.remove('hidden');
    btn.classList.add('active');
}

// ── Summary ───────────────────────────────────────────────────────────────────
async function loadSummary() {
    const res = await fetch('/api/network-management/summary');
    const data = await res.json();
    if (!data.success) return;
    document.getElementById('statSites').textContent = data.site_count.toLocaleString();
    document.getElementById('statCells').textContent = data.cell_count.toLocaleString();
    document.getElementById('statTechs').textContent = data.by_technology.length;
}

// ── Conflicts ─────────────────────────────────────────────────────────────────
async function loadConflicts() {
    const tech  = document.getElementById('conflictTech').value;
    const scope = document.getElementById('conflictScope').value;
    const container = document.getElementById('conflictsContainer');
    container.innerHTML = '<div class="loading-spinner"></div>';

    const res  = await fetch(`/api/network-management/pci-conflicts?technology=${tech}&scope=${scope}`);
    const data = await res.json();
    if (!data.success) { container.innerHTML = '<p>Failed to load conflicts</p>'; return; }

    document.getElementById('statConflicts').textContent = data.conflicts.length;
    document.getElementById('conflictsSummary').textContent =
        `${data.conflicts.length} conflict group${data.conflicts.length !== 1 ? 's' : ''} across ${data.total_cells} cells`;

    if (!data.conflicts.length) {
        container.innerHTML = `
            <div class="no-conflicts">
                <div class="check-icon">✅</div>
                <p>No PCI conflicts detected${tech ? ' for ' + tech : ''}!</p>
            </div>`;
        return;
    }

    container.innerHTML = data.conflicts.map((g, i) => `
        <div class="conflict-group">
            <div class="conflict-header" onclick="toggleConflict(${i})">
                <div class="pci-badge">PCI ${g.pci}</div>
                <div class="conflict-meta">
                    <div class="c-title">${g.cell_count} cells · ${g.site_count} sites — ${g.scope_label}</div>
                    <div class="c-sub">${g.technology} · ${g.cells[0]?.vendor || ''}</div>
                </div>
                <span class="conflict-expand" id="expand-${i}">▶</span>
            </div>
            <div class="conflict-cells" id="cells-${i}">
                <table class="cell-table">
                    <thead><tr>
                        <th>Cell Name</th><th>Site</th><th>Technology</th>
                        <th>Azimuth</th><th>Band</th><th>Area</th>
                    </tr></thead>
                    <tbody>
                        ${g.cells.map(c => `
                        <tr>
                            <td>${c.cell_name}</td>
                            <td>${c.site_name || c.site_id}</td>
                            <td>${c.technology}</td>
                            <td>${c.azimuth != null ? c.azimuth + '°' : '—'}</td>
                            <td>${c.frequency_band || '—'}</td>
                            <td>${c.area || '—'}</td>
                        </tr>`).join('')}
                    </tbody>
                </table>
            </div>
        </div>
    `).join('');
}

function toggleConflict(i) {
    const cells   = document.getElementById(`cells-${i}`);
    const expand  = document.getElementById(`expand-${i}`);
    const isOpen  = cells.classList.contains('open');
    cells.classList.toggle('open', !isOpen);
    expand.classList.toggle('open', !isOpen);
}

// ── Site Browser ──────────────────────────────────────────────────────────────
async function loadSites() {
    const vendor = document.getElementById('browserVendor').value;
    const list = document.getElementById('siteList');
    list.innerHTML = '<div class="loading-spinner"></div>';

    const res  = await fetch(`/api/network-management/sites?vendor=${vendor}`);
    const data = await res.json();
    allSites   = data.sites || [];
    renderSites(allSites);
}

function filterSites() {
    const q = document.getElementById('siteSearch').value.toLowerCase();
    renderSites(allSites.filter(s => s.site_name.toLowerCase().includes(q) || String(s.site_id).includes(q)));
}

function renderSites(sites) {
    const list = document.getElementById('siteList');
    if (!sites.length) {
        list.innerHTML = '<p style="color:#bbb;padding:20px;text-align:center">No sites found</p>';
        return;
    }
    list.innerHTML = sites.map(s => `
        <div class="site-item ${currentSite === s.site_id ? 'active' : ''}" onclick="selectSite('${s.site_id}', '${s.site_name}')">
            <div class="site-name">${s.site_name}</div>
            <div class="site-meta">${s.vendor} · ${s.cell_count} cell${s.cell_count !== 1 ? 's' : ''} · ${s.area}</div>
        </div>
    `).join('');
}

async function selectSite(siteId, siteName) {
    currentSite = siteId;
    filterSites();

    const panel = document.getElementById('cellPanel');
    panel.innerHTML = '<div class="loading-spinner"></div>';

    const res  = await fetch(`/api/network-management/site/${siteId}/cells`);
    const data = await res.json();
    const cells = data.cells || [];

    if (!cells.length) {
        panel.innerHTML = '<p class="placeholder-text">No active cells for this site</p>';
        return;
    }

    const techClass = tech => {
        const t = (tech || '').replace(/[^a-zA-Z0-9-]/g,'');
        return `tech-${t}`;
    };

    panel.innerHTML = `
        <div class="site-header">
            <h3>${siteName}</h3>
            <p>Site ID: ${siteId} &nbsp;·&nbsp; ${cells.length} cell${cells.length !== 1 ? 's' : ''}</p>
        </div>
        <div class="cell-cards">
            ${cells.map(c => `
            <div class="cell-card">
                <div class="cell-card-header">
                    <span class="tech-badge ${techClass(c.technology)}">${c.technology}</span>
                    <span class="cell-card-name">${c.cell_name}</span>
                </div>
                <div class="cell-params">
                    <div class="param-item"><span class="param-label">PCI: </span><span class="param-value">${c.pci ?? '—'}</span></div>
                    <div class="param-item"><span class="param-label">Azimuth: </span><span class="param-value">${c.azimuth != null ? c.azimuth + '°' : '—'}</span></div>
                    <div class="param-item"><span class="param-label">Band: </span><span class="param-value">${c.frequency_band || '—'}</span></div>
                    <div class="param-item"><span class="param-label">e-Tilt: </span><span class="param-value">${c.electrical_tilt ?? '—'}</span></div>
                    <div class="param-item"><span class="param-label">m-Tilt: </span><span class="param-value">${c.mechanical_tilt ?? '—'}</span></div>
                    <div class="param-item"><span class="param-label">Vendor: </span><span class="param-value">${c.vendor || '—'}</span></div>
                </div>
            </div>
            `).join('')}
        </div>`;
}
