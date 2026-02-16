/**
 * NE Comparison Page JavaScript
 */

document.getElementById('xml-file1').addEventListener('change', (e) => {
    const filename = e.target.files[0]?.name || 'Choose first XML...';
    document.getElementById('file1-text').textContent = filename;
});

document.getElementById('xml-file2').addEventListener('change', (e) => {
    const filename = e.target.files[0]?.name || 'Choose second XML...';
    document.getElementById('file2-text').textContent = filename;
});

document.getElementById('upload-form').addEventListener('submit', async (e) => {
    e.preventDefault();

    const file1 = document.getElementById('xml-file1').files[0];
    const file2 = document.getElementById('xml-file2').files[0];

    if (!file1 || !file2) {
        showNotification('Please select both files', 'error');
        return;
    }

    const formData = new FormData();
    formData.append('file1', file1);
    formData.append('file2', file2);

    const statusDiv = document.getElementById('upload-status');
    statusDiv.innerHTML = '<div class="loading-spinner"></div>';
    statusDiv.className = 'status-message';
    statusDiv.style.display = 'block';

    try {
        const response = await fetch('/api/ne-comparison/compare', {
            method: 'POST',
            body: formData
        });

        // Check if response is an Excel file (like old version)
        const contentType = response.headers.get('content-type');

        if (contentType && contentType.includes('spreadsheet')) {
            // Download the Excel file directly
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;

            // Get filename from Content-Disposition header or use default
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
            // Handle error response
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

function displayResults(comparison) {
    document.getElementById('results-section').style.display = 'block';

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

    if (differences.length === 0) {
        resultsDiv.innerHTML = '<p style="text-align: center; color: #27ae60; font-size: 1.2em;">No differences found. Files are identical!</p>';
        return;
    }

    let html = '';
    differences.forEach(diff => {
        const typeClass = diff.type;
        const typeLabel = diff.type.charAt(0).toUpperCase() + diff.type.slice(1);

        html += `
            <div class="diff-item ${typeClass}">
                <div class="diff-item-header">${typeLabel}: ${diff.parameter || diff.mo_class}</div>
                <div class="diff-item-content">
                    ${diff.old_value !== undefined ? `Old: ${diff.old_value}<br>` : ''}
                    ${diff.new_value !== undefined ? `New: ${diff.new_value}` : ''}
                </div>
                <div class="diff-path">${diff.path || ''}</div>
            </div>
        `;
    });

    resultsDiv.innerHTML = html;
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
