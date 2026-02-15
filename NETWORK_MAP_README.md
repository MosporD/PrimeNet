# Network Map Feature

## Overview
The Network Map feature provides an interactive visualization of your telecom network sites, sectors, and cells with real-time KPI monitoring.

## Features
- **Interactive Map**: Visual representation of all network sites on an OpenStreetMap
- **Sector Visualization**: Color-coded sectors showing direction (azimuth) and coverage area
- **KPI Dashboard**: Real-time performance metrics for each cell
- **Search & Filter**: Find sites by name/ID or filter by region
- **Network Statistics**: Overview of total sites, sectors, cells, and availability

## Database Schema

### Tables Created
1. **sites**: Network site locations
   - site_id, site_name, latitude, longitude, region, site_type, status

2. **sectors**: Cell sectors with direction
   - sector_id, site_id, sector_name, azimuth, beamwidth, technology, frequency_band, status

3. **cells**: Individual cells per sector
   - cell_id, cell_name, sector_id, pci, tac, status

4. **cell_kpis**: Performance metrics
   - cell_id, avg_users, data_volume_gb, rsrp, rsrq, sinr, cqi, throughput_dl_mbps, throughput_ul_mbps, rrc_success_rate, erab_success_rate, call_drop_rate, handover_success_rate, availability_percent, timestamp

## API Endpoints

### GET /api/map/sites
Returns all active network sites

### GET /api/map/site/<site_id>
Returns detailed site information including sectors

### GET /api/map/sector/<sector_id>/kpis
Returns KPI data for all cells in a sector

### POST /api/map/site (Admin only)
Add a new site to the network

### POST /api/map/sector (Admin only)
Add a new sector to a site

### GET /api/map/stats
Returns overall network statistics

## Sample Data
A sample dataset has been created for Amman, Jordan with:
- 8 sites across different regions
- 24 sectors (3 per site)
- 52 cells with realistic KPIs
- Mix of 5G and LTE technologies

### Generating Sample Data
```bash
python add_sample_map_data.py
```

## Usage

### Viewing the Map
1. Login to the application
2. Click on "Network Map" tab (🗺️)
3. The map will load showing all sites

### Viewing Site Details
1. Click on any site marker (📡)
2. Sectors will appear as colored overlays
3. Site information panel shows on the right

### Viewing KPIs
1. Click on a colored sector overlay
2. Or click "View KPIs" in the sector popup
3. KPI dashboard modal opens showing:
   - Active users
   - Data volume
   - Signal quality (RSRP, RSRQ, SINR)
   - Throughput
   - Success rates
   - Availability

### Search & Filter
- Use the search box to find sites by name or ID
- Use the region filter to show sites in specific regions
- The map automatically adjusts to show filtered results

## Sector Colors
- **Purple**: 5G sites
- **Blue**: LTE sites
- **Green**: 3G sites (if present)
- **Gray**: 2G sites (if present)

## KPI Thresholds
The dashboard uses color coding for KPIs:
- **Green**: Good performance
- **Orange**: Acceptable performance
- **Red**: Poor performance requiring attention

### Thresholds
- RSRP: Good > -80 dBm, Bad < -100 dBm
- RSRQ: Good > -10 dB, Bad < -15 dB
- SINR: Good > 15 dB, Bad < 5 dB
- RRC Success Rate: Good > 98%, Bad < 95%
- Call Drop Rate: Good < 0.5%, Bad > 2%
- Availability: Good > 99%, Bad < 95%

## OSS Integration

### Production Deployment
This feature is designed to integrate with your OSS (Operations Support System) for real-time data.

### Data Import Steps
1. Use the POST endpoints to add sites/sectors programmatically
2. Schedule periodic KPI updates from OSS
3. Update cell_kpis table with latest measurements

### Example Integration Script
```python
import requests

# Add a new site
site_data = {
    'site_id': 'NEW_001',
    'site_name': 'New Site',
    'latitude': 31.9539,
    'longitude': 35.9106,
    'region': 'Amman',
    'site_type': 'Macro',
    'status': 'Active'
}
response = requests.post('http://your-server/api/map/site', json=site_data)

# Add sectors and cells similarly
```

## Files Created
1. `add_map_tables.py` - Database schema creation
2. `add_sample_map_data.py` - Sample data generator
3. `static/js/map.js` - Frontend map logic
4. `static/css/style.css` - Map styling (appended)
5. API endpoints in `app_enhanced.py`

## Browser Support
- Chrome/Edge (recommended)
- Firefox
- Safari

## Mobile Responsive
The map interface is fully responsive and works on tablets and mobile devices.

## Dark Mode Support
The map includes dark mode theming that activates when the user enables dark mode.

## Future Enhancements
- Historical KPI trending
- Alarm integration
- Heat maps for coverage
- Neighbor cell relationships
- Automated OSS sync
- Export functionality
- Advanced filtering (technology, band, status)

## Troubleshooting

### Map not loading
- Clear browser cache (Ctrl+Shift+R)
- Check console for JavaScript errors
- Verify Leaflet.js is loading (check network tab)

### No data showing
- Verify sample data was imported: `python add_sample_map_data.py`
- Check database: `SELECT COUNT(*) FROM sites;`

### KPI modal not opening
- Check browser console for errors
- Verify sector has associated cells in database
- Ensure user is logged in

## Support
For issues or questions, check the application logs in the console.
