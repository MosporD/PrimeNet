"""
Database Migration Script
Adds missing tables: tasks, task_updates, filter_profiles
Run this to fix "no such table" errors
"""

import sqlite3
import os

DATABASE = 'ncm_users.db'

def add_missing_tables():
    """Add new tables to existing database"""
    
    if not os.path.exists(DATABASE):
        print(f"❌ Database '{DATABASE}' not found!")
        print(f"   Looking in: {os.path.abspath(DATABASE)}")
        return False
    
    print(f"✓ Found database: {os.path.abspath(DATABASE)}")
    
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    # Check which tables exist
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    existing_tables = [row[0] for row in cursor.fetchall()]
    print(f"\n📋 Existing tables: {', '.join(existing_tables)}")
    
    tables_added = 0
    
    # ========================================================================
    # TABLE 1: tasks
    # ========================================================================
    if 'tasks' not in existing_tables:
        print("\n➕ Creating 'tasks' table...")
        cursor.execute('''
            CREATE TABLE tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                task_type TEXT NOT NULL,
                priority TEXT DEFAULT 'medium',
                status TEXT DEFAULT 'pending',
                created_by INTEGER NOT NULL,
                assigned_to INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (created_by) REFERENCES users (id),
                FOREIGN KEY (assigned_to) REFERENCES users (id)
            )
        ''')
        tables_added += 1
        print("   ✓ Created 'tasks' table")
    else:
        print("\n⏭️  'tasks' table already exists")
    
    # ========================================================================
    # TABLE 2: task_updates
    # ========================================================================
    if 'task_updates' not in existing_tables:
        print("\n➕ Creating 'task_updates' table...")
        cursor.execute('''
            CREATE TABLE task_updates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                update_type TEXT NOT NULL,
                old_value TEXT,
                new_value TEXT,
                comment TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (task_id) REFERENCES tasks (id),
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        tables_added += 1
        print("   ✓ Created 'task_updates' table")
    else:
        print("\n⏭️  'task_updates' table already exists")
    
    # ========================================================================
    # TABLE 3: filter_profiles
    # ========================================================================
    if 'filter_profiles' not in existing_tables:
        print("\n➕ Creating 'filter_profiles' table...")
        cursor.execute('''
            CREATE TABLE filter_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                profile_name TEXT NOT NULL,
                description TEXT,
                filter_data TEXT NOT NULL,
                is_shared BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id),
                UNIQUE(user_id, profile_name)
            )
        ''')
        tables_added += 1
        print("   ✓ Created 'filter_profiles' table")
    else:
        print("\n⏭️  'filter_profiles' table already exists")
    
    # Commit changes
    conn.commit()
    
    # Verify tables were created
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    final_tables = [row[0] for row in cursor.fetchall()]
    
    conn.close()
    
    print("\n" + "="*60)
    print("✅ Migration Complete!")
    print(f"   Tables added: {tables_added}")
    print(f"   Total tables: {len(final_tables)}")
    print(f"   Final tables: {', '.join(final_tables)}")
    print("="*60)
    
    return True

if __name__ == '__main__':
    print("="*60)
    print("NCM Database Migration - Add New Tables")
    print("="*60)
    
    success = add_missing_tables()
    
    if success:
        print("\n🎉 Database updated successfully!")
        print("\n📝 Next steps:")
        print("   1. Restart your Flask server")
        print("   2. Refresh your browser")
        print("   3. Try creating a task again")
        print("   4. Try saving a profile")
    else:
        print("\n❌ Migration failed!")
        print("   Make sure you're running this from the same directory as your database")
    
    input("\nPress Enter to exit...")