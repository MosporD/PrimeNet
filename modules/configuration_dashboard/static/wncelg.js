(function () {
    'use strict';

    const STATUS_ORDER = ['Split', 'No split'];
    const STATUS_COLORS = {
        Split: '#c0392b',
        'No split': '#1e8449',
        area: '#5d6d7e',
        groups: '#2980b9',
        total: '#5d6d7e',
    };

    const state = {
        sites: [],
        areaFilter: 'all',
        areaOptions: [],
        networkView: false,
        showArea: true,
        showStatus: true,
        showGroups: true,
        enabledStatuses: new Set(STATUS_ORDER),
        siteFilter: '',
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

    function areaKey(value) {
        return String(value || '').trim().toLowerCase();
    }

    function statusLabel(status) {
        return String(status || '').toLowerCase() === 'split' ? 'Split' : 'No split';
    }

    function groupCountLabel(count) {
        const n = Number(count) || 0;
        if (n <= 1) return '1 group';
        if (n === 2) return '2 groups';
        return '3+ groups';
    }

    function setStatus(text, isError) {
        const el = $('wncelg-load-status');
        if (!el) return;
        el.textContent = text || '';
        el.style.color = isError ? '#c0392b' : '#566573';
    }

    function chip(text, cls) {
        return `<span class="summary-chip${cls ? ' ' + cls : ''}">${escapeHtml(text)}</span>`;
    }

    function initConnectionPill() {
        const pill = $('wncelg-config-status');
        const snapPill = $('wncelg-snapshot-status');
        const ready = document.body.dataset.wncelgSnapshotReady === 'true';
        const builtAt = document.body.dataset.wncelgBuiltAt || '';
        if (pill) {
            pill.classList.remove('ok', 'error');
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
            const res = await fetch('/api/configuration-dashboard/wncelg/status');
            const data = await res.json();
            if (!res.ok || !data.success) return;
            document.body.dataset.wncelgSnapshotReady = data.snapshot_ready ? 'true' : 'false';
            document.body.dataset.wncelgBuiltAt = data.built_at || '';
            initConnectionPill();
        } catch (_err) {
            /* ignore */
        }
    }

    async function loadAreas() {
        const select = $('wncelg-area-select');
        if (!select) return;
        try {
            const res = await fetch('/api/configuration-dashboard/wncelg/areas');
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
                const split = item.split_count != null ? `, ${item.split_count} split` : '';
                const count = item.site_count != null ? ` (${item.site_count} sites${split})` : '';
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

    function renderStatusFilters() {
        const host = $('wncelg-status-filters');
        if (!host) return;
        host.innerHTML = '';
        STATUS_ORDER.forEach(function (status) {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'tech-chip' + (state.enabledStatuses.has(status) ? ' active' : '');
            btn.textContent = status;
            btn.dataset.status = status;
            btn.addEventListener('click', function () {
                if (state.enabledStatuses.has(status)) {
                    state.enabledStatuses.delete(status);
                } else {
                    state.enabledStatuses.add(status);
                }
                btn.classList.toggle('active', state.enabledStatuses.has(status));
                refreshViews();
            });
            host.appendChild(btn);
        });
    }

    function siteVisible(site) {
        const wantArea = areaKey(state.areaFilter);
        if (wantArea && wantArea !== 'all' && areaKey(site.area) !== wantArea) return false;
        const label = statusLabel(site.status);
        if (!state.enabledStatuses.has(label)) return false;
        const needle = (state.siteFilter || '').trim().toLowerCase();
        if (needle) {
            const hay = [site.site_id, site.site_name, site.metadata_site_id].join(' ').toLowerCase();
            if (hay.indexOf(needle) === -1) return false;
        }
        return true;
    }

    function filteredSites() {
        return (state.sites || []).filter(siteVisible);
    }

    function populateAreaFilter(preferred) {
        const select = $('wncelg-area-filter');
        if (!select) return;
        const fromRows = Array.from(new Set(
            (state.sites || []).map(function (row) {
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
        const top = $('wncelg-area-select');
        if (top) {
            const topMatch = Array.from(top.options).find(function (opt) {
                return areaKey(opt.value) === areaKey(state.areaFilter);
            });
            if (topMatch) top.value = topMatch.value;
            else if (isAll) top.value = 'all';
        }
        refreshViews();
    }

    function syncLayerCheckboxes() {
        const areaEl = $('wncelg-sankey-area');
        const statusEl = $('wncelg-sankey-status');
        const groupsEl = $('wncelg-sankey-groups');
        if (areaEl) areaEl.checked = !!state.showArea;
        if (statusEl) statusEl.checked = !!state.showStatus;
        if (groupsEl) {
            groupsEl.checked = !!state.showGroups;
            // Leaf column stays on; toggling off collapses to Total/Status only via aggregate.
        }
    }

    function aggregateClient(sites) {
        const linkWeights = new Map();
        const nodeKinds = new Map();
        const showArea = !!state.showArea;
        const showStatus = !!state.showStatus;
        const showGroups = !!state.showGroups;
        const TOTAL_NODE = 'Total';

        function bump(src, tgt) {
            const key = src + '\0' + tgt;
            linkWeights.set(key, (linkWeights.get(key) || 0) + 1);
        }

        function addNode(name, kind) {
            nodeKinds.set(name, kind);
            return name;
        }

        let split = 0;
        let noSplit = 0;
        const byStatus = {};
        const byGroups = {};

        sites.forEach(function (site) {
            const status = addNode(statusLabel(site.status), 'status');
            const groups = addNode(groupCountLabel(site.group_count), 'groups');
            if (status === 'Split') split += 1;
            else noSplit += 1;
            byStatus[status] = (byStatus[status] || 0) + 1;
            byGroups[groups] = (byGroups[groups] || 0) + 1;

            if (showArea && showStatus && showGroups) {
                const area = addNode(site.area || 'Unknown', 'area');
                bump(area, status);
                bump(status, groups);
            } else if (!showArea && showStatus && showGroups) {
                bump(status, groups);
            } else if (showArea && !showStatus && showGroups) {
                const area = addNode(site.area || 'Unknown', 'area');
                bump(area, groups);
            } else if (showArea && showStatus && !showGroups) {
                const area = addNode(site.area || 'Unknown', 'area');
                bump(area, status);
            } else if (!showArea && showStatus && !showGroups) {
                addNode(TOTAL_NODE, 'total');
                bump(TOTAL_NODE, status);
            } else if (!showArea && !showStatus && showGroups) {
                addNode(TOTAL_NODE, 'total');
                bump(TOTAL_NODE, groups);
            } else if (showArea && !showStatus && !showGroups) {
                const area = addNode(site.area || 'Unknown', 'area');
                addNode(TOTAL_NODE, 'total');
                bump(area, TOTAL_NODE);
            } else {
                addNode(TOTAL_NODE, 'total');
                bump(TOTAL_NODE, addNode('Sites', 'groups'));
            }
        });

        const areas = showArea
            ? Array.from(nodeKinds.keys()).filter(function (n) {
                return nodeKinds.get(n) === 'area';
            }).sort()
            : [];
        const statuses = showStatus
            ? STATUS_ORDER.filter(function (s) {
                return nodeKinds.get(s) === 'status';
            })
            : [];
        const totals = Array.from(nodeKinds.keys()).filter(function (n) {
            return nodeKinds.get(n) === 'total';
        });
        const groupOrder = ['1 group', '2 groups', '3+ groups', 'Sites'];
        const groups = showGroups || (!showArea && !showStatus)
            ? groupOrder.filter(function (g) {
                return nodeKinds.get(g) === 'groups';
            }).concat(
                Array.from(nodeKinds.keys()).filter(function (n) {
                    return nodeKinds.get(n) === 'groups' && groupOrder.indexOf(n) === -1;
                })
            )
            : [];

        // When groups layer off but status on, status is the leaf.
        const leafKind = showGroups ? 'groups' : (showStatus ? 'status' : 'total');
        const leafTotals = new Map();
        linkWeights.forEach(function (weight, key) {
            const parts = key.split('\0');
            if (nodeKinds.get(parts[1]) === leafKind) {
                leafTotals.set(parts[1], (leafTotals.get(parts[1]) || 0) + weight);
            }
        });

        let ordered;
        if (showGroups) {
            ordered = totals.concat(areas, statuses, groups);
        } else if (showStatus) {
            ordered = totals.concat(areas, statuses);
        } else {
            ordered = areas.concat(totals);
        }

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
                total_sites: sites.length,
                split: split,
                no_split: noSplit,
                by_status: byStatus,
                by_groups: byGroups,
                areas: areas.length,
                group_buckets: groups.length,
            },
        };
    }

    function renderSummary(summary) {
        const host = $('wncelg-summary-strip');
        if (!host) return;
        const layers = [
            state.showArea ? 'Area' : null,
            state.showStatus ? 'Status' : null,
            state.showGroups ? 'Groups' : null,
        ].filter(Boolean).join(' → ') || 'Sites';
        host.innerHTML = [
            chip(`${summary.total_sites || 0} sites`),
            chip(`${summary.split || 0} split`, 'warn'),
            chip(`${summary.no_split || 0} no split`, 'ok'),
            chip(layers, 'muted'),
        ].join('');
    }

    function colorForNode(node) {
        if (node.kind === 'status') return STATUS_COLORS[node.name] || STATUS_COLORS.groups;
        if (node.kind === 'area' || node.kind === 'total') return STATUS_COLORS.area;
        return STATUS_COLORS.groups;
    }

    function renderSankey(payload) {
        const svgEl = $('wncelg-sankey-svg');
        const empty = $('wncelg-sankey-empty');
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
                if (src.kind === 'status') return STATUS_COLORS[src.name] || '#85929e';
                if (d.target.kind === 'status') return STATUS_COLORS[d.target.name] || '#85929e';
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

    function renderTable(sites) {
        const tbody = $('wncelg-tbody');
        if (!tbody) return;
        if (!sites.length) {
            tbody.innerHTML = '<tr><td colspan="6">No sites match the current filters.</td></tr>';
            return;
        }
        tbody.innerHTML = sites.map(function (site) {
            const status = site.status === 'split' ? 'split' : 'no_split';
            const label = status === 'split' ? 'Split' : 'No split';
            const instances = (site.instances || []).join(', ');
            const dns = (site.dns || []).map(function (dn) {
                return escapeHtml(dn);
            }).join('<br>');
            return (
                '<tr>' +
                `<td>${escapeHtml(site.area)}</td>` +
                `<td>${escapeHtml(site.site_name || site.site_id)}</td>` +
                `<td><span class="status-badge ${status}">${escapeHtml(label)}</span></td>` +
                `<td>${escapeHtml(site.group_count)}</td>` +
                `<td class="mono">${escapeHtml(instances)}</td>` +
                `<td class="mono">${dns}</td>` +
                '</tr>'
            );
        }).join('');
    }

    function showWarnings(warnings) {
        const box = $('wncelg-results-warnings');
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
        const sites = filteredSites();
        const payload = aggregateClient(sites);
        renderSummary(payload.summary);
        renderSankey(payload);
        renderTable(sites);
    }

    async function loadSites() {
        if (state.loading) return;
        const startArea = ($('wncelg-area-select') && $('wncelg-area-select').value) || 'all';
        state.loading = true;
        setStatus('Loading snapshot…');
        if ($('wncelg-load-btn')) $('wncelg-load-btn').disabled = true;
        try {
            const res = await fetch('/api/configuration-dashboard/wncelg/sites');
            const data = await res.json();
            if (!res.ok || !data.success) {
                throw new Error(data.error || 'Failed to load WNCELG report');
            }
            state.sites = data.sites || [];
            populateAreaFilter(startArea);
            applyAreaFilterChange(state.areaFilter, true);
            if ($('wncelg-results-panel')) $('wncelg-results-panel').hidden = false;
            showWarnings(data.warnings || []);
            const built = data.built_at ? ` · snapshot ${data.built_at}` : '';
            setStatus(`Loaded ${state.sites.length} sites${built}`);
            if ($('wncelg-export-btn')) $('wncelg-export-btn').disabled = state.sites.length === 0;
            refreshStatus();
        } catch (err) {
            setStatus(err.message || String(err), true);
            if ($('wncelg-export-btn')) $('wncelg-export-btn').disabled = true;
        } finally {
            state.loading = false;
            if ($('wncelg-load-btn')) $('wncelg-load-btn').disabled = false;
        }
    }

    function downloadExcel() {
        const area = state.areaFilter || 'all';
        const params = new URLSearchParams();
        if (area && area !== 'all') params.set('area', area);
        const enabled = Array.from(state.enabledStatuses);
        if (enabled.length === 1) {
            params.set('status', enabled[0] === 'Split' ? 'split' : 'no_split');
        }
        window.location.href = '/api/configuration-dashboard/wncelg/export?' + params.toString();
    }

    function bindFilters() {
        const areaFilter = $('wncelg-area-filter');
        if (areaFilter) {
            areaFilter.addEventListener('change', function () {
                applyAreaFilterChange(areaFilter.value || 'all', true);
            });
        }
        const areaLayer = $('wncelg-sankey-area');
        if (areaLayer) {
            areaLayer.addEventListener('change', function () {
                state.showArea = !!areaLayer.checked;
                refreshViews();
            });
        }
        const statusLayer = $('wncelg-sankey-status');
        if (statusLayer) {
            statusLayer.addEventListener('change', function () {
                state.showStatus = !!statusLayer.checked;
                refreshViews();
            });
        }
        const groupsLayer = $('wncelg-sankey-groups');
        if (groupsLayer) {
            groupsLayer.addEventListener('change', function () {
                state.showGroups = !!groupsLayer.checked;
                refreshViews();
            });
        }
        const siteFilter = $('wncelg-site-filter');
        if (siteFilter) {
            siteFilter.addEventListener('input', function () {
                state.siteFilter = siteFilter.value || '';
                refreshViews();
            });
        }
        window.addEventListener('resize', function () {
            if (state.sites.length) refreshViews();
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        initConnectionPill();
        refreshStatus();
        renderStatusFilters();
        syncLayerCheckboxes();
        bindFilters();
        loadAreas();
        const loadBtn = $('wncelg-load-btn');
        const reloadBtn = $('wncelg-reload-btn');
        const exportBtn = $('wncelg-export-btn');
        const exportBtnResults = $('wncelg-export-btn-results');
        if (loadBtn) loadBtn.addEventListener('click', loadSites);
        if (reloadBtn) reloadBtn.addEventListener('click', loadSites);
        if (exportBtn) exportBtn.addEventListener('click', downloadExcel);
        if (exportBtnResults) exportBtnResults.addEventListener('click', downloadExcel);
    });
})();
