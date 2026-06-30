(function () {
    const body = document.body;
    const apiUrl = body.dataset.apiUrl;
    const defaultTechnology = body.dataset.defaultTechnology || 'all';
    let currentRows = [];

    function escapeHtml(value) {
        return String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function setSummary(summary) {
        const bySeverity = summary?.by_severity || {};
        document.getElementById('radio-total').textContent = summary?.total ?? 0;
        document.getElementById('radio-critical').textContent = bySeverity.Critical || 0;
        document.getElementById('radio-high').textContent = bySeverity.High || 0;
        document.getElementById('radio-medium').textContent = bySeverity.Medium || 0;
    }

    function setModuleSummary(rows) {
        const container = document.getElementById('radio-module-summary');
        const counts = new Map();
        (rows || []).forEach((row) => {
            const key = row.module || row.category || 'Unclassified';
            counts.set(key, (counts.get(key) || 0) + 1);
        });
        if (!counts.size) {
            container.innerHTML = '';
            container.hidden = true;
            return;
        }
        container.hidden = false;
        container.innerHTML = Array.from(counts.entries())
            .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
            .map(([label, count]) => `
                <div class="radio-module-chip">
                    <span>${escapeHtml(label)}</span>
                    <strong>${escapeHtml(count)}</strong>
                </div>
            `).join('');
    }

    function formatEvidence(evidence) {
        if (!evidence || Object.keys(evidence).length === 0) {
            return '<p class="radio-muted">No structured evidence available.</p>';
        }
        return `<pre class="radio-evidence">${escapeHtml(JSON.stringify(evidence, null, 2))}</pre>`;
    }

    function renderDetail(row) {
        const detail = document.getElementById('radio-detail');
        if (!row) {
            detail.innerHTML = '<p class="radio-detail-placeholder">Select an issue to review evidence and recommended action.</p>';
            return;
        }
        const cells = (row.cells || []).filter(Boolean).join(', ') || row.site_id || '-';
        const sourceLink = row.source_url
            ? `<a href="${escapeHtml(row.source_url)}" class="radio-detail-link">Open source module</a>`
            : '';
        detail.innerHTML = `
            <div class="radio-detail-head">
                <span class="radio-severity ${escapeHtml(row.severity)}">${escapeHtml(row.severity)}</span>
                <span class="radio-detail-score">Score ${escapeHtml(row.score ?? '-')}</span>
            </div>
            <h2>${escapeHtml(row.title || 'Issue detail')}</h2>
            <p class="radio-detail-summary">${escapeHtml(row.summary || '')}</p>
            <dl class="radio-detail-meta">
                <div><dt>Source</dt><dd>${escapeHtml(row.module || '-')}</dd></div>
                <div><dt>Category</dt><dd>${escapeHtml(row.category || '-')}</dd></div>
                <div><dt>Area</dt><dd>${escapeHtml(row.area || '-')}</dd></div>
                <div><dt>Vendor</dt><dd>${escapeHtml(row.vendor || '-')}</dd></div>
                <div><dt>Technology</dt><dd>${escapeHtml(row.technology || '-')}</dd></div>
                <div><dt>Cells / Site</dt><dd>${escapeHtml(cells)}</dd></div>
            </dl>
            <h3>Recommended Action</h3>
            <p>${escapeHtml(row.recommendation || 'Review the issue evidence and source module before action.')}</p>
            <h3>Evidence</h3>
            ${formatEvidence(row.evidence || {})}
            ${sourceLink}
        `;
    }

    function renderRows(rows) {
        const tbody = document.getElementById('radio-rows');
        if (!rows || rows.length === 0) {
            tbody.innerHTML = '<tr><td colspan="8">No issues found for the selected filters.</td></tr>';
            renderDetail(null);
            return;
        }
        tbody.innerHTML = rows.map((row, index) => {
            const cells = (row.cells || []).filter(Boolean).join(', ') || row.site_id || '-';
            return `
                <tr data-row-index="${index}" tabindex="0">
                    <td><span class="radio-severity ${escapeHtml(row.severity)}">${escapeHtml(row.severity)}</span></td>
                    <td>${escapeHtml(row.score)}</td>
                    <td>
                        <strong>${escapeHtml(row.title)}</strong>
                        <div class="radio-muted">${escapeHtml(row.summary)}</div>
                    </td>
                    <td>${escapeHtml(row.area || '-')}</td>
                    <td>${escapeHtml(row.vendor || '-')}</td>
                    <td>${escapeHtml(row.technology || '-')}</td>
                    <td>${escapeHtml(cells)}</td>
                    <td>${escapeHtml(row.recommendation || '-')}</td>
                </tr>
            `;
        }).join('');
        tbody.querySelectorAll('tr[data-row-index]').forEach((tr) => {
            const selectRow = () => {
                tbody.querySelectorAll('tr.selected').forEach((item) => item.classList.remove('selected'));
                tr.classList.add('selected');
                renderDetail(currentRows[Number(tr.dataset.rowIndex)]);
            };
            tr.addEventListener('click', selectRow);
            tr.addEventListener('keydown', (event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    selectRow();
                }
            });
        });
        const first = tbody.querySelector('tr[data-row-index]');
        if (first) {
            first.classList.add('selected');
            renderDetail(rows[0]);
        }
    }

    async function loadAreas() {
        try {
            const response = await fetch('/api/radio/areas');
            const data = await response.json();
            const select = document.getElementById('radio-area');
            (data.areas || []).forEach((area) => {
                const option = document.createElement('option');
                option.value = area;
                option.textContent = area;
                select.appendChild(option);
            });
        } catch (error) {
            // Filters still work without area options.
        }
    }

    async function loadData() {
        const tbody = document.getElementById('radio-rows');
        tbody.innerHTML = '<tr><td colspan="8">Loading...</td></tr>';
        const params = new URLSearchParams({
            area: document.getElementById('radio-area').value,
            vendor: document.getElementById('radio-vendor').value,
            technology: document.getElementById('radio-technology').value,
            q: document.getElementById('radio-search').value,
            limit: '250',
        });
        try {
            const response = await fetch(`${apiUrl}?${params.toString()}`);
            const data = await response.json();
            if (!data.success) {
                throw new Error(data.error || 'Request failed');
            }
            currentRows = data.issues || [];
            setSummary(data.summary || {});
            setModuleSummary(currentRows);
            renderRows(currentRows);
            const note = document.getElementById('radio-note');
            if (data.note) {
                note.hidden = false;
                note.textContent = data.note;
            } else {
                note.hidden = true;
            }
        } catch (error) {
            tbody.innerHTML = `<tr><td colspan="8">Failed to load data: ${escapeHtml(error.message)}</td></tr>`;
        }
    }

    document.addEventListener('DOMContentLoaded', () => {
        document.getElementById('radio-technology').value = defaultTechnology;
        document.getElementById('radio-apply').addEventListener('click', loadData);
        document.getElementById('radio-search').addEventListener('keydown', (event) => {
            if (event.key === 'Enter') {
                loadData();
            }
        });
        loadAreas().finally(loadData);
    });
}());

