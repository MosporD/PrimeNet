(function () {
    const body = document.body;
    const apiUrl = body.dataset.apiUrl;
    const defaultTechnology = body.dataset.defaultTechnology || 'all';

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

    function renderRows(rows) {
        const tbody = document.getElementById('radio-rows');
        if (!rows || rows.length === 0) {
            tbody.innerHTML = '<tr><td colspan="8">No issues found for the selected filters.</td></tr>';
            return;
        }
        tbody.innerHTML = rows.map((row) => {
            const cells = (row.cells || []).filter(Boolean).join(', ') || row.site_id || '-';
            return `
                <tr>
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
            setSummary(data.summary || {});
            renderRows(data.issues || []);
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

