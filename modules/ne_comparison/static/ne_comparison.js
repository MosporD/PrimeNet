/**
 * NE Comparison Page JavaScript
 */

const cmState = {
    neItems: [],
    moDefaults: [],
};

function $(id) {
    return document.getElementById(id);
}

function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function setStatus(id, text, type = '') {
    const el = $(id);
    if (!el) return;
    el.textContent = text;
    el.className = `status-message ${type}`.trim();
    el.style.display = text ? 'block' : 'none';
}

function selectedOptions(selectId) {
    const sel = $(selectId);
    if (!sel) return [];
    return Array.from(sel.selectedOptions).map((opt) => opt.value).filter(Boolean);
}

function selectedNe(selectId) {
    const value = $(selectId)?.value || '';
    return cmState.neItems.find((item) => item._key === value) || null;
}

function currentVendor() {
    return $('cm-vendor')?.value || 'nokia';
}

function currentScope() {
    return $('cm-scope')?.value || 'MRBTS';
}

function updateScopeOptions() {
    const vendor = currentVendor();
    const scope = $('cm-scope');
    const conf = $('cm-conf-id')?.closest('.file-group');
    if (!scope) return;
    if (vendor === 'huawei') {
        scope.innerHTML = '<option value="ENODEB">eNodeB</option>';
        if (conf) conf.style.display = 'none';
    } else {
        scope.innerHTML = `
            <option value="MRBTS">MRBTS</option>
            <option value="RNC">RNC</option>
            <option value="BSC">BSC</option>
        `;
        if (conf) conf.style.display = '';
    }
}

async function loadCmNes() {
    const vendor = currentVendor();
    const scope = currentScope();
    const q1 = $('cm-ne1-search')?.value || '';
    const q2 = $('cm-ne2-search')?.value || '';
    const query = q1 || q2 || '';
    setStatus('cm-status', 'Loading NEs...', '');
    const params = new URLSearchParams({ vendor, scope_level: scope, q: query, limit: '500' });
    const res = await fetch(`/api/ne-comparison/cm/nes?${params.toString()}`);
    const data = await res.json();
    if (!data.success) throw new Error(data.error || 'Could not load NEs');
    cmState.neItems = (data.items || []).map((item, idx) => ({
        ...item,
        _key: `${item.site_id || item.ne_name || item.u2020_ne_name || idx}`,
    }));
    renderNeSelect('cm-ne1');
    renderNeSelect('cm-ne2');
    renderAuditNeSelect();
    setStatus('cm-status', `Loaded ${cmState.neItems.length} ${scope} NEs.`, 'success');
}

function renderNeSelect(selectId) {
    const sel = $(selectId);
    if (!sel) return;
    const previous = sel.value;
    sel.innerHTML = cmState.neItems.map((item) => {
        const label = item.label || item.site_name || item.ne_name || item.site_id || 'NE';
        const meta = [item.area, item.cluster, item.cell_count ? `${item.cell_count} cells` : '']
            .filter(Boolean)
            .join(' · ');
        return `<option value="${escapeHtml(item._key)}">${escapeHtml(label)}${meta ? ` — ${escapeHtml(meta)}` : ''}</option>`;
    }).join('');
    if (previous && Array.from(sel.options).some((opt) => opt.value === previous)) {
        sel.value = previous;
    }
}

function renderAuditNeSelect() {
    const sel = $('audit-nes');
    if (!sel) return;
    const selected = new Set(Array.from(sel.selectedOptions).map((opt) => opt.value));
    sel.innerHTML = cmState.neItems.map((item) => {
        const label = item.label || item.site_name || item.ne_name || item.site_id || 'NE';
        const meta = [item.area, item.cluster, item.cell_count ? `${item.cell_count} cells` : '']
            .filter(Boolean)
            .join(' · ');
        const isSelected = selected.has(item._key) ? ' selected' : '';
        return `<option value="${escapeHtml(item._key)}"${isSelected}>${escapeHtml(label)}${meta ? ` — ${escapeHtml(meta)}` : ''}</option>`;
    }).join('');
}

async function loadCmMoClasses() {
    const vendor = currentVendor();
    const scope = currentScope();
    const sel = $('cm-mo-classes');
    if (!sel) return;
    sel.innerHTML = '<option>Loading...</option>';
    const params = new URLSearchParams({ vendor, scope_level: scope });
    const res = await fetch(`/api/ne-comparison/cm/mo-classes?${params.toString()}`);
    const data = await res.json();
    if (!data.success) throw new Error(data.error || 'Could not load MO classes');
    cmState.moDefaults = data.default_mo_classes || [];
    const defaults = new Set(cmState.moDefaults);
    sel.innerHTML = (data.items || []).map((item) => {
        const id = item.id || item.mo_id;
        const label = item.label || id;
        const group = item.group || item.technology || '';
        const selected = defaults.has(id) ? ' selected' : '';
        return `<option value="${escapeHtml(id)}"${selected}>${escapeHtml(label)}${group ? ` (${escapeHtml(group)})` : ''}</option>`;
    }).join('');
}

async function compareCmNes(e) {
    e.preventDefault();
    const ne1 = selectedNe('cm-ne1');
    const ne2 = selectedNe('cm-ne2');
    if (!ne1 || !ne2) {
        showNotification('Select two NEs to compare', 'error');
        return;
    }
    if (ne1._key === ne2._key) {
        showNotification('Select two different NEs', 'error');
        return;
    }

    const payload = {
        vendor: currentVendor(),
        scope_level: currentScope(),
        conf_id: Number($('cm-conf-id')?.value || 1),
        ne1,
        ne2,
        mo_classes: selectedOptions('cm-mo-classes'),
    };

    const btn = e.target.querySelector('button[type="submit"]');
    if (btn) btn.disabled = true;
    setStatus('cm-status', 'Pulling CM data and comparing NEs...', '');
    try {
        const res = await fetch('/api/ne-comparison/cm/compare', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (!data.success) throw new Error(data.error || 'Comparison failed');
        window.comparisonData = data;
        displayResults(data);
        setStatus('cm-status', 'CM comparison completed.', 'success');
        showNotification('CM comparison completed', 'success');
    } catch (error) {
        setStatus('cm-status', `Error: ${error.message}`, 'error');
        showNotification(error.message, 'error');
    } finally {
        if (btn) btn.disabled = false;
    }
}

function selectedAuditNes() {
    const values = new Set(selectedOptions('audit-nes'));
    return cmState.neItems.filter((item) => values.has(item._key));
}

async function runNetworkAudit(e) {
    e.preventDefault();
    const nes = selectedAuditNes();
    if (!nes.length) {
        showNotification('Select at least one NE to audit', 'error');
        return;
    }

    const payload = {
        vendor: currentVendor(),
        scope_level: currentScope(),
        conf_id: Number($('cm-conf-id')?.value || 1),
        nes,
        mo_classes: selectedOptions('cm-mo-classes'),
    };

    const btn = e.target.querySelector('button[type="submit"]');
    if (btn) btn.disabled = true;
    setStatus('audit-status', `Pulling CM data for ${nes.length} NE(s) and building parameter consistency summary...`, '');
    try {
        const res = await fetch('/api/ne-comparison/cm/audit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (!data.success) throw new Error(data.error || 'Audit failed');
        window.comparisonData = data;
        displayAuditResults(data);
        setStatus('audit-status', 'NW audit completed.', 'success');
        showNotification('NW audit completed', 'success');
    } catch (error) {
        setStatus('audit-status', `Error: ${error.message}`, 'error');
        showNotification(error.message, 'error');
    } finally {
        if (btn) btn.disabled = false;
    }
}

function bindCmWorkflow() {
    $('cm-compare-form')?.addEventListener('submit', compareCmNes);
    $('cm-audit-form')?.addEventListener('submit', runNetworkAudit);
    $('audit-select-all')?.addEventListener('click', () => {
        const sel = $('audit-nes');
        if (!sel) return;
        Array.from(sel.options).forEach((opt) => {
            opt.selected = true;
        });
    });
    $('audit-clear-selection')?.addEventListener('click', () => {
        const sel = $('audit-nes');
        if (!sel) return;
        Array.from(sel.options).forEach((opt) => {
            opt.selected = false;
        });
    });
    $('cm-vendor')?.addEventListener('change', async () => {
        updateScopeOptions();
        try {
            await Promise.all([loadCmNes(), loadCmMoClasses()]);
        } catch (error) {
            setStatus('cm-status', error.message, 'error');
        }
    });
    $('cm-scope')?.addEventListener('change', async () => {
        try {
            await Promise.all([loadCmNes(), loadCmMoClasses()]);
        } catch (error) {
            setStatus('cm-status', error.message, 'error');
        }
    });
    $('cm-ne1-search')?.addEventListener('change', () => loadCmNes().catch((err) => setStatus('cm-status', err.message, 'error')));
    $('cm-ne2-search')?.addEventListener('change', () => loadCmNes().catch((err) => setStatus('cm-status', err.message, 'error')));
}

function bindLegacyUpload() {
    $('xml-file1')?.addEventListener('change', (e) => {
        const filename = e.target.files[0]?.name || 'Choose first XML...';
        $('file1-text').textContent = filename;
    });

    $('xml-file2')?.addEventListener('change', (e) => {
        const filename = e.target.files[0]?.name || 'Choose second XML...';
        $('file2-text').textContent = filename;
    });

    $('upload-form')?.addEventListener('submit', async (e) => {
        e.preventDefault();

        const file1 = $('xml-file1').files[0];
        const file2 = $('xml-file2').files[0];

        if (!file1 || !file2) {
            showNotification('Please select both files', 'error');
            return;
        }

        const formData = new FormData();
        formData.append('file1', file1);
        formData.append('file2', file2);

        const statusDiv = $('upload-status');
        statusDiv.innerHTML = '<div class="loading-spinner"></div>';
        statusDiv.className = 'status-message';
        statusDiv.style.display = 'block';

        try {
            const response = await fetch('/api/ne-comparison/compare', {
                method: 'POST',
                body: formData
            });

            const contentType = response.headers.get('content-type');

            if (contentType && contentType.includes('spreadsheet')) {
                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;

                const disposition = response.headers.get('Content-Disposition');
                let filename = 'comparison_report.xlsx';
                if (disposition && disposition.includes('filename=')) {
                    filename = disposition.split('filename=')[1].replace(/"/g, '');
                }

                a.download = filename;
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(url);
                a.remove();

                statusDiv.textContent = 'Comparison completed! File downloaded.';
                statusDiv.className = 'status-message success';
                showNotification('Comparison report downloaded!', 'success');
            } else {
                const data = await response.json();
                statusDiv.textContent = `Error: ${data.error}`;
                statusDiv.className = 'status-message error';
                showNotification(data.error, 'error');
            }
        } catch (error) {
            statusDiv.textContent = `Error: ${error.message}`;
            statusDiv.className = 'status-message error';
            showNotification('Comparison failed', 'error');
        }
    });
}

function displayResults(comparison) {
    document.getElementById('results-section').style.display = 'block';
    const title = $('results-title');
    if (title) title.textContent = 'Comparison Results';

    const stats = comparison.stats;
    const statsBar = document.getElementById('comparison-stats');
    statsBar.innerHTML = `
        <div class="stat-item">
            <div class="stat-value added">${stats.added || 0}</div>
            <div class="stat-label">Added</div>
        </div>
        <div class="stat-item">
            <div class="stat-value removed">${stats.removed || 0}</div>
            <div class="stat-label">Removed</div>
        </div>
        <div class="stat-item">
            <div class="stat-value modified">${stats.modified || 0}</div>
            <div class="stat-label">Modified</div>
        </div>
        <div class="stat-item">
            <div class="stat-value same">${stats.same || 0}</div>
            <div class="stat-label">Unchanged</div>
        </div>
    `;

    const resultsDiv = document.getElementById('comparison-results');
    const differences = comparison.differences || [];
    const warnings = comparison.warnings || [];
    const summary = comparison.summary || [];

    if (differences.length === 0) {
        resultsDiv.innerHTML = [
            renderSummary(summary),
            renderWarnings(warnings),
            '<p style="text-align: center; color: #27ae60; font-size: 1.2em;">No differences found for the compared CM data.</p>',
        ].join('');
        return;
    }

    let html = renderSummary(summary) + renderWarnings(warnings);
    if (comparison.truncated) {
        html += '<div class="status-message error">Result preview is truncated. Download/export support can be added for larger comparisons.</div>';
    }
    differences.forEach(diff => {
        const typeClass = diff.type;
        const typeLabel = diff.type.charAt(0).toUpperCase() + diff.type.slice(1);
        const changes = diff.changes || [];
        const valueHtml = changes.length
            ? `<table class="change-table"><thead><tr><th>Parameter</th><th>Baseline</th><th>Compare</th></tr></thead><tbody>${
                changes.slice(0, 12).map(change => `
                    <tr>
                        <td>${escapeHtml(change.parameter)}</td>
                        <td>${escapeHtml(change.old_value)}</td>
                        <td>${escapeHtml(change.new_value)}</td>
                    </tr>
                `).join('')
            }</tbody></table>${changes.length > 12 ? `<div class="diff-path">+${changes.length - 12} more changed parameter(s)</div>` : ''}`
            : `${diff.old_value !== undefined ? `Old: ${escapeHtml(JSON.stringify(diff.old_value))}<br>` : ''}
               ${diff.new_value !== undefined ? `New: ${escapeHtml(JSON.stringify(diff.new_value))}` : ''}`;

        html += `
            <div class="diff-item ${typeClass}">
                <div class="diff-item-header">${typeLabel}: ${escapeHtml(diff.section || diff.parameter || diff.mo_class || 'CM object')}</div>
                <div class="diff-item-content">
                    ${valueHtml}
                </div>
                <div class="diff-path">${escapeHtml(diff.path || '')}</div>
            </div>
        `;
    });

    resultsDiv.innerHTML = html;
}

function displayAuditResults(audit) {
    $('results-section').style.display = 'block';
    const title = $('results-title');
    if (title) title.textContent = 'NW Audit Results';

    const stats = audit.stats || {};
    const statsBar = $('comparison-stats');
    statsBar.innerHTML = `
        <div class="stat-item">
            <div class="stat-value modified">${stats.parameters || 0}</div>
            <div class="stat-label">Parameters</div>
        </div>
        <div class="stat-item">
            <div class="stat-value high">${stats.high || 0}</div>
            <div class="stat-label">High Inconsistency</div>
        </div>
        <div class="stat-item">
            <div class="stat-value medium">${stats.medium || 0}</div>
            <div class="stat-label">Medium</div>
        </div>
        <div class="stat-item">
            <div class="stat-value same">${stats.consistent || 0}</div>
            <div class="stat-label">Consistent</div>
        </div>
    `;

    const rows = audit.parameter_summary || [];
    const resultsDiv = $('comparison-results');
    let html = renderAuditSectionSummary(audit.section_summary || []) + renderWarnings(audit.warnings || []);
    if (!rows.length) {
        html += '<p style="text-align: center; color: #7f8c8d; font-size: 1.1em;">No parameter samples were returned for this audit.</p>';
        resultsDiv.innerHTML = html;
        return;
    }

    html += `
        <table class="audit-table">
            <thead>
                <tr>
                    <th>MO</th>
                    <th>Parameter</th>
                    <th>Status</th>
                    <th>Inconsistent</th>
                    <th>Distinct</th>
                    <th>Most Common Value</th>
                    <th>Samples</th>
                </tr>
            </thead>
            <tbody>
                ${rows.map(row => `
                    <tr>
                        <td>${escapeHtml(row.section)}</td>
                        <td>${escapeHtml(row.parameter)}</td>
                        <td><span class="audit-badge audit-${escapeHtml(row.status)}">${escapeHtml(row.status)}</span></td>
                        <td>${escapeHtml(row.inconsistency_pct)}%</td>
                        <td>${escapeHtml(row.distinct_values)}</td>
                        <td>${escapeHtml(row.most_common_value)}</td>
                        <td>
                            ${(row.values || []).slice(0, 3).map(v => `
                                <div class="audit-value-sample">
                                    <strong>${escapeHtml(v.percent)}%</strong>
                                    ${escapeHtml(v.value)}
                                    <span>${escapeHtml((v.sample_nes || []).join(', '))}</span>
                                </div>
                            `).join('')}
                        </td>
                    </tr>
                `).join('')}
            </tbody>
        </table>
    `;
    resultsDiv.innerHTML = html;
}

function renderAuditSectionSummary(summary) {
    if (!summary.length) return '';
    return `
        <div class="section-summary">
            ${summary.map(row => `
                <div class="section-summary-item">
                    <strong>${escapeHtml(row.section)}</strong>
                    <span>${row.ne_count || 0} NE pull(s)</span>
                    <span>${row.object_count || 0} object sample(s)</span>
                </div>
            `).join('')}
        </div>
    `;
}

function renderSummary(summary) {
    if (!summary.length) return '';
    return `
        <div class="section-summary">
            ${summary.map(row => `
                <div class="section-summary-item">
                    <strong>${escapeHtml(row.section)}</strong>
                    <span>${row.left_count || 0} vs ${row.right_count || 0} objects</span>
                    <span>${row.modified || 0} modified · ${row.added || 0} added · ${row.removed || 0} removed</span>
                </div>
            `).join('')}
        </div>
    `;
}

function renderWarnings(warnings) {
    if (!warnings.length) return '';
    return `<div class="warning-list">${warnings.map(w => `<div>${escapeHtml(w)}</div>`).join('')}</div>`;
}

async function downloadReport() {
    if (!window.comparisonData) {
        showNotification('No comparison data available', 'error');
        return;
    }

    try {
        const response = await fetch('/api/ne-comparison/download-report', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(window.comparisonData)
        });

        if (response.ok) {
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'comparison_report.xlsx';
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

document.addEventListener('DOMContentLoaded', async () => {
    bindLegacyUpload();
    bindCmWorkflow();
    updateScopeOptions();
    try {
        await Promise.all([loadCmNes(), loadCmMoClasses()]);
    } catch (error) {
        setStatus('cm-status', error.message, 'error');
    }
});
