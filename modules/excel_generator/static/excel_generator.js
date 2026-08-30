/**
 * Excel Generator Page JavaScript
 */

let uploadedFileId = null;
let moClasses = [];

// Step 1: Upload Excel and discover MO classes
document.getElementById('upload-form').addEventListener('submit', async (e) => {
    e.preventDefault();

    const fileInput = document.getElementById('excel-file');
    const file = fileInput.files[0];

    if (!file) {
        showNotification('Please select a file', 'error');
        return;
    }

    document.querySelector('.file-text').textContent = file.name;

    const formData = new FormData();
    formData.append('file', file);

    const statusDiv = document.getElementById('upload-status');
    statusDiv.innerHTML = '<div class="loading-spinner"></div>';
    statusDiv.className = 'status-message';
    statusDiv.style.display = 'block';

    try {
        const response = await fetch('/api/excel-generator/upload', {
            method: 'POST',
            body: formData
        });

        const data = await response.json();

        if (data.success) {
            statusDiv.textContent = 'File uploaded successfully!';
            statusDiv.className = 'status-message success';

            // Store file ID and MO classes
            uploadedFileId = data.file_id;
            moClasses = data.mo_classes;

            // Show operations section
            displayOperations(moClasses);
            document.getElementById('operations-section').style.display = 'block';

            showNotification('File uploaded! Select operations for each MO.', 'success');
        } else {
            statusDiv.textContent = `Error: ${data.error}`;
            statusDiv.className = 'status-message error';
            showNotification(data.error, 'error');
        }
    } catch (error) {
        statusDiv.textContent = `Error: ${error.message}`;
        statusDiv.className = 'status-message error';
        showNotification('Upload failed', 'error');
    }
});

function displayOperations(moClasses) {
    const operationsList = document.getElementById('operations-list');
    operationsList.innerHTML = '';

    moClasses.forEach(moClass => {
        const item = document.createElement('div');
        item.className = 'operation-item';

        item.innerHTML = `
            <div class="mo-name">${moClass}</div>
            <div class="operation-selector">
                <label>
                    <input type="radio" name="op_${moClass}" value="create">
                    <span>Create</span>
                </label>
                <label>
                    <input type="radio" name="op_${moClass}" value="update" checked>
                    <span>Update</span>
                </label>
                <label>
                    <input type="radio" name="op_${moClass}" value="delete">
                    <span>Delete</span>
                </label>
            </div>
        `;

        operationsList.appendChild(item);
    });
}

// Step 2: Generate XML with selected operations
async function generateXML() {
    if (!uploadedFileId) {
        showNotification('Please upload a file first', 'error');
        return;
    }

    // Collect selected operations
    const operations = {};
    moClasses.forEach(moClass => {
        const selected = document.querySelector(`input[name="op_${moClass}"]:checked`);
        operations[moClass] = selected ? selected.value : 'update';
    });

    const statusDiv = document.getElementById('upload-status');
    statusDiv.innerHTML = '<div class="loading-spinner"></div>';
    statusDiv.className = 'status-message';
    statusDiv.style.display = 'block';

    try {
        const response = await fetch('/api/excel-generator/convert', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                file_id: uploadedFileId,
                operations: operations
            })
        });

        const data = await response.json();

        if (data.success) {
            statusDiv.textContent = 'XML generated successfully!';
            statusDiv.className = 'status-message success';

            document.getElementById('operations-section').style.display = 'none';
            document.getElementById('results-section').style.display = 'block';
            document.getElementById('results-message').textContent =
                `Successfully converted Excel to XML: ${data.output_file}`;

            window.downloadFilename = data.output_file;
            renderValidation(data.validation);

            showNotification('Conversion complete!', 'success');
        } else {
            statusDiv.textContent = `Error: ${data.error}`;
            statusDiv.className = 'status-message error';
            showNotification(data.error, 'error');
        }
    } catch (error) {
        statusDiv.textContent = `Error: ${error.message}`;
        statusDiv.className = 'status-message error';
        showNotification('Conversion failed', 'error');
    }
}

async function downloadFile() {
    if (!window.downloadFilename) {
        showNotification('No file available for download', 'error');
        return;
    }

    try {
        const response = await fetch(`/api/excel-generator/download/${window.downloadFilename}`);

        if (response.ok) {
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = window.downloadFilename;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            a.remove();

            showNotification('Download started', 'success');
        } else {
            showNotification('Download failed', 'error');
        }
    } catch (error) {
        showNotification('Download error: ' + error.message, 'error');
    }
}

function renderValidation(payload) {
    const host = document.getElementById('validation-section');
    const summaryEl = document.getElementById('validation-summary');
    const listEl = document.getElementById('validation-list');
    if (!host || !summaryEl || !listEl) return;
    if (!payload) {
        host.hidden = true;
        return;
    }
    const summary = payload.summary || {};
    const findings = Array.isArray(payload.findings) ? payload.findings : [];
    host.hidden = false;
    summaryEl.textContent = `${payload.mo_count || 0} MOs · ${summary.errors || 0} errors · ${summary.warnings || 0} warnings · ${summary.diffs || 0} diffs vs current network snapshot`;
    if (!payload.snapshot_available) {
        summaryEl.textContent += ' (no snapshot loaded — generate after a CM extract for a dry-run diff)';
    }
    if (!findings.length) {
        listEl.innerHTML = '<p class="validation-ok">Plan passed dictionary / golden-rule checks.</p>';
        return;
    }
    listEl.innerHTML = findings.slice(0, 80).map((item) => {
        const cls = item.severity === 'error' ? 'is-error' : (item.severity === 'warning' ? 'is-warning' : 'is-info');
        const text = String(item.message || '').replace(/&/g, '&amp;').replace(/</g, '&lt;');
        return `<div class="validation-item ${cls}"><strong>${item.severity || ''}</strong> ${text}</div>`;
    }).join('');
}

