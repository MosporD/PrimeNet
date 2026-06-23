#!/usr/bin/env python3
"""Create admin_test — a normal (non-admin) user for UI preview."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database_enhanced import authenticate_user, create_user, execute_query, get_db

USERNAME = 'admin_test'
EMAIL = 'admin_test@company.com'
PASSWORD = 'AdminTest123!'
FULL_NAME = 'Admin Test (Normal User)'


def main() -> int:
    conn = get_db()
    existing = execute_query(
        conn,
        'SELECT id, username, role FROM users WHERE LOWER(username) = LOWER(?)',
        (USERNAME,),
    ).fetchone()
    conn.close()

    if existing:
        uid = existing['id'] if isinstance(existing, dict) else existing[0]
        conn = get_db()
        execute_query(
            conn,
            "UPDATE users SET role = 'user', is_active = 1, force_password_change = 0 WHERE id = ?",
            (uid,),
        )
        conn.commit()
        conn.close()
        print(f'User "{USERNAME}" already exists (id={uid}); role set to user.')
    else:
        ok, result = create_user(
            username=USERNAME,
            email=EMAIL,
            password=PASSWORD,
            full_name=FULL_NAME,
            department='IT',
            role='user',
        )
        if not ok:
            print(f'Failed to create user: {result}')
            return 1
        conn = get_db()
        execute_query(
            conn,
            'UPDATE users SET force_password_change = 0 WHERE id = ?',
            (result,),
        )
        conn.commit()
        conn.close()
        print(f'Created user "{USERNAME}" (id={result}, role=user).')

    ok, user = authenticate_user(USERNAME, PASSWORD)
    if not ok:
        print('Login verification failed.')
        return 1
    print(f'Login OK — role={user.get("role")!r}')
    print(f'Username: {USERNAME}')
    print(f'Password: {PASSWORD}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
