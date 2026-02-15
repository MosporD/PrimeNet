/**
 * Network Map Visualization with Leaflet
 * Displays sites, sectors, and KPIs
 */

let map = null;
let sitesData = [];
let siteMarkers = [];
let sectorOverlays = [];

// Default map center (will be adjusted based on site locations)
const DEFAULT_CENTER = [31.9539, 35.9106]; // Amman, Jordan
const DEFAULT_ZOOM = 10;

/**
 * Initialize the map when the tab is opened
 */
function initializeMap() {
    if (map) {
        map.invalidateSize();
        return;
    }

    // Initialize Leaflet map
    map = L.map('network-map').setView(DEFAULT_CENTER, DEFAULT_ZOOM);

    // Add OpenStreetMap tiles
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© OpenStreetMap contributors',
        maxZoom: 18
    }).addTo(map);

    // Load sites data
    loadNetworkSites();
    loadNetworkStats();
}

/**
 * Load all network sites from the API
 */
async function loadNetworkSites() {
    try {
        const response = await fetch('/api/map/sites');
        const data = await response.json();

        if (data.success) {
            sitesData = data.sites;
            displaySites(sitesData);

            // Update sites count
            document.getElementById('sites-count').textContent = sitesData.length;

            // Auto-fit map to show all sites
            if (sitesData.length > 0) {
                const bounds = sitesData.map(site => [site.latitude, site.longitude]);
                map.fitBounds(bounds, { padding: [50, 50] });
            }
        }
    } catch (error) {
        console.error('Error loading sites:', error);
        showNotification('Failed to load network sites', 'error');
    }
}

/**
 * Display sites on the map
 */
function displaySites(sites) {
    // Clear existing markers
    siteMarkers.forEach(marker => map.removeLayer(marker));
    siteMarkers = [];

    sites.forEach(site => {
        // Create custom icon based on site type
        const icon = L.divIcon({
            className: 'site-marker',
            html: `<div class="site-marker-inner" title="${site.site_name}">
                    <div class="site-icon">📡</div>
                   </div>`,
            iconSize: [40, 40],
            iconAnchor: [20, 20]
        });

        // Add marker
        const marker = L.marker([site.latitude, site.longitude], { icon: icon })
            .addTo(map);

        // Add click handler to show site details
        marker.on('click', () => showSiteDetails(site.site_id));

        siteMarkers.push(marker);
    });
}

/**
 * Show detailed information about a site including sectors
 */
async function showSiteDetails(siteId) {
    try {
        const response = await fetch(`/api/map/site/${siteId}`);
        const data = await response.json();

        if (data.success) {
            const site = data.site;

            // Clear existing sector overlays
            sectorOverlays.forEach(overlay => map.removeLayer(overlay));
            sectorOverlays = [];

            // Display sectors
            site.sectors.forEach(sector => {
                drawSectorOverlay(site, sector);
            });

            // Show site info panel
            displaySiteInfo(site);
        }
    } catch (error) {
        console.error('Error loading site details:', error);
        showNotification('Failed to load site details', 'error');
    }
}

/**
 * Draw sector direction overlay on the map
 */
function drawSectorOverlay(site, sector) {
    const sectorRadius = 0.005; // Approx 500m in degrees
    const azimuth = sector.azimuth || 0;
    const beamwidth = sector.beamwidth || 65;

    // Calculate sector arc points
    const startAngle = azimuth - (beamwidth / 2);
    const endAngle = azimuth + (beamwidth / 2);

    const points = [[site.latitude, site.longitude]];

    // Generate arc points
    for (let angle = startAngle; angle <= endAngle; angle += 5) {
        const rad = (angle * Math.PI) / 180;
        const lat = site.latitude + sectorRadius * Math.cos(rad);
        const lng = site.longitude + sectorRadius * Math.sin(rad);
        points.push([lat, lng]);
    }

    points.push([site.latitude, site.longitude]);

    // Color based on technology
    const colors = {
        '5G': '#9b59b6',
        'LTE': '#3498db',
        '3G': '#27ae60',
        '2G': '#95a5a6'
    };
    const color = colors[sector.technology] || '#34495e';

    // Draw sector polygon
    const polygon = L.polygon(points, {
        color: color,
        fillColor: color,
        fillOpacity: 0.3,
        weight: 2
    }).addTo(map);

    // Add click handler to show KPIs
    polygon.on('click', (e) => {
        L.DomEvent.stopPropagation(e);
        showSectorKPIs(sector.sector_id);
    });

    // Add popup with sector info
    polygon.bindPopup(`
        <div style="text-align: center;">
            <strong>${sector.sector_name}</strong><br>
            Technology: ${sector.technology || 'N/A'}<br>
            Band: ${sector.frequency_band || 'N/A'}<br>
            Azimuth: ${azimuth}°<br>
            <button onclick="showSectorKPIs('${sector.sector_id}')"
                    style="margin-top: 8px; padding: 5px 15px; background: #3498db;
                           color: white; border: none; border-radius: 5px; cursor: pointer;">
                View KPIs
            </button>
        </div>
    `);

    sectorOverlays.push(polygon);
}

/**
 * Display site information in the info panel
 */
function displaySiteInfo(site) {
    const infoPanel = document.getElementById('site-info-panel');

    let sectorsHtml = '<div style="margin-top: 10px;">';
    site.sectors.forEach(sector => {
        sectorsHtml += `
            <div style="padding: 8px; background: #f8f9fa; margin: 5px 0; border-radius: 5px; cursor: pointer;"
                 onclick="showSectorKPIs('${sector.sector_id}')">
                <strong>${sector.sector_name}</strong> - ${sector.technology || 'N/A'}<br>
                <small>Azimuth: ${sector.azimuth}° | Band: ${sector.frequency_band || 'N/A'}</small>
            </div>
        `;
    });
    sectorsHtml += '</div>';

    infoPanel.innerHTML = `
        <h3 style="margin: 0 0 15px 0; color: #2C3E50;">📡 ${site.site_name}</h3>
        <p style="margin: 5px 0;"><strong>Site ID:</strong> ${site.site_id}</p>
        <p style="margin: 5px 0;"><strong>Region:</strong> ${site.region || 'N/A'}</p>
        <p style="margin: 5px 0;"><strong>Type:</strong> ${site.site_type || 'N/A'}</p>
        <p style="margin: 5px 0;"><strong>Sectors:</strong> ${site.sectors.length}</p>
        ${sectorsHtml}
        <a href="/performance?site_id=${site.site_id}"
           style="display:block; margin-top:14px; padding:10px; text-align:center;
                  background:#3498db; color:white; border-radius:6px;
                  text-decoration:none; font-weight:600; font-size:0.9em;">
            📈 In-depth KPI
        </a>
    `;
    infoPanel.style.display = 'block';
}

/**
 * Show KPI dashboard for a sector
 */
async function showSectorKPIs(sectorId) {
    try {
        const response = await fetch(`/api/map/sector/${sectorId}/kpis`);
        const data = await response.json();

        if (data.success) {
            displayKPIDashboard(data.sector);
        }
    } catch (error) {
        console.error('Error loading sector KPIs:', error);
        showNotification('Failed to load KPI data', 'error');
    }
}

/**
 * Display KPI dashboard modal
 */
function displayKPIDashboard(sector) {
    const modal = document.getElementById('kpi-modal');
    const content = document.getElementById('kpi-content');

    let cellsHtml = '';

    sector.cells.forEach(cell => {
        const kpis = cell.kpis;

        if (!kpis) {
            cellsHtml += `
                <div class="kpi-cell-card">
                    <h4>${cell.cell_name}</h4>
                    <p style="color: #95a5a6;">No KPI data available</p>
                </div>
            `;
            return;
        }

        // Determine status colors
        const getStatusColor = (value, goodThreshold, badThreshold, inverse = false) => {
            if (!value) return '#95a5a6';
            if (inverse) {
                return value < goodThreshold ? '#27ae60' : value > badThreshold ? '#e74c3c' : '#f39c12';
            } else {
                return value > goodThreshold ? '#27ae60' : value < badThreshold ? '#e74c3c' : '#f39c12';
            }
        };

        cellsHtml += `
            <div class="kpi-cell-card">
                <h4>${cell.cell_name} <span style="font-size: 0.8em; color: #7f8c8d;">(PCI: ${cell.pci || 'N/A'})</span></h4>

                <div class="kpi-grid">
                    <div class="kpi-item">
                        <div class="kpi-label">Users</div>
                        <div class="kpi-value">${kpis.avg_users || 0}</div>
                    </div>

                    <div class="kpi-item">
                        <div class="kpi-label">Data (GB)</div>
                        <div class="kpi-value">${(kpis.data_volume_gb || 0).toFixed(2)}</div>
                    </div>

                    <div class="kpi-item">
                        <div class="kpi-label">RSRP (dBm)</div>
                        <div class="kpi-value" style="color: ${getStatusColor(kpis.rsrp, -80, -100)}">
                            ${kpis.rsrp ? kpis.rsrp.toFixed(1) : 'N/A'}
                        </div>
                    </div>

                    <div class="kpi-item">
                        <div class="kpi-label">RSRQ (dB)</div>
                        <div class="kpi-value" style="color: ${getStatusColor(kpis.rsrq, -10, -15)}">
                            ${kpis.rsrq ? kpis.rsrq.toFixed(1) : 'N/A'}
                        </div>
                    </div>

                    <div class="kpi-item">
                        <div class="kpi-label">SINR (dB)</div>
                        <div class="kpi-value" style="color: ${getStatusColor(kpis.sinr, 15, 5)}">
                            ${kpis.sinr ? kpis.sinr.toFixed(1) : 'N/A'}
                        </div>
                    </div>

                    <div class="kpi-item">
                        <div class="kpi-label">Throughput DL</div>
                        <div class="kpi-value">${kpis.throughput_dl_mbps ? kpis.throughput_dl_mbps.toFixed(1) + ' Mbps' : 'N/A'}</div>
                    </div>

                    <div class="kpi-item">
                        <div class="kpi-label">RRC Success</div>
                        <div class="kpi-value" style="color: ${getStatusColor(kpis.rrc_success_rate, 98, 95)}">
                            ${kpis.rrc_success_rate ? kpis.rrc_success_rate.toFixed(2) + '%' : 'N/A'}
                        </div>
                    </div>

                    <div class="kpi-item">
                        <div class="kpi-label">Call Drop Rate</div>
                        <div class="kpi-value" style="color: ${getStatusColor(kpis.call_drop_rate, 0.5, 2, true)}">
                            ${kpis.call_drop_rate ? kpis.call_drop_rate.toFixed(2) + '%' : 'N/A'}
                        </div>
                    </div>

                    <div class="kpi-item">
                        <div class="kpi-label">Availability</div>
                        <div class="kpi-value" style="color: ${getStatusColor(kpis.availability_percent, 99, 95)}">
                            ${kpis.availability_percent ? kpis.availability_percent.toFixed(2) + '%' : 'N/A'}
                        </div>
                    </div>
                </div>

                <div style="margin-top: 10px; font-size: 0.85em; color: #7f8c8d;">
                    Last updated: ${kpis.timestamp ? new Date(kpis.timestamp).toLocaleString() : 'N/A'}
                </div>
            </div>
        `;
    });

    content.innerHTML = `
        <h2 style="margin-top: 0; color: #2C3E50;">
            ${sector.sector_name} - KPI Dashboard
        </h2>
        <div style="margin-bottom: 15px; padding: 10px; background: #ecf0f1; border-radius: 5px;
                    display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px;">
            <span>
                <strong>Site:</strong> ${sector.site_name} |
                <strong>Technology:</strong> ${sector.technology || 'N/A'} |
                <strong>Band:</strong> ${sector.frequency_band || 'N/A'} |
                <strong>Azimuth:</strong> ${sector.azimuth}°
            </span>
            <a href="/performance?site_id=${sector.site_id}&technology=${sector.technology || ''}"
               style="padding:8px 18px; background:#3498db; color:white; border-radius:6px;
                      text-decoration:none; font-weight:600; font-size:0.88em; white-space:nowrap;">
                📈 In-depth KPI
            </a>
        </div>
        ${cellsHtml}
    `;

    modal.style.display = 'flex';
}

/**
 * Close KPI modal
 */
function closeKPIModal() {
    document.getElementById('kpi-modal').style.display = 'none';
}

/**
 * Load network statistics
 */
async function loadNetworkStats() {
    try {
        const response = await fetch('/api/map/stats');
        const data = await response.json();

        if (data.success) {
            const stats = data.stats;
            document.getElementById('sites-count').textContent = stats.total_sites;
            document.getElementById('sectors-count').textContent = stats.total_sectors;
            document.getElementById('cells-count').textContent = stats.total_cells;
            document.getElementById('availability-percent').textContent = stats.avg_availability.toFixed(2) + '%';
        }
    } catch (error) {
        console.error('Error loading stats:', error);
    }
}

/**
 * Search sites by name or ID
 */
function searchSites() {
    const searchTerm = document.getElementById('site-search').value.toLowerCase();

    if (!searchTerm) {
        displaySites(sitesData);
        return;
    }

    const filtered = sitesData.filter(site =>
        site.site_name.toLowerCase().includes(searchTerm) ||
        site.site_id.toLowerCase().includes(searchTerm)
    );

    displaySites(filtered);

    if (filtered.length > 0) {
        const bounds = filtered.map(site => [site.latitude, site.longitude]);
        map.fitBounds(bounds, { padding: [50, 50] });
    }
}

/**
 * Filter sites by region
 */
function filterByRegion() {
    const region = document.getElementById('region-filter').value;

    if (region === 'all') {
        displaySites(sitesData);
        return;
    }

    const filtered = sitesData.filter(site => site.region === region);
    displaySites(filtered);

    if (filtered.length > 0) {
        const bounds = filtered.map(site => [site.latitude, site.longitude]);
        map.fitBounds(bounds, { padding: [50, 50] });
    }
}

// Close modal when clicking outside
window.onclick = function(event) {
    const modal = document.getElementById('kpi-modal');
    if (event.target === modal) {
        closeKPIModal();
    }
}
