(function () {
    const focusCase = document.body.dataset.focusCase || "";
    let cases = [];
    let activeId = focusCase || null;
    let detailCache = null;

    function escapeHtml(value) {
        return String(value ?? "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    function cellsLabel(row) {
        const cells = row.cells || [];
        if (!cells.length) return row.site_id || "—";
        if (cells.length <= 2) return cells.join(", ");
        return `${cells.slice(0, 2).join(", ")} +${cells.length - 2}`;
    }

    function parseCells(text) {
        return String(text || "")
            .split(/[\n,;]+/)
            .map((s) => s.trim())
            .filter(Boolean);
    }

    function renderStats(stats) {
        const body = document.getElementById("case-stats-body");
        const by = (stats && stats.by_state) || {};
        const entries = Object.keys(by).sort().map((k) => [k, by[k]]);
        entries.unshift(["total", (stats && stats.total) || 0]);
        body.innerHTML = entries
            .map(([k, v]) => `<dt>${escapeHtml(k)}</dt><dd>${escapeHtml(v)}</dd>`)
            .join("");
    }

    function renderSelection(sel) {
        const summary = document.getElementById("selection-summary");
        const cellsBox = document.getElementById("selection-cells");
        const labelBox = document.getElementById("selection-label");
        if (!sel || sel.kind === "empty" || !(sel.cells || []).length) {
            summary.textContent = "No shared selection.";
            if (!cellsBox.value) cellsBox.value = "";
            return;
        }
        summary.textContent = `${sel.kind}: ${(sel.cells || []).length} cell(s)`
            + (sel.label ? ` — ${sel.label}` : "")
            + (sel.source ? ` (from ${sel.source})` : "");
        cellsBox.value = (sel.cells || []).join("\n");
        labelBox.value = sel.label || "";
    }

    function renderList() {
        const tbody = document.getElementById("case-rows");
        document.getElementById("case-count").textContent = `${cases.length} shown`;
        if (!cases.length) {
            tbody.innerHTML = '<tr><td colspan="6">No cases yet. Open one from a radio issue or selection.</td></tr>';
            return;
        }
        tbody.innerHTML = cases
            .map((row) => `
                <tr data-id="${escapeHtml(row.case_id)}" class="${row.case_id === activeId ? "selected" : ""}">
                    <td><span class="opt-state ${escapeHtml(row.state)}">${escapeHtml(row.state)}</span></td>
                    <td><span class="opt-sev ${escapeHtml(row.severity)}">${escapeHtml(row.severity)}</span></td>
                    <td>
                        <strong>${escapeHtml(row.title)}</strong>
                        <div class="opt-muted">${escapeHtml(row.source_module || "")}</div>
                    </td>
                    <td>${escapeHtml(cellsLabel(row))}</td>
                    <td>${escapeHtml(row.owner || "—")}</td>
                    <td>${escapeHtml((row.updated_at || "").replace("T", " ").slice(0, 16))}</td>
                </tr>
            `)
            .join("");
        tbody.querySelectorAll("tr[data-id]").forEach((tr) => {
            tr.addEventListener("click", () => {
                activeId = tr.dataset.id;
                renderList();
                loadDetail(activeId);
            });
        });
    }

    function renderDetail(payload) {
        const el = document.getElementById("case-detail");
        if (!payload || !payload.case) {
            el.innerHTML = '<p class="opt-muted">Select a case to review narrative, evidence, scorecard, and transitions.</p>';
            return;
        }
        const c = payload.case;
        const allowed = payload.allowed_transitions || [];
        const sc = c.scorecard || {};
        const facts = ((c.evidence || {}).correlator || {}).facts || [];
        const events = payload.events || [];

        el.innerHTML = `
            <h2>${escapeHtml(c.title)}</h2>
            <p>${escapeHtml(c.summary || "")}</p>
            <dl class="opt-detail-meta">
                <div><dt>State</dt><dd><span class="opt-state ${escapeHtml(c.state)}">${escapeHtml(c.state)}</span></dd></div>
                <div><dt>Severity</dt><dd>${escapeHtml(c.severity)} (${escapeHtml(c.score)})</dd></div>
                <div><dt>Source</dt><dd>${escapeHtml(c.source_module || "—")}</dd></div>
                <div><dt>Owner</dt><dd>${escapeHtml(c.owner || "—")}</dd></div>
                <div><dt>Vendor / RAT</dt><dd>${escapeHtml(c.vendor || "—")} / ${escapeHtml(c.technology || "—")}</dd></div>
                <div><dt>Area</dt><dd>${escapeHtml(c.area || "—")}</dd></div>
                <div><dt>Cells</dt><dd>${escapeHtml((c.cells || []).join(", ") || c.site_id || "—")}</dd></div>
                <div><dt>Case ID</dt><dd><code>${escapeHtml(c.case_id)}</code></dd></div>
            </dl>

            <div class="opt-actions">
                ${allowed.map((st) => `<button type="button" class="btn-secondary" data-transition="${escapeHtml(st)}">→ ${escapeHtml(st)}</button>`).join("")}
                <button type="button" class="btn-secondary" id="btn-refresh-evidence">Refresh evidence</button>
                <button type="button" class="btn-secondary" id="btn-refresh-scorecard">Refresh scorecard</button>
                ${c.source_url ? `<a class="btn-secondary" href="${escapeHtml(c.source_url)}">Open source</a>` : ""}
            </div>

            <h3>Narrative</h3>
            <pre class="opt-narrative">${escapeHtml(c.narrative || "No narrative yet.")}</pre>

            <h3>Recommendation</h3>
            <p>${escapeHtml(c.recommendation || "—")}</p>

            <h3>Proposed change</h3>
            <label class="opt-field">
                <textarea id="proposed-change" rows="3">${escapeHtml(c.proposed_change || "")}</textarea>
            </label>
            <label class="opt-field">
                <span>Execution reference</span>
                <input type="text" id="execution-ref" value="${escapeHtml(c.execution_ref || "")}" placeholder="XML job / CR / ticket id">
            </label>
            <button type="button" class="btn-primary" id="btn-save-case-fields">Save change fields</button>

            <h3>Scorecard</h3>
            <dl class="opt-detail-meta">
                <div><dt>Status</dt><dd>${escapeHtml(sc.status || "—")}</dd></div>
                <div><dt>Completeness</dt><dd>${escapeHtml(sc.completeness ?? "—")}</dd></div>
                <div><dt>Confidence</dt><dd>${escapeHtml(sc.confidence ?? "—")}</dd></div>
                <div><dt>Baseline signals</dt><dd>${escapeHtml((sc.baseline || {}).signal_count ?? 0)}</dd></div>
                <div><dt>Control neighbors</dt><dd>${escapeHtml(((sc.control_neighbors || []).length) || 0)}</dd></div>
            </dl>
            <p>${escapeHtml(sc.rollback_warning || "")}</p>
            ${(sc.gaps || []).length ? `<ul class="opt-scorecard-gaps">${sc.gaps.map((g) => `<li>${escapeHtml(g)}</li>`).join("")}</ul>` : ""}

            <h3>Evidence facts (${facts.length})</h3>
            <pre class="opt-narrative">${escapeHtml(JSON.stringify(facts.slice(0, 30), null, 2))}</pre>

            <h3>Events</h3>
            <ul class="opt-events">
                ${events.map((e) => `
                    <li>
                        <strong>${escapeHtml(e.event_type)}</strong>
                        · ${escapeHtml(e.actor || "system")}
                        · ${escapeHtml((e.created_at || "").replace("T", " ").slice(0, 19))}
                        <div class="opt-muted">${escapeHtml(JSON.stringify(e.detail || {}))}</div>
                    </li>
                `).join("") || "<li class='opt-muted'>No events</li>"}
            </ul>
        `;

        el.querySelectorAll("[data-transition]").forEach((btn) => {
            btn.addEventListener("click", async () => {
                const state = btn.getAttribute("data-transition");
                const res = await fetch(`/api/optimization-cases/${encodeURIComponent(c.case_id)}/transition`, {
                    method: "POST",
                    credentials: "same-origin",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ state }),
                });
                const data = await res.json();
                if (!data.success) {
                    alert(data.error || "Transition failed");
                    return;
                }
                await loadList();
                await loadDetail(c.case_id);
            });
        });

        const refreshEv = document.getElementById("btn-refresh-evidence");
        if (refreshEv) {
            refreshEv.addEventListener("click", async () => {
                const res = await fetch(`/api/optimization-cases/${encodeURIComponent(c.case_id)}/refresh-evidence`, {
                    method: "POST",
                    credentials: "same-origin",
                });
                const data = await res.json();
                if (!data.success) alert(data.error || "Refresh failed");
                await loadDetail(c.case_id);
                await loadList();
            });
        }
        const refreshSc = document.getElementById("btn-refresh-scorecard");
        if (refreshSc) {
            refreshSc.addEventListener("click", async () => {
                const res = await fetch(`/api/optimization-cases/${encodeURIComponent(c.case_id)}/refresh-scorecard`, {
                    method: "POST",
                    credentials: "same-origin",
                });
                const data = await res.json();
                if (!data.success) alert(data.error || "Refresh failed");
                await loadDetail(c.case_id);
            });
        }
        const saveFields = document.getElementById("btn-save-case-fields");
        if (saveFields) {
            saveFields.addEventListener("click", async () => {
                const res = await fetch(`/api/optimization-cases/${encodeURIComponent(c.case_id)}`, {
                    method: "PATCH",
                    credentials: "same-origin",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        proposed_change: document.getElementById("proposed-change").value,
                        execution_ref: document.getElementById("execution-ref").value,
                    }),
                });
                const data = await res.json();
                if (!data.success) {
                    alert(data.error || "Save failed");
                    return;
                }
                await fetch(`/api/optimization-cases/${encodeURIComponent(c.case_id)}/refresh-scorecard`, {
                    method: "POST",
                    credentials: "same-origin",
                });
                await loadDetail(c.case_id);
            });
        }
    }

    async function loadList() {
        const state = document.getElementById("filter-state").value;
        const search = document.getElementById("filter-search").value.trim();
        const qs = new URLSearchParams();
        if (state) qs.set("state", state);
        if (search) qs.set("search", search);
        const res = await fetch(`/api/optimization-cases?${qs}`, { credentials: "same-origin" });
        const data = await res.json();
        if (!data.success) throw new Error(data.error || "List failed");
        cases = data.cases || [];
        renderStats(data.stats || {});
        renderList();
    }

    async function loadDetail(caseId) {
        if (!caseId) {
            renderDetail(null);
            return;
        }
        const res = await fetch(`/api/optimization-cases/${encodeURIComponent(caseId)}`, { credentials: "same-origin" });
        const data = await res.json();
        if (!data.success) {
            renderDetail(null);
            alert(data.error || "Failed to load case");
            return;
        }
        detailCache = data;
        activeId = caseId;
        renderList();
        renderDetail(data);
        const url = new URL(window.location.href);
        url.searchParams.set("case", caseId);
        window.history.replaceState({}, "", url);
    }

    async function loadSelection() {
        if (!window.PrimeNetSelection) return;
        try {
            const sel = await window.PrimeNetSelection.fetchServer();
            renderSelection(sel);
        } catch (_) {
            renderSelection(window.PrimeNetSelection.readLocal());
        }
    }

    async function saveSelection() {
        const cells = parseCells(document.getElementById("selection-cells").value);
        const label = document.getElementById("selection-label").value.trim();
        const sel = await window.PrimeNetSelection.save({
            kind: cells.length ? "cells" : "empty",
            cells,
            label,
            source: "optimization-cases",
        });
        renderSelection(sel);
    }

    async function openCaseFromSelection() {
        await saveSelection();
        const cells = parseCells(document.getElementById("selection-cells").value);
        if (!cells.length) {
            alert("Add cells to the selection first.");
            return;
        }
        const label = document.getElementById("selection-label").value.trim();
        const res = await fetch("/api/optimization-cases", {
            method: "POST",
            credentials: "same-origin",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                title: label || `Selection case (${cells.length} cells)`,
                summary: "Opened from shared selection context.",
                cells,
                source_module: "Selection Context",
                category: "Manual",
                selection: window.PrimeNetSelection.readLocal(),
            }),
        });
        const data = await res.json();
        if (!data.success) {
            alert(data.error || "Failed to create case");
            return;
        }
        activeId = data.case.case_id;
        await loadList();
        await loadDetail(activeId);
    }

    document.getElementById("btn-refresh-list").addEventListener("click", () => loadList().catch((e) => alert(e.message)));
    document.getElementById("filter-state").addEventListener("change", () => loadList().catch((e) => alert(e.message)));
    document.getElementById("filter-search").addEventListener("keydown", (ev) => {
        if (ev.key === "Enter") loadList().catch((e) => alert(e.message));
    });
    document.getElementById("btn-save-selection").addEventListener("click", () => saveSelection().catch((e) => alert(e.message)));
    document.getElementById("btn-clear-selection").addEventListener("click", async () => {
        const sel = await window.PrimeNetSelection.clear();
        document.getElementById("selection-cells").value = "";
        document.getElementById("selection-label").value = "";
        renderSelection(sel);
    });
    document.getElementById("btn-case-from-selection").addEventListener("click", () => openCaseFromSelection().catch((e) => alert(e.message)));

    Promise.all([loadSelection(), loadList()])
        .then(() => {
            if (activeId) return loadDetail(activeId);
            return null;
        })
        .catch((err) => {
            document.getElementById("case-rows").innerHTML =
                `<tr><td colspan="6">${escapeHtml(err.message || "Failed to load")}</td></tr>`;
        });
})();
