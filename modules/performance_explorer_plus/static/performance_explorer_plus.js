(() => {
  const $ = (id) => document.getElementById(id);
  let chart;
  let lastResult = null;
  let kpis = [];
  let counters = [];
  let objects = [];
  let selectedObjectDn = "";
  let selectedCounterIds = new Set();
  let mode = "explore"; // explore | builder | health
  let viewMode = "charts"; // charts | table | drill

  function pepSidebarToggle(btn) {
    const expanded = btn.getAttribute("aria-expanded") !== "false";
    const next = !expanded;
    btn.setAttribute("aria-expanded", next ? "true" : "false");
    const bodyId = btn.getAttribute("aria-controls");
    const body = bodyId ? document.getElementById(bodyId) : null;
    if (body) body.style.display = next ? "" : "none";
    const chev = btn.querySelector(".perf-chevron");
    if (chev) chev.textContent = next ? "▼" : "▶";
  }
  window.pepSidebarToggle = pepSidebarToggle;

  function togglePepLeftPanel() {
    const body = $("pep-body");
    const btn = $("perf-left-panel-toggle");
    const collapsed = body.classList.toggle("left-collapsed");
    btn.setAttribute("aria-expanded", collapsed ? "false" : "true");
    btn.textContent = collapsed ? "▶" : "◀";
    btn.title = collapsed ? "Expand filters" : "Collapse filters";
  }
  window.togglePepLeftPanel = togglePepLeftPanel;

  function setMode(next) {
    mode = next;
    document.querySelectorAll(".perf-mode-btn").forEach((b) => {
      b.classList.toggle("active", b.dataset.mode === next);
    });
    $("pep-explore-controls").style.display = next === "explore" ? "" : "none";
    $("pep-builder-controls").style.display = next === "builder" ? "" : "none";
    $("pep-health-controls").style.display = next === "health" ? "" : "none";

    $("no-selection").style.display = "none";
    $("charts-wrap").style.display = "none";
    $("pm-table-view").style.display = "none";
    $("pep-drill-view").style.display = "none";
    $("pep-builder-view").style.display = next === "builder" ? "" : "none";
    $("pep-health-view").style.display = next === "health" ? "" : "none";
    $("view-toggle").style.display = next === "explore" ? "" : "none";
    $("btn-export").style.display = next === "explore" && lastResult ? "" : "none";
    $("pep-save-view").style.display = next === "explore" && lastResult ? "" : "none";

    if (next === "explore") {
      $("charts-title").textContent = lastResult
        ? "Query result"
        : "Select objects and counters, then Query";
      if (lastResult) showExploreResult();
      else $("no-selection").style.display = "";
    } else if (next === "builder") {
      $("charts-title").textContent = "KPI Builder";
    } else {
      $("charts-title").textContent = "Ingest Health";
      refreshHealth();
    }
  }

  function setViewMode(next) {
    viewMode = next;
    document.querySelectorAll("#view-toggle .view-btn").forEach((b) => {
      b.classList.toggle("active", b.dataset.view === next);
    });
    if (mode !== "explore" || !lastResult) return;
    showExploreResult();
  }

  function showExploreResult() {
    $("no-selection").style.display = "none";
    $("loading-charts").style.display = "none";
    $("charts-wrap").style.display = viewMode === "charts" ? "" : "none";
    $("pm-table-view").style.display = viewMode === "table" ? "" : "none";
    $("pep-drill-view").style.display = viewMode === "drill" ? "" : "none";
    $("btn-export").style.display = "";
    $("pep-save-view").style.display = "";
  }

  function metricMode() {
    const el = document.querySelector('input[name="pep-metric-mode"]:checked');
    return el ? el.value : "counters";
  }

  function syncMetricModeUi() {
    const m = metricMode();
    $("pep-kpi-select").style.display = m === "kpi" ? "" : "none";
    $("kpi-scope-list").style.display = m === "counters" ? "" : "none";
    $("pep-counter-search").style.display = m === "counters" ? "" : "none";
  }

  function queryPayload() {
    let formula = ($("pep-formula").value || "").trim();
    let counterIds = Array.from(selectedCounterIds);
    if (metricMode() === "kpi") {
      const kpiId = $("pep-kpi-select").value;
      const kpi = kpis.find((k) => String(k.id) === String(kpiId));
      if (kpi) formula = kpi.formula;
    }
    return {
      resolution: $("pep-resolution").value,
      site_key: ($("pep-site").value || "").trim() || null,
      formula: formula || null,
      counter_ids: formula ? null : counterIds,
      object_dns: selectedObjectDn ? [selectedObjectDn] : null,
      limit: 5000,
    };
  }

  function renderMeta(result) {
    const c = result.completeness_pct;
    $("pep-meta").textContent = [
      `points=${(result.points || []).length}`,
      `objects=${result.objects_with_data ?? "—"}`,
      `expected=${result.expected_objects ?? "—"}`,
      `completeness=${c == null ? "—" : c + "%"}`,
      `resolution=${result.resolution}`,
    ].join(" · ");
  }

  function renderChart(result) {
    const labels = (result.summary || []).map((p) => p.bucket_ts);
    const values = (result.summary || []).map((p) => p.value);
    const ctx = $("pep-chart").getContext("2d");
    if (chart) chart.destroy();
    chart = new Chart(ctx, {
      type: "line",
      data: {
        labels,
        datasets: [
          {
            label: result.formula || "value",
            data: values,
            borderColor: "#2563eb",
            backgroundColor: "rgba(37, 99, 235, 0.12)",
            tension: 0.15,
            pointRadius: 2,
            fill: true,
          },
        ],
      },
      options: {
        responsive: true,
        plugins: { legend: { display: true } },
        scales: { x: { ticks: { maxTicksLimit: 10 } } },
      },
    });
  }

  function renderTable(result) {
    const tbody = $("pep-table").querySelector("tbody");
    tbody.innerHTML = "";
    (result.points || []).slice(0, 500).forEach((p, idx) => {
      const tr = document.createElement("tr");
      const metric = p.counter_id || result.formula || "kpi";
      tr.innerHTML = `<td>${p.bucket_ts || ""}</td><td>${p.object_dn || ""}</td><td>${metric}</td><td>${
        p.value == null ? "—" : Number(p.value).toFixed(4)
      }</td>`;
      tr.addEventListener("click", () => {
        tbody.querySelectorAll("tr").forEach((r) => r.classList.remove("active"));
        tr.classList.add("active");
        $("pep-drill-body").textContent = JSON.stringify(p, null, 2);
        setViewMode("drill");
      });
      if (idx === 0) {
        tr.classList.add("active");
        $("pep-drill-body").textContent = JSON.stringify(p, null, 2);
      }
      tbody.appendChild(tr);
    });
  }

  async function runQuery() {
    const payload = queryPayload();
    if (!payload.formula && !(payload.counter_ids || []).length) {
      $("pep-meta").textContent = "Select counters or a saved KPI / formula.";
      return;
    }
    setMode("explore");
    $("no-selection").style.display = "none";
    $("charts-wrap").style.display = "none";
    $("pm-table-view").style.display = "none";
    $("pep-drill-view").style.display = "none";
    $("loading-charts").style.display = "";
    $("pep-meta").textContent = "Running…";
    $("charts-title").textContent = "Loading…";

    const res = await fetch("/api/performance-explorer-plus/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    $("loading-charts").style.display = "none";
    if (!data.success) {
      $("pep-meta").textContent = data.error || "Query failed";
      $("no-selection").style.display = "";
      return;
    }
    lastResult = data;
    $("charts-title").textContent = data.formula || (data.counters || []).join(", ") || "Query result";
    renderMeta(data);
    renderChart(data);
    renderTable(data);
    showExploreResult();
  }

  async function exportCsv() {
    const payload = queryPayload();
    const res = await fetch("/api/performance-explorer-plus/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      alert("Export failed");
      return;
    }
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "pm_plus_export.csv";
    a.click();
  }

  async function saveView() {
    const name = prompt("View name?");
    if (!name) return;
    await fetch("/api/performance-explorer-plus/views", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, payload: queryPayload() }),
    });
  }

  function renderObjects(filter = "") {
    const list = $("pep-object-list");
    list.innerHTML = "";
    const q = (filter || "").toLowerCase();
    const rows = objects.filter((o) => !q || String(o.object_dn || "").toLowerCase().includes(q));
    $("cell-count-badge").textContent = `${rows.length} object(s)`;
    rows.slice(0, 400).forEach((o) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "pep-object-item" + (o.object_dn === selectedObjectDn ? " active" : "");
      btn.textContent = o.object_dn;
      btn.title = [o.tech, o.site_key].filter(Boolean).join(" · ");
      btn.addEventListener("click", () => {
        selectedObjectDn = o.object_dn;
        $("filter-object-dn").value = o.object_dn;
        $("filter-site").value = o.site_key || "";
        if (o.site_key) $("pep-site").value = o.site_key;
        renderObjects($("cell-search").value);
      });
      list.appendChild(btn);
    });
  }

  function renderCounterList(filter = "") {
    const list = $("kpi-scope-list");
    list.innerHTML = "";
    const q = (filter || "").toLowerCase();
    const rows = counters.filter(
      (c) =>
        !q ||
        String(c.counter_id || "").toLowerCase().includes(q) ||
        String(c.family || "").toLowerCase().includes(q)
    );
    $("kpi-scope-count").textContent = String(rows.length);
    rows.slice(0, 400).forEach((c) => {
      const label = document.createElement("label");
      label.className = "pep-counter-item";
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = selectedCounterIds.has(c.counter_id);
      cb.addEventListener("change", () => {
        if (cb.checked) selectedCounterIds.add(c.counter_id);
        else selectedCounterIds.delete(c.counter_id);
      });
      const span = document.createElement("span");
      span.innerHTML = `<code>${c.counter_id}</code>${c.family ? ` · ${c.family}` : ""}`;
      label.appendChild(cb);
      label.appendChild(span);
      list.appendChild(label);
    });
  }

  async function loadObjects() {
    const q = ($("cell-search").value || "").trim();
    const res = await fetch(
      `/api/performance-explorer-plus/objects?q=${encodeURIComponent(q)}&limit=500`
    );
    const data = await res.json();
    objects = data.objects || [];
    renderObjects(q);
  }

  async function loadCounters(q = "") {
    const res = await fetch(
      `/api/performance-explorer-plus/counters?q=${encodeURIComponent(q)}&limit=500`
    );
    const data = await res.json();
    counters = data.counters || [];
    renderCounterList(q);
  }

  async function loadKpis() {
    const res = await fetch("/api/performance-explorer-plus/kpis");
    const data = await res.json();
    kpis = data.kpis || [];
    const sel = $("pep-kpi-select");
    sel.innerHTML = '<option value="">Select saved KPI…</option>';
    const list = $("pep-kpi-list");
    list.innerHTML = "";
    kpis.forEach((k) => {
      const opt = document.createElement("option");
      opt.value = k.id;
      opt.textContent = k.name;
      sel.appendChild(opt);
      const li = document.createElement("li");
      li.innerHTML = `<span><strong>${k.name}</strong><br><code>${k.formula}</code></span>`;
      const del = document.createElement("button");
      del.type = "button";
      del.className = "btn-query";
      del.textContent = "Delete";
      del.addEventListener("click", async () => {
        await fetch(`/api/performance-explorer-plus/kpis/${k.id}`, { method: "DELETE" });
        loadKpis();
      });
      li.appendChild(del);
      list.appendChild(li);
    });
  }

  async function refreshHealth() {
    const box = $("pep-health");
    box.innerHTML = "<p class='pep-muted'>Loading…</p>";
    const res = await fetch("/api/performance-explorer-plus/health");
    const data = await res.json();
    if (!data.success) {
      box.innerHTML = `<p>${data.error || "Failed"}</p>`;
      return;
    }
    const lag = data.lag || {};
    const wh = data.warehouse || {};
    const stats = [
      ["Lag (min)", lag.lag_minutes == null ? "—" : Number(lag.lag_minutes).toFixed(1)],
      ["Backlog", lag.backlog_files ?? 0],
      ["Failed", lag.failed_files ?? 0],
      ["Last ROP", lag.last_rop || "—"],
      ["Objects", wh.objects ?? 0],
      ["Counters", wh.counters ?? 0],
      ["Hour facts", wh.fact_hour ?? 0],
      ["Day facts", wh.fact_day ?? 0],
      ["Ledger", wh.ledger ?? 0],
    ];
    box.innerHTML = stats
      .map(
        ([label, value]) =>
          `<div class="pep-stat"><div class="label">${label}</div><div class="value">${value}</div></div>`
      )
      .join("");
  }

  document.querySelectorAll(".perf-mode-btn").forEach((btn) => {
    btn.addEventListener("click", () => setMode(btn.dataset.mode));
  });
  document.querySelectorAll("#view-toggle .view-btn").forEach((btn) => {
    btn.addEventListener("click", () => setViewMode(btn.dataset.view));
  });
  document.querySelectorAll('input[name="pep-metric-mode"]').forEach((el) => {
    el.addEventListener("change", syncMetricModeUi);
  });

  $("pep-run").addEventListener("click", runQuery);
  $("btn-export").addEventListener("click", exportCsv);
  $("pep-save-view").addEventListener("click", saveView);
  $("pep-refresh-health").addEventListener("click", refreshHealth);
  $("pep-refresh-objects").addEventListener("click", loadObjects);
  $("cell-search").addEventListener("input", (e) => renderObjects(e.target.value));
  $("pep-counter-search").addEventListener("input", (e) => renderCounterList(e.target.value));

  $("pep-kpi-validate").addEventListener("click", async () => {
    const formula = $("pep-kpi-formula").value;
    const res = await fetch("/api/performance-explorer-plus/kpis/validate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ formula }),
    });
    $("pep-kpi-msg").textContent = JSON.stringify(await res.json(), null, 2);
  });

  $("pep-kpi-save").addEventListener("click", async () => {
    const res = await fetch("/api/performance-explorer-plus/kpis", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: $("pep-kpi-name").value,
        formula: $("pep-kpi-formula").value,
        description: $("pep-kpi-desc").value,
      }),
    });
    const data = await res.json();
    $("pep-kpi-msg").textContent = JSON.stringify(data, null, 2);
    if (data.success) loadKpis();
  });

  $("pep-run-rollup").addEventListener("click", async () => {
    const res = await fetch("/api/performance-explorer-plus/rollup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ retention: true }),
    });
    alert(JSON.stringify(await res.json()));
    refreshHealth();
  });

  syncMetricModeUi();
  loadKpis();
  loadCounters();
  loadObjects();
  setMode("explore");
})();
