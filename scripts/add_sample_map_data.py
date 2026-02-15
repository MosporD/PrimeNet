"""
Add sample network data for testing the Network Map
This script creates sample sites, sectors, cells, and KPIs for demonstration
"""

import sqlite3
import random
from datetime import datetime

DATABASE = 'ncm_users.db'

def generate_sample_data():
    """Generate sample network data for Amman, Jordan region"""

    # Sample sites around Amman
    sites = [
        {
            'site_id': 'AMM_001',
            'site_name': 'Abdali Tower',
            'latitude': 31.9624,
            'longitude': 35.9153,
            'region': 'Amman Center',
            'site_type': 'Macro'
        },
        {
            'site_id': 'AMM_002',
            'site_name': 'Sweifieh Mall',
            'latitude': 31.9398,
            'longitude': 35.8515,
            'region': 'Amman West',
            'site_type': 'Macro'
        },
        {
            'site_id': 'AMM_003',
            'site_name': 'University Street',
            'latitude': 32.0110,
            'longitude': 35.8706,
            'region': 'Amman North',
            'site_type': 'Macro'
        },
        {
            'site_id': 'AMM_004',
            'site_name': 'Mecca Street Hub',
            'latitude': 31.9286,
            'longitude': 35.9040,
            'region': 'Amman South',
            'site_type': 'Macro'
        },
        {
            'site_id': 'AMM_005',
            'site_name': 'Downtown Center',
            'latitude': 31.9540,
            'longitude': 35.9450,
            'region': 'Amman Center',
            'site_type': 'Micro'
        },
        {
            'site_id': 'AMM_006',
            'site_name': 'Sports City',
            'latitude': 31.9870,
            'longitude': 35.8960,
            'region': 'Amman North',
            'site_type': 'Macro'
        },
        {
            'site_id': 'AMM_007',
            'site_name': 'Abdoun Circle',
            'latitude': 31.9480,
            'longitude': 35.8790,
            'region': 'Amman West',
            'site_type': 'Micro'
        },
        {
            'site_id': 'AMM_008',
            'site_name': 'Queen Alia Airport',
            'latitude': 31.7227,
            'longitude': 35.9932,
            'region': 'Airport Zone',
            'site_type': 'Macro'
        }
    ]

    # Generate sectors for each site (3 sectors per site with 120° separation)
    sectors = []
    cells = []
    kpis = []

    technologies = ['5G', 'LTE', 'LTE']  # More LTE than 5G
    frequency_bands = {
        '5G': ['n78 (3.5GHz)', 'n1 (2.1GHz)'],
        'LTE': ['B3 (1800MHz)', 'B7 (2600MHz)', 'B20 (800MHz)']
    }

    for site in sites:
        site_id = site['site_id']

        # Each site has 3 sectors
        for sector_num in range(1, 4):
            tech = random.choice(technologies)
            sector_id = f"{site_id}_S{sector_num}"
            azimuth = (sector_num - 1) * 120  # 0°, 120°, 240°

            sector = {
                'sector_id': sector_id,
                'site_id': site_id,
                'sector_name': f"{site['site_name']}-S{sector_num}",
                'azimuth': azimuth,
                'beamwidth': 65,
                'technology': tech,
                'frequency_band': random.choice(frequency_bands[tech]),
                'status': 'Active'
            }
            sectors.append(sector)

            # Each sector has 1-3 cells depending on technology
            num_cells = 3 if tech == '5G' else 2

            for cell_num in range(1, num_cells + 1):
                cell_id = f"{sector_id}_C{cell_num}"
                pci = random.randint(0, 503)
                tac = random.randint(1000, 9999)

                cell = {
                    'cell_id': cell_id,
                    'cell_name': f"{sector['sector_name']}-C{cell_num}",
                    'sector_id': sector_id,
                    'pci': pci,
                    'tac': tac,
                    'status': 'Active'
                }
                cells.append(cell)

                # Generate realistic KPIs for each cell
                kpi = {
                    'cell_id': cell_id,
                    'avg_users': random.randint(50, 300),
                    'data_volume_gb': round(random.uniform(500, 2000), 2),
                    'rsrp': round(random.uniform(-95, -70), 1),
                    'rsrq': round(random.uniform(-14, -8), 1),
                    'sinr': round(random.uniform(5, 25), 1),
                    'cqi': round(random.uniform(7, 14), 1),
                    'throughput_dl_mbps': round(random.uniform(30, 150), 1),
                    'throughput_ul_mbps': round(random.uniform(10, 50), 1),
                    'rrc_success_rate': round(random.uniform(96, 99.5), 2),
                    'erab_success_rate': round(random.uniform(95, 99), 2),
                    'call_drop_rate': round(random.uniform(0.1, 2.5), 2),
                    'handover_success_rate': round(random.uniform(97, 99.8), 2),
                    'availability_percent': round(random.uniform(98, 100), 2)
                }
                kpis.append(kpi)

    return sites, sectors, cells, kpis

def insert_sample_data():
    """Insert sample data into the database"""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    print("Generating sample network data...")
    sites, sectors, cells, kpis = generate_sample_data()

    print(f"Inserting {len(sites)} sites...")
    for site in sites:
        try:
            cursor.execute('''
                INSERT INTO sites (site_id, site_name, latitude, longitude, region, site_type, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                site['site_id'],
                site['site_name'],
                site['latitude'],
                site['longitude'],
                site['region'],
                site['site_type'],
                'Active'
            ))
        except sqlite3.IntegrityError:
            print(f"  [SKIP] Site {site['site_id']} already exists")

    print(f"Inserting {len(sectors)} sectors...")
    for sector in sectors:
        try:
            cursor.execute('''
                INSERT INTO sectors (sector_id, site_id, sector_name, azimuth, beamwidth,
                                   technology, frequency_band, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                sector['sector_id'],
                sector['site_id'],
                sector['sector_name'],
                sector['azimuth'],
                sector['beamwidth'],
                sector['technology'],
                sector['frequency_band'],
                sector['status']
            ))
        except sqlite3.IntegrityError:
            print(f"  [SKIP] Sector {sector['sector_id']} already exists")

    print(f"Inserting {len(cells)} cells...")
    for cell in cells:
        try:
            cursor.execute('''
                INSERT INTO cells (cell_id, cell_name, sector_id, pci, tac, status)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                cell['cell_id'],
                cell['cell_name'],
                cell['sector_id'],
                cell['pci'],
                cell['tac'],
                cell['status']
            ))
        except sqlite3.IntegrityError:
            print(f"  [SKIP] Cell {cell['cell_id']} already exists")

    print(f"Inserting {len(kpis)} KPI records...")
    for kpi in kpis:
        cursor.execute('''
            INSERT INTO cell_kpis (cell_id, avg_users, data_volume_gb, rsrp, rsrq, sinr, cqi,
                                 throughput_dl_mbps, throughput_ul_mbps, rrc_success_rate,
                                 erab_success_rate, call_drop_rate, handover_success_rate,
                                 availability_percent)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            kpi['cell_id'],
            kpi['avg_users'],
            kpi['data_volume_gb'],
            kpi['rsrp'],
            kpi['rsrq'],
            kpi['sinr'],
            kpi['cqi'],
            kpi['throughput_dl_mbps'],
            kpi['throughput_ul_mbps'],
            kpi['rrc_success_rate'],
            kpi['erab_success_rate'],
            kpi['call_drop_rate'],
            kpi['handover_success_rate'],
            kpi['availability_percent']
        ))

    conn.commit()
    print("[OK] Sample data inserted successfully!")

    # Print summary
    cursor.execute('SELECT COUNT(*) FROM sites WHERE status = "Active"')
    total_sites = cursor.fetchone()[0]

    cursor.execute('SELECT COUNT(*) FROM sectors WHERE status = "Active"')
    total_sectors = cursor.fetchone()[0]

    cursor.execute('SELECT COUNT(*) FROM cells WHERE status = "Active"')
    total_cells = cursor.fetchone()[0]

    print(f"\n=== Network Summary ===")
    print(f"Total Sites: {total_sites}")
    print(f"Total Sectors: {total_sectors}")
    print(f"Total Cells: {total_cells}")
    print(f"======================\n")

    conn.close()

if __name__ == '__main__':
    insert_sample_data()
    print("Sample data is ready! You can now test the Network Map feature.")
    print("Note: This data will be replaced when OSS integration is configured.")
