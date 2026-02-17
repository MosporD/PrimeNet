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

    # Per-technology KPI tables (2G_Hourly, 3G_Hourly, 4G_Hourly, 5G_Hourly)
    for tech in ('2G', '3G', '4G', '5G'):
        table = f'{tech}_Hourly'
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS "{table}" (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cell_name TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                UNIQUE (cell_name, timestamp) ON CONFLICT REPLACE
            )
        ''')

    conn.commit()
    print("[OK] Network Map tables created successfully")

    # Add indexes for performance
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_sectors_site ON sectors(site_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_cells_sector ON cells(sector_id)')
    for tech in ('2G', '3G', '4G', '5G'):
        table = f'{tech}_Hourly'
        cursor.execute(f'CREATE INDEX IF NOT EXISTS "idx_{table}_cell_ts" ON "{table}" (cell_name, timestamp)')
        cursor.execute(f'CREATE INDEX IF NOT EXISTS "idx_{table}_ts"      ON "{table}" (timestamp)')

    conn.commit()
    print("[OK] Indexes created")

    conn.close()

if __name__ == '__main__':
    add_map_tables()
    print("\nDatabase schema updated successfully!")
