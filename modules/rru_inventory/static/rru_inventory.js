(function () {
    'use strict';

    const TECH_ORDER = ['2G', '3G', '4G', '5G', 'Unused'];
    const TECH_COLORS = {
        '2G': '#5dade2',
        '3G': '#58d68d',
        '4G': '#f5b041',
        '5G': '#af7ac5',
        Unused: '#aab7b8',
        area: '#5d6d7e',
        rru: '#2980b9',
    };

    const state = {
        rows: [],
        areaFilter: 'all',
        areaOptions: [],
        networkView: false,
        showArea: true,
        showTech: true,
        showBand: true,
        enabledTechs: new Set(TECH_ORDER),
        showUnused: true,
        productFilter: '',
        loading: false,
    };

    function $(id) {
        return document.getElementById(id);
    }

    function escapeHtml(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function techRoot(label) {
        const text = String(label || '');
        if (text.indexOf('4G') === 0) return '4G';
        if (text.indexOf('3G') === 0) return '3G';
        if (text.indexOf('2G') === 0) return '2G';
        if (text.indexOf('5G') === 0) return '5G';
        return text;
    }

    function techEnabled(label) {
        if (label === 'Unused') return state.showUnused;
        return state.enabledTechs.has(techRoot(label));
    }

    function colorForTech(name) {
        return TECH_COLORS[techRoot(name)] || TECH_COLORS.rru;
    }

    function setStatus(text, isError) {
        const el = $('load-status');
        if (!el) return;
        el.textContent = text || '';
        el.style.color = isError ? '#c0392b' : '#566573';
    }

    function initConnectionPill() {
        const pill = $('cm-config-status');
        const snapPill = $('snapshot-status');
        const ready = document.body.dataset.snapshotReady === 'true';
        const builtAt = document.body.dataset.snapshotBuiltAt || '';
        if (pill) {
            if (ready) {
                pill.textContent = 'Snapshot ready';
                pill.classList.add('ok');
            } else {
                pill.textContent = 'No snapshot yet';
                pill.classList.add('error');
            }
        }
        if (snapPill) {
            snapPill.textContent = builtAt
                ? `Built: ${builtAt}`
                : 'Built: — (admin daily 04:00 or manual run)';
        }
    }

    async function refreshStatus() {
        try {
            const res = await fetch('/api/rru-inventory/status');
            const data = await res.json();
            if (!res.ok || !data.success) return;
            document.body.dataset.snapshotReady = data.snapshot_ready ? 'true' : 'false';
            document.body.dataset.snapshotBuiltAt = data.built_at || '';
            initConnectionPill();
        } catch (_err) {
            /* ignore */
        }
    }

    async function loadAreas() {
        const select = $('area-select');
        if (!select) return;
        try {
            const res = await fetch('/api/rru-inventory/areas');
            const data = await res.json();
            if (!res.ok || !data.success) {
                throw new Error(data.error || 'Failed to load areas');
            }
            const current = select.value || 'all';
            select.innerHTML = '<option value="all">All areas</option>';
            state.areaOptions = [];
            (data.areas || []).forEach(function (item) {
                const area = item.area || item;
                state.areaOptions.push(area);
                const count = item.rru_count != null
                    ? ` (${item.rru_count} RRUs)`
                    : (item.site_count != null ? ` (${item.site_count} sites)` : '');
                const opt = document.createElement('option');
                opt.value = area;
                opt.textContent = `${area}${count}`;
                select.appendChild(opt);
            });
            select.value = current;
        } catch (err) {
            setStatus(err.message || String(err), true);
        }
    }

    function renderTechFilters() {
        const host = $('tech-filters');
        if (!host) return;
        host.innerHTML = '';
        TECH_ORDER.forEach(function (tech) {
            if (tech === 'Unused') return;
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'tech-chip' + (state.enabledTechs.has(tech) ? ' active' : '');
            btn.textContent = tech;
            btn.dataset.tech = tech;
            btn.addEventListener('click', function () {
                if (state.enabledTechs.has(tech)) {
                    state.enabledTechs.delete(tech);
                } else {
                    state.enabledTechs.add(tech);
                }
                btn.classList.toggle('active', state.enabledTechs.has(tech));
                refreshViews();
            });
            host.appendChild(btn);
        });
    }

    function areaKey(value) {
        return String(value || '').trim().toLowerCase();
    }

    function rowVisible(row) {
        const want = areaKey(state.areaFilter);
        if (want && want !== 'all' && areaKey(row.area) !== want) return false;

        const techs = row.techs || [];
        const unused = !!row.unused || (techs.length === 1 && techs[0] === 'Unused');
        if (unused && !state.showUnused) return false;
        const active = techs.filter(function (t) {
            return t !== 'Unused' && techEnabled(t);
        });
        if (!unused && active.length === 0) return false;
        const needle = (state.productFilter || '').trim().toLowerCase();
        if (needle && String(row.productName || '').toLowerCase().indexOf(needle) === -1) {
            return false;
        }
        return true;
    }

    function populateAreaFilter(preferred) {
        const select = $('area-filter');
        if (!select) return;
        const fromRows = Array.from(new Set(
            (state.rows || []).map(function (row) {
                return String(row.area || '').trim();
            }).filter(Boolean)
        )).sort(function (a, b) {
            return a.localeCompare(b);
        });
        const options = fromRows.length ? fromRows : (state.areaOptions || []);
        const want = preferred || state.areaFilter || 'all';
        select.innerHTML = '<option value="all">All areas</option>';
        options.forEach(function (area) {
            const opt = document.createElement('option');
            opt.value = area;
            opt.textContent = area;
            select.appendChild(opt);
        });
        const match = options.find(function (area) {
            return areaKey(area) === areaKey(want);
        });
        if (match) {
            select.value = match;
            state.areaFilter = match;
        } else {
            select.value = 'all';
            state.areaFilter = 'all';
        }
    }

    function applyAreaFilterChange(area, updateShowArea) {
        state.areaFilter = area || 'all';
        const isAll = areaKey(state.areaFilter) === 'all';
        state.networkView = isAll;
        if (updateShowArea) {
            state.showArea = !isAll;
            syncLayerCheckboxes();
        }
        const top = $('area-select');
        if (top) {
            const topMatch = Array.from(top.options).find(function (opt) {
                return areaKey(opt.value) === areaKey(state.areaFilter);
            });
            if (topMatch) top.value = topMatch.value;
            else if (isAll) top.value = 'all';
        }
        refreshViews();
    }

    function filteredRows() {
        return (state.rows || []).filter(rowVisible);
    }

    function orderedTechNames(names) {
        return Array.from(names).sort(function (a, b) {
            const ra = TECH_ORDER.indexOf(techRoot(a));
            const rb = TECH_ORDER.indexOf(techRoot(b));
            const fa = ra === -1 ? TECH_ORDER.length : ra;
            const fb = rb === -1 ? TECH_ORDER.length : rb;
            return fa - fb || a.localeCompare(b);
        });
    }

    function displayTechs(techs) {
        const filtered = (techs || []).filter(function (tech) {
            return techEnabled(tech);
        });
        if (state.showBand) return filtered;
        // Collapse 4G-L18 → 4G while preserving order / uniqueness.
        const seen = new Set();
        const out = [];
        filtered.forEach(function (tech) {
            const root = tech === 'Unused' ? 'Unused' : techRoot(tech);
            if (seen.has(root)) return;
            seen.add(root);
            out.push(root);
        });
        return out;
    }

    function syncLayerCheckboxes() {
        const areaEl = $('sankey-area');
        const techEl = $('sankey-tech');
        const bandEl = $('sankey-band');
        if (areaEl) areaEl.checked = !!state.showArea;
        if (techEl) techEl.checked = !!state.showTech;
        if (bandEl) {
            bandEl.checked = !!state.showBand;
            bandEl.disabled = !state.showTech;
        }
    }

    function aggregateClient(rows) {
        const linkWeights = new Map();
        const nodeKinds = new Map();
        const showArea = !!state.showArea;
        const showTech = !!state.showTech;
        const TOTAL_NODE = 'Total';

        function bump(src, tgt) {
            const key = src + '\0' + tgt;
            linkWeights.set(key, (linkWeights.get(key) || 0) + 1);
        }

        function addNode(name, kind) {
            nodeKinds.set(name, kind);
            return name;
        }

        let unused = 0;
        let multi = 0;
        const byTech = {};

        rows.forEach(function (row) {
            const product = addNode(row.productName || 'Unknown', 'rru');
            if (row.unused) unused += 1;
            if (row.multi_rat) multi += 1;

            const techs = displayTechs(row.techs || ['Unused']);
            if (!techs.length) return;

            techs.forEach(function (tech) {
                byTech[tech] = (byTech[tech] || 0) + 1;
            });

            if (showArea && showTech) {
                const area = addNode(row.area || 'Unknown', 'area');
                techs.forEach(function (tech) {
                    addNode(tech, 'tech');
                    bump(area, tech);
                    bump(tech, product);
                });
            } else if (!showArea && showTech) {
                techs.forEach(function (tech) {
                    addNode(tech, 'tech');
                    bump(tech, product);
                });
            } else if (showArea && !showTech) {
                // One physical RRU → one Area→RRU link (no tech fan-out).
                const area = addNode(row.area || 'Unknown', 'area');
                bump(area, product);
            } else {
                // No area/tech columns — single Total → RRU.
                addNode(TOTAL_NODE, 'total');
                bump(TOTAL_NODE, product);
            }
        });

        const areas = showArea
            ? Array.from(nodeKinds.keys()).filter(function (n) {
                return nodeKinds.get(n) === 'area';
            }).sort()
            : [];
        const techs = showTech
            ? orderedTechNames(
                Array.from(nodeKinds.keys()).filter(function (n) {
                    return nodeKinds.get(n) === 'tech';
                })
            )
            : [];
        const totals = Array.from(nodeKinds.keys()).filter(function (n) {
            return nodeKinds.get(n) === 'total';
        });
        const rruTotals = new Map();
        linkWeights.forEach(function (weight, key) {
            const parts = key.split('\0');
            if (nodeKinds.get(parts[1]) === 'rru') {
                rruTotals.set(parts[1], (rruTotals.get(parts[1]) || 0) + weight);
            }
        });
        // When tech fan-out is off, rruTotals already equals physical count per type.
        const rrus = Array.from(rruTotals.entries())
            .sort(function (a, b) {
                return b[1] - a[1] || a[0].localeCompare(b[0]);
            })
            .map(function (pair) {
                return pair[0];
            });

        const ordered = totals.concat(areas, techs, rrus);
        const index = {};
        ordered.forEach(function (name, i) {
            index[name] = i;
        });
        const nodes = ordered.map(function (name) {
            return { id: name, name: name, kind: nodeKinds.get(name) };
        });
        const links = [];
        linkWeights.forEach(function (weight, key) {
            const parts = key.split('\0');
            if (index[parts[0]] == null || index[parts[1]] == null) return;
            links.push({
                source: index[parts[0]],
                target: index[parts[1]],
                value: weight,
                source_id: parts[0],
                target_id: parts[1],
            });
        });

        return {
            nodes: nodes,
            links: links,
            summary: {
                physical_rrus: rows.length,
                unused: unused,
                multi_rat: multi,
                by_tech: byTech,
                areas: areas.length,
                rru_types: rrus.length,
            },
        };
    }

    function renderSummary(summary) {
        const host = $('summary-strip');
        if (!host) return;
        const byTech = summary.by_tech || {};
        const techBits = orderedTechNames(Object.keys(byTech)).map(function (t) {
            return `${t}: ${byTech[t]}`;
        }).join(' · ');
        const layers = [
            state.showArea ? 'Area' : null,
            state.showTech ? (state.showBand ? 'Tech/band' : 'Tech') : null,
            'RRU',
        ].filter(Boolean).join(' → ');
        host.innerHTML = [
            chip(`${summary.physical_rrus || 0} physical RRUs`),
            chip(`${summary.unused || 0} unused`, true),
            chip(`${summary.multi_rat || 0} multi-RAT`, true),
            chip(`${summary.rru_types || 0} RRU types`, true),
            chip(layers, true),
            techBits ? chip(techBits, true) : '',
        ].join('');
    }

    function chip(text, muted) {
        return `<span class="summary-chip${muted ? ' muted' : ''}">${escapeHtml(text)}</span>`;
    }

    function colorForNode(node) {
        if (node.kind === 'tech') return colorForTech(node.name);
        if (node.kind === 'area') return TECH_COLORS.area;
        if (node.kind === 'total') return TECH_COLORS.area;
        return TECH_COLORS.rru;
    }

    function renderSankey(payload) {
        const svgEl = $('sankey-svg');
        const empty = $('sankey-empty');
        if (!svgEl || typeof d3 === 'undefined' || !d3.sankey) {
            if (empty) {
                empty.hidden = false;
                empty.textContent = 'Sankey library failed to load.';
            }
            return;
        }

        const nodes = (payload.nodes || []).map(function (n) {
            return Object.assign({}, n);
        });
        const links = (payload.links || []).map(function (l) {
            return Object.assign({}, l);
        });

        if (!nodes.length || !links.length) {
            d3.select(svgEl).selectAll('*').remove();
            if (empty) {
                empty.hidden = false;
                empty.textContent = 'No flows match the current filters.';
            }
            return;
        }
        if (empty) empty.hidden = true;

        const width = svgEl.clientWidth || svgEl.parentElement.clientWidth || 900;
        const height = svgEl.clientHeight || 480;
        const margin = { top: 16, right: 140, bottom: 16, left: 12 };
        const innerWidth = Math.max(200, width - margin.left - margin.right);
        const innerHeight = Math.max(200, height - margin.top - margin.bottom);

        const sankey = d3.sankey()
            .nodeWidth(18)
            .nodePadding(14)
            .extent([[0, 0], [innerWidth, innerHeight]]);

        const graph = sankey({
            nodes: nodes,
            links: links,
        });

        const svg = d3.select(svgEl);
        svg.selectAll('*').remove();
        svg.attr('viewBox', `0 0 ${width} ${height}`);

        const g = svg.append('g')
            .attr('transform', `translate(${margin.left},${margin.top})`);

        const linkPath = d3.sankeyLinkHorizontal();

        g.append('g')
            .attr('fill', 'none')
            .selectAll('path')
            .data(graph.links)
            .join('path')
            .attr('class', 'sankey-link')
            .attr('d', linkPath)
            .attr('stroke', function (d) {
                const src = d.source;
                if (src.kind === 'tech') return colorForTech(src.name);
                if (d.target.kind === 'tech') return colorForTech(d.target.name);
                return '#85929e';
            })
            .attr('stroke-width', function (d) {
                return Math.max(1, d.width);
            })
            .append('title')
            .text(function (d) {
                return `${d.source.name} → ${d.target.name}: ${d.value}`;
            });

        const node = g.append('g')
            .selectAll('g')
            .data(graph.nodes)
            .join('g')
            .attr('class', 'sankey-node')
            .attr('transform', function (d) {
                return `translate(${d.x0},${d.y0})`;
            });

        node.append('rect')
            .attr('height', function (d) {
                return Math.max(1, d.y1 - d.y0);
            })
            .attr('width', function (d) {
                return d.x1 - d.x0;
            })
            .attr('fill', function (d) {
                return colorForNode(d);
            })
            .append('title')
            .text(function (d) {
                return `${d.name}: ${d.value}`;
            });

        node.append('text')
            .attr('x', function (d) {
                return d.x0 < innerWidth / 2 ? (d.x1 - d.x0) + 6 : -6;
            })
            .attr('y', function (d) {
                return (d.y1 - d.y0) / 2;
            })
            .attr('dy', '0.35em')
            .attr('text-anchor', function (d) {
                return d.x0 < innerWidth / 2 ? 'start' : 'end';
            })
            .text(function (d) {
                const label = d.name.length > 28 ? d.name.slice(0, 26) + '…' : d.name;
                return `${label} (${d.value})`;
            });
    }

    function renderTable(rows) {
        const tbody = $('rru-tbody');
        if (!tbody) return;
        if (!rows.length) {
            tbody.innerHTML = '<tr><td colspan="6">No RRUs match the current filters.</td></tr>';
            return;
        }
        tbody.innerHTML = rows.map(function (row) {
            const tags = displayTechs(row.techs || []).map(function (tech) {
                const cls = tech === 'Unused' ? 'tech-tag unused' : 'tech-tag';
                return `<span class="${cls}">${escapeHtml(tech)}</span>`;
            }).join('');
            return (
                '<tr>' +
                `<td>${escapeHtml(row.area)}</td>` +
                `<td>${escapeHtml(row.site_name || row.site_id)}</td>` +
                `<td>${escapeHtml(row.productName)}</td>` +
                `<td>${tags}</td>` +
                `<td>${escapeHtml(row.operationalState || '')}</td>` +
                `<td class="mono">${escapeHtml(row.DN)}</td>` +
                '</tr>'
            );
        }).join('');
    }

    function showWarnings(warnings) {
        const box = $('results-warnings');
        if (!box) return;
        if (!warnings || !warnings.length) {
            box.hidden = true;
            box.textContent = '';
            return;
        }
        box.hidden = false;
        box.textContent = warnings.join(' ');
    }

    function refreshViews() {
        const rows = filteredRows();
        const payload = aggregateClient(rows);
        renderSummary(payload.summary);
        renderSankey(payload);
        renderTable(rows);
    }

    async function loadSankey() {
        if (state.loading) return;
        const startArea = ($('area-select') && $('area-select').value) || 'all';
        state.loading = true;
        setStatus('Loading snapshot…');
        $('load-btn').disabled = true;
        try {
            // Always load the full snapshot so area switching is client-side / instant.
            const res = await fetch('/api/rru-inventory/sankey?area=');
            const data = await res.json();
            if (!res.ok || !data.success) {
                throw new Error(data.error || 'Failed to load report');
            }
            state.rows = data.rows || [];
            populateAreaFilter(startArea);
            applyAreaFilterChange(state.areaFilter, true);
            $('results-panel').hidden = false;
            showWarnings(data.warnings || []);
            const built = data.built_at ? ` · snapshot ${data.built_at}` : '';
            setStatus(`Loaded ${state.rows.length} RRUs${built}`);
            if ($('export-btn')) $('export-btn').disabled = state.rows.length === 0;
            refreshStatus();
        } catch (err) {
            setStatus(err.message || String(err), true);
            if ($('export-btn')) $('export-btn').disabled = true;
        } finally {
            state.loading = false;
            $('load-btn').disabled = false;
        }
    }

    function downloadExcel() {
        const area = state.areaFilter || 'all';
        const url = '/api/rru-inventory/export?area=' + encodeURIComponent(area === 'all' ? '' : area);
        window.location.href = url;
    }

    function bindFilters() {
        const unused = $('show-unused');
        if (unused) {
            unused.addEventListener('change', function () {
                state.showUnused = !!unused.checked;
                refreshViews();
            });
        }
        const areaFilter = $('area-filter');
        if (areaFilter) {
            areaFilter.addEventListener('change', function () {
                applyAreaFilterChange(areaFilter.value || 'all', true);
            });
        }
        const areaLayer = $('sankey-area');
        if (areaLayer) {
            areaLayer.addEventListener('change', function () {
                state.showArea = !!areaLayer.checked;
                refreshViews();
            });
        }
        const techLayer = $('sankey-tech');
        if (techLayer) {
            techLayer.addEventListener('change', function () {
                state.showTech = !!techLayer.checked;
                syncLayerCheckboxes();
                refreshViews();
            });
        }
        const bandLayer = $('sankey-band');
        if (bandLayer) {
            bandLayer.addEventListener('change', function () {
                state.showBand = !!bandLayer.checked;
                refreshViews();
            });
        }
        const product = $('product-filter');
        if (product) {
            product.addEventListener('input', function () {
                state.productFilter = product.value || '';
                refreshViews();
            });
        }
        window.addEventListener('resize', function () {
            if (state.rows.length) refreshViews();
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        initConnectionPill();
        refreshStatus();
        renderTechFilters();
        syncLayerCheckboxes();
        bindFilters();
        loadAreas();
        const loadBtn = $('load-btn');
        const reloadBtn = $('reload-btn');
        const exportBtn = $('export-btn');
        const exportBtnResults = $('export-btn-results');
        if (loadBtn) loadBtn.addEventListener('click', loadSankey);
        if (reloadBtn) reloadBtn.addEventListener('click', loadSankey);
        if (exportBtn) exportBtn.addEventListener('click', downloadExcel);
        if (exportBtnResults) exportBtnResults.addEventListener('click', downloadExcel);
    });
})();
