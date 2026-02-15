"""
Add Network Map tables to database
Creates tables for sites, sectors, cells, and KPIs
"""

import sqlite3
import os

DATABASE = 'ncm_users.db'

def add_map_tables():
    """Add tables for network map functionality"""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    print("Adding Network Map tables...")

    # Sites table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            site_id TEXT UNIQUE NOT NULL,
            site_name TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            region TEXT,
            site_type TEXT,
            status TEXT DEFAULT 'Active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Sectors table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sectors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sector_id TEXT UNIQUE NOT NULL,
            site_id TEXT NOT NULL,
            sector_name TEXT NOT NULL,
            azimuth INTEGER,
            beamwidth INTEGER DEFAULT 65,
            technology TEXT,
            frequency_band TEXT,
            status TEXT DEFAULT 'Active',
            FOREIGN KEY (site_id) REFERENCES sites(site_id)
        )
    ''')

    # Cells table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS cells (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cell_id TEXT UNIQUE NOT NULL,
            cell_name TEXT NOT NULL,
            sector_id TEXT NOT NULL,
            pci INTEGER,
            tac INTEGER,
            status TEXT DEFAULT 'Active',
            FOREIGN KEY (sector_id) REFERENCES sectors(sector_id)
        )
    ''')

    # KPIs table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS cell_kpis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cell_id TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            avg_users INTEGER DEFAULT 0,
            data_volume_gb REAL DEFAULT 0,
            rsrp REAL,
            rsrq REAL,
            sinr REAL,
            cqi REAL,
            throughput_dl_mbps REAL,
            throughput_ul_mbps REAL,
            rrc_success_rate REAL,
            erab_success_rate REAL,
            call_drop_rate REAL,
            handover_success_rate REAL,
            availability_percent REAL DEFAULT 100,
            FOREIGN KEY (cell_id) REFERENCES cells(cell_id)
        )
    ''')

    conn.commit()
    print("[OK] Network Map tables created successfully")

    # Add indexes for performance
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_sectors_site ON sectors(site_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_cells_sector ON cells(sector_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_kpis_cell ON cell_kpis(cell_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_kpis_timestamp ON cell_kpis(timestamp)')

    conn.commit()
    print("[OK] Indexes created")

    conn.close()

if __name__ == '__main__':
    add_map_tables()
    print("\nDatabase schema updated successfully!")
