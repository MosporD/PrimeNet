const REPORT_META = {
    site_inventory:  { icon: '🏗️', desc: 'Sites and cells with location, azimuth, PCI, tilt, and band. Opens settings for technology scope.' },
    pci_conflicts:   { icon: '⚠️', desc: 'PCI/PSC/BCCH conflicts. Opens settings: optional max distance (km) and azimuth window (1–180°, both sides).' },
    config_versions: { icon: '📋', desc: 'Full log of all XML configuration versions uploaded to the version history module.' },
    sector_health:   { icon: '📡', desc: 'Per-sector FDD layer matrix. Opens settings: Active only or All cells (Active/Inactive).' },
};

const REPORT_TYPE_LABELS = {
    sector_health: 'Sector Health',
    sector_health_all: 'Sector Health (All Cells)',
    sector_coverage: 'Sector Health',
    pci_conflicts: 'Conflict Report',
    site_inventory: 'Site Inventory',
};

/** Cards that open a settings panel before generate. */
const SETTINGS_REPORTS = {
    site_inventory: { title: 'Site Inventory settings' },
    pci_conflicts: { title: 'Conflict Report settings' },
    sector_health: { title: 'Sector Health settings' },
};

let activeSettingsType = null;

function reportTypeLabel(typeId) {
    return REPORT_TYPE_LABELS[typeId] || typeId;
}

function esc(v) {
    return String(v ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function escJs(v) {
    return String(v ?? '').replace(/\\/g, '\\\\').replace(/'/g, "\\'");
}

window.addEventListener('DOMContentLoaded', () => {
    loadReportTypes();
    loadArchive();
    const pciTech = document.getElementById('pci-conflict-tech');
    if (pciTech) {
        pciTech.addEventListener('change', syncPciConflictModeVisibility);
        syncPciConflictModeVisibility();
    }
    const genBtn = document.getElementById('report-settings-generate');
    const cancelBtn = document.getElementById('report-settings-cancel');
    if (genBtn) genBtn.addEventListener('click', () => generateFromOpenSettings());
    if (cancelBtn) cancelBtn.addEventListener('click', () => closeReportSettings());
});

function syncPciConflictModeVisibility() {
    const tech = document.getElementById('pci-conflict-tech')?.value || '';
    const modeEl = document.getElementById('pci-conflict-mode');
    const modeLabel = document.getElementById('pci-conflict-mode-label');
    const is2g = tech === '2G';
    if (modeEl) {
        modeEl.style.display = is2g ? '' : 'none';
        modeEl.disabled = !is2g;
    }
    if (modeLabel) modeLabel.style.display = is2g ? '' : 'none';
}

function openReportSettings(type) {
    const shell = document.getElementById('report-settings');
    const titleEl = document.getElementById('report-settings-title');
    if (!shell || !SETTINGS_REPORTS[type]) return;

    activeSettingsType = type;
    shell.hidden = false;
    if (titleEl) titleEl.textContent = SETTINGS_REPORTS[type].title;

    document.querySelectorAll('.report-settings-panel').forEach((panel) => {
        panel.hidden = panel.id !== `settings-panel-${type}`;
    });
    document.querySelectorAll('.report-card').forEach((el) => {
        el.classList.toggle('selected', el.id === `card-${type}`);
    });
    if (type === 'pci_conflicts') syncPciConflictModeVisibility();
    shell.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function closeReportSettings() {
    activeSettingsType = null;
    const shell = document.getElementById('report-settings');
    if (shell) shell.hidden = true;
    document.querySelectorAll('.report-settings-panel').forEach((panel) => {
        panel.hidden = true;
    });
    document.querySelectorAll('.report-card').forEach((el) => el.classList.remove('selected'));
}

function onReportCardClick(type, label) {
    if (SETTINGS_REPORTS[type]) {
        openReportSettings(type);
        return;
    }
    closeReportSettings();
    generateReport(type, label);
}

async function loadReportTypes() {
    const res  = await fetch('/api/reports/types');
    const data = await res.json();
    if (!data.success) return;

    const container = document.getElementById('reportCards');
    container.innerHTML = data.types.map(t => {
        const meta = REPORT_META[t.id] || { icon: '📊', desc: '' };
        const id = escJs(t.id);
        const label = escJs(t.label);
        const selected = activeSettingsType === t.id ? ' selected' : '';
        return `
        <div class="report-card${selected}" id="card-${id}" onclick="onReportCardClick('${id}', '${label}')">
            <div class="report-icon">${meta.icon}</div>
            <div class="report-title">${esc(t.label)}</div>
            <div class="report-desc">${esc(meta.desc)}</div>
        </div>`;
    }).join('');
}

async function downloadReportArchive(archiveId, filename) {
    const res = await fetch(`/api/reports/download/${archiveId}`, { credentials: 'same-origin' });
    if (!res.ok) {
        throw new Error(`Download failed (${res.status})`);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename || `report_${archiveId}.xlsx`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
}

function readSettingsPayloadOrError(type) {
    if (type === 'site_inventory') {
        const tech = document.getElementById('site-inventory-tech')?.value || 'all';
        return {
            payload: { report_type: 'site_inventory', technology: tech },
            label: 'Site Inventory',
        };
    }

    if (type === 'sector_health') {
        const scope = document.getElementById('sector-health-scope')?.value || 'active';
        const report_type = scope === 'all' ? 'sector_health_all' : 'sector_health';
        const label = scope === 'all' ? 'Sector Health (All Cells)' : 'Sector Health';
        return { payload: { report_type }, label };
    }

    if (type === 'pci_conflicts') {
        const tech = document.getElementById('pci-conflict-tech')?.value || '4G';
        const mode = document.getElementById('pci-conflict-mode')?.value || 'both';
        const distRaw = (document.getElementById('pci-conflict-distance')?.value || '').trim();
        const azRaw = (document.getElementById('pci-conflict-azimuth')?.value || '').trim();

        let distance_km = null;
        let azimuth_deg = null;

        if (distRaw !== '') {
            const d = Number(distRaw);
            if (!Number.isFinite(d) || d <= 0) {
                return { error: 'Distance must be a number greater than 0 km (or leave empty).' };
            }
            if (d > 5000) {
                return { error: 'Distance must be at most 5000 km.' };
            }
            distance_km = d;
        }

        if (azRaw !== '') {
            const a = Number(azRaw);
            if (!Number.isFinite(a) || a < 1 || a > 180) {
                return { error: 'Azimuth must be between 1 and 180 (or leave empty).' };
            }
            azimuth_deg = a;
        }

        const payload = {
            report_type: 'pci_conflicts',
            technology: tech,
            distance_km,
            azimuth_deg,
        };
        if (tech === '2G') payload.conflict_mode = mode;
        return { payload, label: 'Conflict Report' };
    }

    return { error: 'Unknown settings report.' };
}

async function generateFromOpenSettings() {
    const statusEl = document.getElementById('generateStatus');
    if (!activeSettingsType) {
        if (statusEl) {
            statusEl.className = 'status-message error';
            statusEl.textContent = 'Select a report card first.';
        }
        return;
    }
    const parsed = readSettingsPayloadOrError(activeSettingsType);
    if (parsed.error) {
        if (statusEl) {
            statusEl.className = 'status-message error';
            statusEl.textContent = parsed.error;
        }
        return;
    }
    const cardType = activeSettingsType;
    await generateReport(cardType, parsed.label, parsed.payload);
}

async function generateReport(type, label, presetPayload) {
    const card = document.getElementById('card-' + type);
    if (card) {
        card.classList.add('generating');
        card.innerHTML += `<div class="report-gen-overlay"><span class="loading-spinner" style="width:22px;height:22px;border-width:3px"></span> Generating…</div>`;
    }

    const statusEl = document.getElementById('generateStatus');
    statusEl.className = 'status-message info';
    statusEl.textContent = `Generating ${label}…`;

    const genBtn = document.getElementById('report-settings-generate');
    if (genBtn) genBtn.disabled = true;

    try {
        const payload = presetPayload || { report_type: type };

        const res  = await fetch('/api/reports/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await res.json();

        if (data.success) {
            statusEl.className = 'status-message success';
            statusEl.textContent = `✓ ${label} generated (${data.rows.toLocaleString()} rows). Downloading…`;
            await downloadReportArchive(data.archive_id, data.filename);
            loadArchive();
        } else {
            statusEl.className = 'status-message error';
            statusEl.textContent = data.error || 'Report generation failed';
        }
    } catch (e) {
        statusEl.className = 'status-message error';
        statusEl.textContent = 'Network error. Please try again.';
    }

    if (card) card.classList.remove('generating');
    if (genBtn) genBtn.disabled = false;
    loadReportTypes();
}

async function loadArchive() {
    const container = document.getElementById('archiveContainer');
    const res  = await fetch('/api/reports/archive');
    const data = await res.json();
    const reports = data.reports || [];

    if (!reports.length) {
        container.innerHTML = '<div class="empty-archive">No reports generated yet. Click a report card above to generate one.</div>';
        return;
    }

    container.innerHTML = `
    <div class="archive-table-wrapper">
        <table class="archive-table">
            <thead><tr>
                <th>Report Name</th>
                <th>Type</th>
                <th>Size</th>
                <th>Generated At</th>
                <th>Generated By</th>
                <th>Actions</th>
            </tr></thead>
            <tbody>
                ${reports.map(r => `
                <tr>
                    <td>${esc(r.report_name)}</td>
                    <td><span class="type-badge">${esc(reportTypeLabel(r.report_type))}</span></td>
                    <td>${formatSize(r.file_size)}</td>
                    <td>${esc(r.generated_at ? r.generated_at.slice(0,16) : '—')}</td>
                    <td>${esc(r.generated_by_name || '—')}</td>
                    <td style="white-space:nowrap">
                        <button class="btn-dl" onclick="downloadReport(${r.id})">⬇ Download</button>
                        <button class="btn-rm" onclick="deleteReport(${r.id})">🗑 Delete</button>
                    </td>
                </tr>`).join('')}
            </tbody>
        </table>
    </div>`;
}

function downloadReport(id) {
    window.location.href = `/api/reports/download/${id}`;
}

async function deleteReport(id) {
    if (!confirm('Remove this report from the archive?')) return;
    const res  = await fetch(`/api/reports/archive/${id}`, { method: 'DELETE' });
    const data = await res.json();
    if (data.success) loadArchive();
}

function formatSize(bytes) {
    if (!bytes) return '—';
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1048576).toFixed(1) + ' MB';
}
