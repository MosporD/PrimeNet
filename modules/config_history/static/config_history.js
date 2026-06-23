let allNEs = [];
let currentNE = null;
let currentVersions = [];
let selectedForDiff = [];

function escHtml(v) {
    return String(v ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

// ── Init ──────────────────────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', () => {
    loadNEList();
    // drag-drop
    const area = document.getElementById('uploadArea');
    area.addEventListener('dragover', e => { e.preventDefault(); area.style.background = '#eaf4fd'; });
    area.addEventListener('dragleave', () => { area.style.background = ''; });
    area.addEventListener('drop', e => { e.preventDefault(); area.style.background = ''; handleDrop(e); });
});

// ── NE List ───────────────────────────────────────────────────────────────────
async function loadNEList() {
    const res = await fetch('/api/config-history/list');
    const data = await res.json();
    allNEs = data.nes || [];
    renderNEs(allNEs);
}

function renderNEs(nes) {
    const list = document.getElementById('neList');
    if (!nes.length) {
        list.innerHTML = '<p class="placeholder-text">No configurations uploaded yet</p>';
        return;
    }
    list.innerHTML = nes.map(ne => `
        <div class="ne-item ${currentNE === ne.ne_name ? 'active' : ''}" onclick="selectNE('${encodeURIComponent(ne.ne_name)}')">
            <span class="ne-name">${escHtml(ne.ne_name)}</span>
            <span class="ne-meta">
                ${escHtml(ne.version_count)} version${ne.version_count !== 1 ? 's' : ''}<br>
                ${escHtml(ne.last_updated ? ne.last_updated.slice(0, 10) : '')}
            </span>
        </div>
    `).join('');
}

function filterNEs() {
    const q = document.getElementById('neSearch').value.toLowerCase();
    renderNEs(allNEs.filter(ne => ne.ne_name.toLowerCase().includes(q)));
}

// ── Version List ──────────────────────────────────────────────────────────────
async function selectNE(neNameEncoded) {
    const neName = decodeURIComponent(neNameEncoded);
    currentNE = neName;
    selectedForDiff = [];
    document.getElementById('versionsTitle').textContent = `Versions — ${neName}`;
    document.getElementById('compareBtn').style.display = 'none';
    renderNEs(allNEs.filter(ne =>
        ne.ne_name.toLowerCase().includes(document.getElementById('neSearch').value.toLowerCase())
    ));

    const vList = document.getElementById('versionsList');
    vList.innerHTML = '<div class="loading-spinner"></div>';

    const res = await fetch(`/api/config-history/${encodeURIComponent(neName)}/versions`);
    const data = await res.json();
    currentVersions = data.versions || [];
    renderVersions();
}

function renderVersions() {
    const vList = document.getElementById('versionsList');
    if (!currentVersions.length) {
        vList.innerHTML = '<p class="placeholder-text">No versions found</p>';
        return;
    }
    vList.innerHTML = currentVersions.map(v => {
        const isSelected = selectedForDiff.includes(v.id);
        const sizeKB = (v.content_length / 1024).toFixed(1);
        return `
        <div class="version-card ${isSelected ? 'selected' : ''}" id="vcard-${v.id}">
            <span class="version-badge">v${v.version_num}</span>
            <div class="version-info">
                <div class="v-date">${escHtml(v.created_at ? v.created_at.slice(0, 16) : '')} &nbsp;·&nbsp; ${escHtml(sizeKB)} KB</div>
                <div class="v-comment">${v.comment ? escHtml(v.comment) : '<em style="color:#bbb">No comment</em>'}</div>
                <div class="v-user">by ${escHtml(v.uploaded_by_name || 'Unknown')}</div>
            </div>
            <div class="version-actions">
                <button class="btn-select ${isSelected ? 'active-sel' : ''}" onclick="toggleDiffSelect(${Number(v.id)})" title="Select for diff">
                    ${isSelected ? '✓' : 'Diff'}
                </button>
                <button class="btn-download" onclick="downloadVersion(${Number(v.id)})" title="Download">⬇</button>
                <button class="btn-delete" onclick="deleteVersion(${Number(v.id)})" title="Delete">🗑</button>
            </div>
        </div>`;
    }).join('');
}

// ── Diff selection ────────────────────────────────────────────────────────────
function toggleDiffSelect(id) {
    if (selectedForDiff.includes(id)) {
        selectedForDiff = selectedForDiff.filter(x => x !== id);
    } else {
        if (selectedForDiff.length >= 2) selectedForDiff.shift();
        selectedForDiff.push(id);
    }
    renderVersions();
    document.getElementById('compareBtn').style.display = selectedForDiff.length === 2 ? 'inline-block' : 'none';
}

// ── Diff Modal ────────────────────────────────────────────────────────────────
function openDiff() {
    const modal = document.getElementById('diffModal');
    modal.style.display = 'flex';

    // Populate dropdowns
    const opts = currentVersions.map(v => `<option value="${v.id}">v${escHtml(v.version_num)} — ${escHtml((v.created_at||'').slice(0,10))} — ${escHtml(v.comment||'no comment')}</option>`).join('');
    document.getElementById('diffV1').innerHTML = opts;
    document.getElementById('diffV2').innerHTML = opts;

    // Pre-select the two chosen versions
    if (selectedForDiff.length === 2) {
        document.getElementById('diffV1').value = selectedForDiff[0];
        document.getElementById('diffV2').value = selectedForDiff[1];
    }
    document.getElementById('diffOutput').textContent = 'Click "Show Diff" to compare';
    document.getElementById('diffStats').innerHTML = '';
}

function closeDiff() {
    document.getElementById('diffModal').style.display = 'none';
}

async function runDiff() {
    const v1 = parseInt(document.getElementById('diffV1').value);
    const v2 = parseInt(document.getElementById('diffV2').value);
    if (v1 === v2) { alert('Select two different versions'); return; }

    document.getElementById('diffOutput').textContent = 'Computing diff…';
    document.getElementById('diffStats').innerHTML = '';

    const res = await fetch('/api/config-history/diff', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ version1_id: v1, version2_id: v2 })
    });
    const data = await res.json();
    if (!data.success) { alert(data.error || 'Diff failed'); return; }

    // Render stats
    const s = data.stats;
    document.getElementById('diffStats').innerHTML = `
        <span class="stat-badge stat-added">+${s.added} added</span>
        <span class="stat-badge stat-removed">-${s.removed} removed</span>
    `;

    // Colour-coded diff
    const pre = document.getElementById('diffOutput');
    if (!data.diff.trim()) {
        pre.innerHTML = '<span style="color:#6fdd8b">No differences — files are identical</span>';
        return;
    }
    const html = data.diff.split('\n').map(line => {
        if (line.startsWith('+++') || line.startsWith('---')) return `<span class="diff-hdr">${esc(line)}</span>`;
        if (line.startsWith('@@'))  return `<span class="diff-hdr">${esc(line)}</span>`;
        if (line.startsWith('+'))   return `<span class="diff-add">${esc(line)}</span>`;
        if (line.startsWith('-'))   return `<span class="diff-rem">${esc(line)}</span>`;
        return `<span class="diff-ctx">${esc(line)}</span>`;
    }).join('\n');
    pre.innerHTML = html;
}

function esc(s) {
    return escHtml(s);
}

// ── Upload ────────────────────────────────────────────────────────────────────
let selectedFile = null;

function handleFileSelect(input) {
    if (input.files && input.files[0]) showUploadForm(input.files[0]);
}

function handleDrop(e) {
    const file = e.dataTransfer.files[0];
    if (file) showUploadForm(file);
}

function showUploadForm(file) {
    selectedFile = file;
    document.getElementById('selectedFileName').textContent = file.name;
    document.getElementById('uploadForm').style.display = 'flex';
    document.getElementById('uploadStatus').className = 'status-message';
    document.getElementById('uploadStatus').textContent = '';
}

function cancelUpload() {
    selectedFile = null;
    document.getElementById('uploadForm').style.display = 'none';
    document.getElementById('xmlFile').value = '';
}

async function uploadVersion() {
    if (!selectedFile) return;
    const comment = document.getElementById('uploadComment').value;
    const fd = new FormData();
    fd.append('file', selectedFile);
    fd.append('comment', comment);

    const statusEl = document.getElementById('uploadStatus');
    statusEl.className = 'status-message info';
    statusEl.textContent = 'Uploading…';

    const res = await fetch('/api/config-history/upload', { method: 'POST', body: fd });
    const data = await res.json();

    if (data.success) {
        statusEl.className = 'status-message success';
        statusEl.textContent = `Saved as v${data.version_num} for ${data.ne_name}`;
        cancelUpload();
        await loadNEList();
        if (currentNE === data.ne_name) selectNE(encodeURIComponent(data.ne_name));
    } else {
        statusEl.className = 'status-message error';
        statusEl.textContent = data.error || 'Upload failed';
    }
}

// ── Actions ───────────────────────────────────────────────────────────────────
function downloadVersion(versionId) {
    window.location.href = `/api/config-history/version/${versionId}/download`;
}

async function deleteVersion(versionId) {
    if (!confirm('Delete this version? This cannot be undone.')) return;
    const res = await fetch(`/api/config-history/version/${versionId}`, { method: 'DELETE' });
    const data = await res.json();
    if (data.success) {
        await loadNEList();
        if (currentNE) selectNE(encodeURIComponent(currentNE));
    } else {
        alert(data.error || 'Delete failed');
    }
}
