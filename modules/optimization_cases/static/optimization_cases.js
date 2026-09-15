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
            tbody.innerHTML = '<tr><td colspan="7">No cases yet. Open one from a radio issue or selection.</td></tr>';
            return;
        }
        tbody.innerHTML = cases
            .map((row) => `
                <tr data-id="${escapeHtml(row.case_id)}" class="${row.case_id === activeId ? "selected" : ""}">
                    <td><span class="opt-state ${escapeHtml(row.state)}">${escapeHtml(row.state)}</span></td>
                    <td><span class="opt-sev ${escapeHtml(row.severity)}">${escapeHtml(row.severity)}</span></td>
                    <td>${escapeHtml(row.impact_score ?? "—")}</td>
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

    function checklistHtml(checklist) {
        const keys = ["availability_ok", "cssr_ok", "cdr_ok", "alarms_cleared", "map_location_ok"];
        if (!checklist || !Object.keys(checklist).length) return "";
        return `
            <h3>Cluster checklist</h3>
            <div class="opt-checklist" id="case-checklist">
                ${keys.map((k) => `
                    <label><input type="checkbox" data-check="${k}" ${checklist[k] ? "checked" : ""}> ${escapeHtml(k)}</label>
                `).join("")}
                <label class="opt-field"><span>Notes</span>
                    <textarea id="checklist-notes" rows="2">${escapeHtml(checklist.notes || "")}</textarea>
                </label>
                <button type="button" class="btn-secondary" id="btn-save-checklist">Save checklist</button>
            </div>
        `;
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
        const related = payload.related_cases || [];
        const pm = payload.pm_deeplink || {};
        const post = sc.post || {};
        const impact = ((c.evidence || {}).impact || {});

        el.innerHTML = `
            <h2>${escapeHtml(c.title)}</h2>
            <p>${escapeHtml(c.summary || "")}</p>
            <dl class="opt-detail-meta">
                <div><dt>State</dt><dd><span class="opt-state ${escapeHtml(c.state)}">${escapeHtml(c.state)}</span></dd></div>
                <div><dt>Severity</dt><dd>${escapeHtml(c.severity)} (${escapeHtml(c.score)})</dd></div>
                <div><dt>Impact Score (PM)</dt><dd>${escapeHtml(c.impact_score ?? impact.impact_score ?? "—")}</dd></div>
                <div><dt>Source</dt><dd>${escapeHtml(c.source_module || "—")}</dd></div>
                <div><dt>Owner</dt><dd>${escapeHtml(c.owner || "—")}</dd></div>
                <div><dt>Ticket</dt><dd>${escapeHtml(c.ticket_id || "—")}</dd></div>
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
                <a class="btn-secondary" id="btn-pm-link" href="${escapeHtml(pm.performance_url || "/performance")}">Open Performance</a>
                <a class="btn-secondary" href="${escapeHtml(pm.performance_plus_url || "/performance-explorer-plus")}">Open Performance Plus</a>
            </div>
            <label class="opt-field">
                <span>Override note (conflict / golden-rule approve)</span>
                <input type="text" id="override-note" placeholder="Required when gates block approval">
            </label>

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
                <div><dt>Verdict</dt><dd>${escapeHtml(sc.verdict || "—")}</dd></div>
                <div><dt>Completeness</dt><dd>${escapeHtml(sc.completeness ?? "—")}</dd></div>
                <div><dt>Confidence</dt><dd>${escapeHtml(sc.confidence ?? "—")}</dd></div>
                <div><dt>Baseline signals</dt><dd>${escapeHtml((sc.baseline || {}).signal_count ?? 0)}</dd></div>
                <div><dt>Post signals</dt><dd>${escapeHtml(post.signal_count ?? 0)}</dd></div>
                <div><dt>Control neighbors</dt><dd>${escapeHtml(((sc.control_neighbors || []).length) || 0)}</dd></div>
            </dl>
            <p>${escapeHtml(sc.rollback_warning || "")}</p>
            <p class="opt-muted">${escapeHtml(post.note || "")}</p>
            ${(sc.gaps || []).length ? `<ul class="opt-scorecard-gaps">${sc.gaps.map((g) => `<li>${escapeHtml(g)}</li>`).join("")}</ul>` : ""}

            ${checklistHtml(c.checklist)}

            <h3>Same-cell history (30d)</h3>
            <ul class="opt-events">
                ${related.map((r) => `
                    <li>
                        <a href="/optimization-cases?case=${encodeURIComponent(r.case_id)}">${escapeHtml(r.case_id)}</a>
                        · ${escapeHtml(r.state)} · ${escapeHtml(r.title || "")}
                        <div class="opt-muted">${escapeHtml(r.source_module || "")} · ${escapeHtml((r.updated_at || "").slice(0, 16))}</div>
                    </li>
                `).join("") || "<li class='opt-muted'>No related cases in the last 30 days.</li>"}
            </ul>

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

        // Persist selection for Performance deep-links
        if ((c.cells || []).length && window.PrimeNetSelection) {
            window.PrimeNetSelection.save({
                kind: "cells",
                cells: c.cells,
                label: c.title || "",
                source: "optimization-cases",
                meta: { case_id: c.case_id, start: pm.start || "", end: pm.end || "" },
            }).catch(() => {});
        }

        el.querySelectorAll("[data-transition]").forEach((btn) => {
            btn.addEventListener("click", async () => {
                const state = btn.getAttribute("data-transition");
                const overrideNote = (document.getElementById("override-note") || {}).value || "";
                const res = await fetch(`/api/optimization-cases/${encodeURIComponent(c.case_id)}/transition`, {
                    method: "POST",
                    credentials: "same-origin",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ state, override_note: overrideNote }),
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
        const saveCheck = document.getElementById("btn-save-checklist");
        if (saveCheck) {
            saveCheck.addEventListener("click", async () => {
                const checklist = Object.assign({}, c.checklist || {});
                el.querySelectorAll("[data-check]").forEach((cb) => {
                    checklist[cb.getAttribute("data-check")] = !!cb.checked;
                });
                checklist.notes = (document.getElementById("checklist-notes") || {}).value || "";
                const res = await fetch(`/api/optimization-cases/${encodeURIComponent(c.case_id)}`, {
                    method: "PATCH",
                    credentials: "same-origin",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ checklist }),
                });
                const data = await res.json();
                if (!data.success) alert(data.error || "Checklist save failed");
                else await loadDetail(c.case_id);
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

    async function openClusterAcceptance() {
        await saveSelection();
        const cells = parseCells(document.getElementById("selection-cells").value);
        if (!cells.length) {
            alert("Add cells for cluster acceptance.");
            return;
        }
        const label = document.getElementById("selection-label").value.trim();
        const res = await fetch("/api/optimization-cases/cluster-acceptance", {
            method: "POST",
            credentials: "same-origin",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                title: label || `Cluster acceptance (${cells.length} cells)`,
                cells,
            }),
        });
        const data = await res.json();
        if (!data.success) {
            alert(data.error || "Failed to create cluster case");
            return;
        }
        activeId = data.case.case_id;
        await loadList();
        await loadDetail(activeId);
    }

    async function openComplaint() {
        const cells = parseCells(document.getElementById("complaint-cells").value);
        const res = await fetch("/api/optimization-cases/complaint", {
            method: "POST",
            credentials: "same-origin",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                ticket_id: document.getElementById("complaint-ticket").value.trim(),
                site_id: document.getElementById("complaint-site").value.trim(),
                postcode: document.getElementById("complaint-postcode").value.trim(),
                cells,
                summary: document.getElementById("complaint-summary").value.trim(),
            }),
        });
        const data = await res.json();
        if (!data.success) {
            alert(data.error || "Complaint case failed");
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
    document.getElementById("btn-cluster-acceptance").addEventListener("click", () => openClusterAcceptance().catch((e) => alert(e.message)));
    document.getElementById("btn-complaint").addEventListener("click", () => openComplaint().catch((e) => alert(e.message)));

    Promise.all([loadSelection(), loadList()])
        .then(() => {
            if (activeId) return loadDetail(activeId);
            return null;
        })
        .catch((err) => {
            document.getElementById("case-rows").innerHTML =
                `<tr><td colspan="7">${escapeHtml(err.message || "Failed to load")}</td></tr>`;
        });
})();
