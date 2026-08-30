/**
 * XML Parser Page JavaScript
 */

let uploadedFile = null;
let availableParameters = [];
let selectedParameters = new Set();

// Handle file upload form
document.getElementById('upload-form').addEventListener('submit', async (e) => {
    e.preventDefault();

    const fileInput = document.getElementById('xml-file');
    const file = fileInput.files[0];

    if (!file) {
        showNotification('Please select a file', 'error');
        return;
    }

    // Update file label
    document.querySelector('.file-text').textContent = file.name;

    const formData = new FormData();
    formData.append('file', file);

    const statusDiv = document.getElementById('upload-status');
    statusDiv.innerHTML = '<div class="loading-spinner"></div>';
    statusDiv.className = 'status-message';
    statusDiv.style.display = 'block';

    try {
        const response = await fetch('/api/xml-parser/upload', {
            method: 'POST',
            body: formData
        });

        const data = await response.json();

        if (data.success) {
            uploadedFile = data.file_id;
            availableParameters = data.parameters || [];

            statusDiv.textContent = `File uploaded successfully! Found ${availableParameters.length} parameters.`;
            statusDiv.className = 'status-message success';

            // Show filter section
            document.getElementById('filter-section').style.display = 'block';
            loadParameters();
            renderValidation(data.validation);

            showNotification('File uploaded successfully!', 'success');
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

// Load and display parameters
function loadParameters() {
    const paramsList = document.getElementById('parameters-list');
    paramsList.innerHTML = '';

    if (availableParameters.length === 0) {
        paramsList.innerHTML = '<p style="text-align: center; color: #7f8c8d;">No parameters found</p>';
        return;
    }

    availableParameters.forEach(param => {
        const paramDiv = document.createElement('div');
        paramDiv.className = 'param-item';

        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.id = `param-${param}`;
        checkbox.value = param;
        checkbox.checked = true;
        selectedParameters.add(param);

        checkbox.addEventListener('change', (e) => {
            if (e.target.checked) {
                selectedParameters.add(param);
            } else {
                selectedParameters.delete(param);
            }
        });

        const label = document.createElement('label');
        label.htmlFor = `param-${param}`;
        label.textContent = param;

        paramDiv.appendChild(checkbox);
        paramDiv.appendChild(label);
        paramsList.appendChild(paramDiv);
    });

    // Setup search
    setupParameterSearch();
}

// Setup parameter search
function setupParameterSearch() {
    const searchInput = document.getElementById('param-search');
    searchInput.addEventListener('input', (e) => {
        const searchTerm = e.target.value.toLowerCase();
        const paramItems = document.querySelectorAll('.param-item');

        paramItems.forEach(item => {
            const label = item.querySelector('label');
            if (label.textContent.toLowerCase().includes(searchTerm)) {
                item.style.display = 'flex';
            } else {
                item.style.display = 'none';
            }
        });
    });
}

// Select all parameters
function selectAllParams() {
    const checkboxes = document.querySelectorAll('#parameters-list input[type="checkbox"]');
    checkboxes.forEach(checkbox => {
        checkbox.checked = true;
        selectedParameters.add(checkbox.value);
    });
    showNotification('All parameters selected', 'success');
}

// Deselect all parameters
function deselectAllParams() {
    const checkboxes = document.querySelectorAll('#parameters-list input[type="checkbox"]');
    checkboxes.forEach(checkbox => {
        checkbox.checked = false;
    });
    selectedParameters.clear();
    showNotification('All parameters deselected', 'info');
}

// Generate Excel with selected parameters
async function generateExcel() {
    if (!uploadedFile) {
        showNotification('No file uploaded', 'error');
        return;
    }

    const params = Array.from(selectedParameters);

    if (params.length === 0) {
        if (!confirm('No parameters selected. Generate empty Excel file?')) {
            return;
        }
    }

    try {
        const response = await fetch('/api/xml-parser/convert', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                file_id: uploadedFile,
                selected_parameters: params
            })
        });

        const data = await response.json();

        if (data.success) {
            showResults(data.output_file, params.length);
        } else {
            showNotification(data.error, 'error');
        }
    } catch (error) {
        showNotification('Conversion failed: ' + error.message, 'error');
    }
}

// Skip filter and convert all parameters
async function skipFilter() {
    if (!uploadedFile) {
        showNotification('No file uploaded', 'error');
        return;
    }

    try {
        const response = await fetch('/api/xml-parser/convert', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                file_id: uploadedFile,
                selected_parameters: []  // Empty means all
            })
        });

        const data = await response.json();

        if (data.success) {
            showResults(data.output_file, availableParameters.length);
        } else {
            showNotification(data.error, 'error');
        }
    } catch (error) {
        showNotification('Conversion failed: ' + error.message, 'error');
    }
}

// Show results section
function showResults(filename, paramCount) {
    document.getElementById('filter-section').style.display = 'none';
    const resultsSection = document.getElementById('results-section');
    resultsSection.style.display = 'block';

    const message = document.getElementById('results-message');
    message.textContent = `Successfully converted XML to Excel with ${paramCount} parameters.`;

    // Store filename for download
    window.downloadFilename = filename;

    showNotification('Conversion complete!', 'success');
}

// Download the generated file
async function downloadFile() {
    if (!window.downloadFilename) {
        showNotification('No file available for download', 'error');
        return;
    }

    try {
        const response = await fetch(`/api/xml-parser/download/${window.downloadFilename}`);

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

// Save filter profile
async function saveFilterProfile() {
    if (selectedParameters.size === 0) {
        showNotification('No parameters selected to save', 'error');
        return;
    }

    const profileName = prompt('Enter profile name:');
    if (!profileName) return;

    try {
        const response = await fetch('/api/profiles/save', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                profile_name: profileName,
                selected_params: Array.from(selectedParameters)
            })
        });

        const data = await response.json();

        if (data.success) {
            showNotification('Profile saved successfully', 'success');
        } else {
            showNotification(data.error, 'error');
        }
    } catch (error) {
        showNotification('Failed to save profile', 'error');
    }
}

// Load filter profile
async function loadFilterProfile() {
    try {
        const response = await fetch('/api/profiles/list');
        const data = await response.json();

        if (data.success && data.profiles.length > 0) {
            const profileOptions = data.profiles.map(p => p.name).join('\n');
            const profileName = prompt(`Available profiles:\n${profileOptions}\n\nEnter profile name to load:`);

            if (!profileName) return;

            const profile = data.profiles.find(p => p.name === profileName);
            if (profile) {
                // Deselect all first
                deselectAllParams();

                // Select profile parameters
                profile.parameters.forEach(param => {
                    const checkbox = document.getElementById(`param-${param}`);
                    if (checkbox) {
                        checkbox.checked = true;
                        selectedParameters.add(param);
                    }
                });

                showNotification(`Profile "${profileName}" loaded`, 'success');
            } else {
                showNotification('Profile not found', 'error');
            }
        } else {
            showNotification('No saved profiles found', 'info');
        }
    } catch (error) {
        showNotification('Failed to load profiles', 'error');
    }
}

function renderValidation(payload) {
    const host = document.getElementById('validation-section');
    const summaryEl = document.getElementById('validation-summary');
    const listEl = document.getElementById('validation-list');
    if (!host || !summaryEl || !listEl) return;
    if (!payload) {
        host.style.display = 'none';
        return;
    }
    const summary = payload.summary || {};
    const findings = Array.isArray(payload.findings) ? payload.findings : [];
    const errors = summary.errors || 0;
    const warnings = summary.warnings || 0;
    const diffs = summary.diffs || 0;
    host.style.display = 'block';
    summaryEl.textContent = `${payload.mo_count || 0} MOs · ${errors} errors · ${warnings} warnings · ${diffs} diffs vs network snapshot`;
    if (!payload.dictionary_available) {
        summaryEl.textContent += ' · dictionary not loaded';
    }
    if (!payload.snapshot_available) {
        summaryEl.textContent += ' · no CM snapshot for dry-run diff';
    }
    if (!findings.length) {
        listEl.innerHTML = '<p class="validation-ok">No MO / golden-rule issues found.</p>';
        return;
    }
    listEl.innerHTML = findings.slice(0, 80).map((item) => {
        const cls = item.severity === 'error' ? 'is-error' : (item.severity === 'warning' ? 'is-warning' : 'is-info');
        return `<div class="validation-item ${cls}"><strong>${escapeXml(item.severity || '')}</strong> ${escapeXml(item.message || '')}</div>`;
    }).join('');
}

function escapeXml(value) {
    return String(value || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

