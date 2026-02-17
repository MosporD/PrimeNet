"""
Add sample network data for testing the Performance module and Network Map.

Three-database architecture:
  metadata.db  → sites + cells  (the performance module queries this)
  nokia_pm.db  → Nokia hourly KPIs keyed by cell_name + timestamp
  huawei_pm.db → Huawei hourly KPIs keyed by cell_name + timestamp

Run:
    python scripts/add_sample_map_data.py
"""

import sqlite3
import random
import os
import sys
from datetime import datetime, timedelta

# Use canonical paths from sync_config
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sync_config import METADATA_DB, NOKIA_PM_DB, HUAWEI_PM_DB

# First, ensure DB schemas exist
from sync.db_migration import run_migrations
run_migrations()


# ── Sample sites around Amman ───────────────────────────────────────────────

# site_id must be numeric so cluster = floor(site_id/100) maps to CLUSTER_AREA.
# Cluster 3 → East Amman,  Cluster 2 → West Amman,  Cluster 1 → South Amman,
# Cluster 4 → North Jordan, Cluster 7 → South Jordan, Cluster 10 → East Jordan
SITES = [
    {'site_id': '305',  'site_name': 'Abdali Tower',       'latitude': 31.9624, 'longitude': 35.9153, 'site_type': 'Macro', 'vendor': 'Nokia'},
    {'site_id': '210',  'site_name': 'Sweifieh Mall',      'latitude': 31.9398, 'longitude': 35.8515, 'site_type': 'Macro', 'vendor': 'Nokia'},
    {'site_id': '415',  'site_name': 'University Street',  'latitude': 32.0110, 'longitude': 35.8706, 'site_type': 'Macro', 'vendor': 'Nokia'},
    {'site_id': '120',  'site_name': 'Mecca Street Hub',   'latitude': 31.9286, 'longitude': 35.9040, 'site_type': 'Macro', 'vendor': 'Nokia'},
    {'site_id': '325',  'site_name': 'Downtown Center',    'latitude': 31.9540, 'longitude': 35.9450, 'site_type': 'Micro', 'vendor': 'Huawei'},
    {'site_id': '1022', 'site_name': 'Sports City',        'latitude': 31.9870, 'longitude': 35.8960, 'site_type': 'Macro', 'vendor': 'Huawei'},
    {'site_id': '215',  'site_name': 'Abdoun Circle',      'latitude': 31.9480, 'longitude': 35.8790, 'site_type': 'Micro', 'vendor': 'Huawei'},
    {'site_id': '730',  'site_name': 'Queen Alia Airport', 'latitude': 31.7227, 'longitude': 35.9932, 'site_type': 'Macro', 'vendor': 'Nokia'},
]

# Technology distribution per vendor
NOKIA_TECHS   = ['2G', '3G', '4G', '5G']
HUAWEI_TECHS  = ['2G', '3G', '4G']

FREQ_BANDS = {
    '2G': ['900MHz', '1800MHz'],
    '3G': ['2100MHz'],
    '4G': ['B3 (1800MHz)', 'B7 (2600MHz)', 'B20 (800MHz)'],
    '5G': ['n78 (3.5GHz)', 'n1 (2.1GHz)'],
}


def _random_kpi_row(cell_name, ts_str, technology):
    """Return a dict of realistic KPI values for one hourly sample."""
    base = {
        'cell_name': cell_name,
        'timestamp': ts_str,
    }
    if technology in ('4G', '5G'):
        base.update({
            'Avg act UEs DL':                            random.randint(10, 300),
            'PDCP SDU Volume, DL (GB)':                  round(random.uniform(0.5, 20), 2),
            'Average CQI':                               round(random.uniform(7, 14), 1),
            'Avg PDCP cell thp DL (Mbps)':               round(random.uniform(30, 150), 1),
            'Avg PDCP cell thp UL (Mbps)':               round(random.uniform(5, 50), 1),
            'Total E-UTRAN RRC conn stp SR':             round(random.uniform(96, 99.9), 2),
            'E-UTRAN E-RAB stp SR':                      round(random.uniform(95, 99.5), 2),
            'E-UTRAN E-RAB Drop Ratio, User Perspective':round(random.uniform(0.05, 2.5), 2),
            'E-UTRAN Intra-Freq HO SR':                  round(random.uniform(96, 99.8), 2),
            'Cell Avail':                                round(random.uniform(97, 100), 2),
        })
    elif technology == '3G':
        base.update({
            'Average number of simultaneous HSDPA users': random.randint(5, 150),
            'Avg reported CQI':                           round(random.uniform(7, 14), 1),
            'HSDPA Cell thp':                             round(random.uniform(2, 20), 1),
            'Active  HSUPA cell thp':                     round(random.uniform(1, 10), 1),
            'RRC Success Rate (Total)(%)':                round(random.uniform(96, 99.9), 2),
            'AMR Call Drop Ratio(%)':                     round(random.uniform(0.1, 3.0), 2),
            'Soft HO Success rate, RT':                   round(random.uniform(96, 99.8), 2),
            'Cell Availability':                          round(random.uniform(97, 100), 2),
        })
    else:  # 2G
        base.update({
            'Call Setup Success Rate - overall':          round(random.uniform(95, 99.5), 2),
            'Call DR':                                    round(random.uniform(0.1, 3.0), 2),
            'HO SR w/o Intracell':                        round(random.uniform(95, 99.5), 2),
            'TCH availability ratio':                     round(random.uniform(97, 100), 2),
        })
    return base


def insert_sample_data():
    """Create sample sites + cells in metadata.db and KPI rows in PM dbs."""

    # ── metadata.db: sites + cells ──────────────────────────────────────────
    meta = sqlite3.connect(METADATA_DB)
    mc   = meta.cursor()

    cells_by_vendor = {'Nokia': [], 'Huawei': []}   # collect for PM insert

    print(f"Using metadata DB: {METADATA_DB}")
    print(f"Using Nokia PM DB: {NOKIA_PM_DB}")
    print(f"Using Huawei PM DB: {HUAWEI_PM_DB}")
    print()

    print(f"Inserting {len(SITES)} sites...")
    for site in SITES:
        mc.execute('''
            INSERT INTO sites (site_id, site_name, latitude, longitude, site_type, vendor, status)
            VALUES (?, ?, ?, ?, ?, ?, 'Active')
            ON CONFLICT(site_id) DO UPDATE SET
                site_name = excluded.site_name,
                latitude  = excluded.latitude,
                longitude = excluded.longitude,
                vendor    = excluded.vendor,
                status    = 'Active'
        ''', (site['site_id'], site['site_name'], site['latitude'], site['longitude'],
              site['site_type'], site['vendor']))

        vendor = site['vendor']
        techs  = NOKIA_TECHS if vendor == 'Nokia' else HUAWEI_TECHS

        # 3 sectors × selected technologies
        for sector_num in range(1, 4):
            azimuth = (sector_num - 1) * 120
            tech    = techs[sector_num % len(techs)]
            freq    = random.choice(FREQ_BANDS[tech])
            pci     = random.randint(0, 503)

            cell_name = f"{site['site_name']}-S{sector_num}-{tech}"

            mc.execute('''
                INSERT INTO cells
                    (cell_name, site_id, technology, vendor, frequency_band, azimuth, pci, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'Active')
                ON CONFLICT(cell_name) DO UPDATE SET
                    site_id        = excluded.site_id,
                    technology     = excluded.technology,
                    vendor         = excluded.vendor,
                    frequency_band = excluded.frequency_band,
                    azimuth        = excluded.azimuth,
                    pci            = excluded.pci,
                    status         = 'Active'
            ''', (cell_name, site['site_id'], tech, vendor, freq, azimuth, pci))

            cells_by_vendor[vendor].append((cell_name, tech))

    meta.commit()

    total_sites = mc.execute("SELECT COUNT(*) FROM sites").fetchone()[0]
    total_cells = mc.execute("SELECT COUNT(*) FROM cells").fetchone()[0]
    meta.close()
    print(f"[OK] metadata.db: {total_sites} sites, {total_cells} cells")

    # ── PM databases: hourly KPI rows for the last 7 days ──────────────────
    now   = datetime.now()
    hours = 168  # 7 days

    for vendor, pm_db in [('Nokia', NOKIA_PM_DB), ('Huawei', HUAWEI_PM_DB)]:
        cells = cells_by_vendor[vendor]
        if not cells:
            continue

        conn = sqlite3.connect(pm_db, timeout=30)
        conn.execute('PRAGMA journal_mode=WAL')

        # Ensure KPI columns exist for ALL technologies in this vendor
        all_techs = set(t for _, t in cells)
        existing = {r[1] for r in conn.execute('PRAGMA table_info(cell_kpis)').fetchall()}
        for tech in all_techs:
            sample = _random_kpi_row('test', '2000-01-01', tech)
            for col in sample.keys():
                if col not in ('cell_name', 'timestamp') and col not in existing:
                    conn.execute(f'ALTER TABLE cell_kpis ADD COLUMN "{col}" REAL')
                    existing.add(col)

        inserted = 0
        for cell_name, tech in cells:
            for h in range(hours):
                ts = (now - timedelta(hours=hours - h)).strftime('%Y-%m-%d %H:%M:%S')
                row = _random_kpi_row(cell_name, ts, tech)
                cols_q   = ', '.join(f'"{c}"' for c in row.keys())
                placeholders = ', '.join(['?'] * len(row))
                conn.execute(
                    f'INSERT OR REPLACE INTO cell_kpis ({cols_q}) VALUES ({placeholders})',
                    list(row.values())
                )
                inserted += 1

        conn.commit()
        conn.close()
        print(f"[OK] {os.path.basename(pm_db)}: {inserted} KPI rows for {len(cells)} cells ({hours}h each)")

    print()
    print("=== Sample Data Summary ===")
    print(f"  Sites: {total_sites}")
    print(f"  Cells: {total_cells}")
    print(f"  Nokia cells:  {len(cells_by_vendor['Nokia'])}")
    print(f"  Huawei cells: {len(cells_by_vendor['Huawei'])}")
    print(f"  KPI hours:    {hours} per cell")
    print("===========================")


if __name__ == '__main__':
    insert_sample_data()
    print("\nSample data is ready! Performance module should now show KPI data.")
    print("Note: This data will be replaced when SFTP sync is configured.")
