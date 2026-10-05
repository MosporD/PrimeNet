"""Repo-wide scan for SQLite-only SQL patterns (Postgres cutover hygiene).

Run: ``python scripts/audit_sqlite_isms.py``  (report only)
      ``python scripts/audit_sqlite_isms.py --fail``  (CI gate once debt is burned down)
"""

from __future__ import annotations

import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ('sqlite_master', re.compile(r'\bsqlite_master\b', re.I)),
    ('PRAGMA', re.compile(r'\bPRAGMA\b', re.I)),
    ('INSERT OR REPLACE', re.compile(r'\bINSERT\s+OR\s+REPLACE\b', re.I)),
    ('INSERT OR IGNORE', re.compile(r'\bINSERT\s+OR\s+IGNORE\b', re.I)),
    ('AUTOINCREMENT', re.compile(r'\bAUTOINCREMENT\b', re.I)),
    ('GROUP_CONCAT', re.compile(r'\bGROUP_CONCAT\b', re.I)),
    ('IFNULL', re.compile(r'\bIFNULL\s*\(', re.I)),
    ('rowid', re.compile(r'\browid\b', re.I)),
    ('last_insert_rowid', re.compile(r'\blast_insert_rowid\b', re.I)),
    ('COLLATE NOCASE', re.compile(r'\bCOLLATE\s+NOCASE\b', re.I)),
]

SKIP_DIR_PARTS = {
    'huawei_params',
    'graphify-out',
    '.git',
    '__pycache__',
    'node_modules',
    '.venv',
    'venv',
}

# Paths where SQLite-shaped SQL is expected (adapter, docs, generated HTML, marketing portal).
ALLOWLIST_SUBSTRINGS = (
    'db/app_sql.py',
    'scripts/test_app_db_adapter.py',
    'scripts/audit_sqlite_isms.py',
    'portals/marketing/',
    'graphify-out/',
    'modules/parameter_dictionary/huawei_params/',
)


def _skip_path(rel: str) -> bool:
    parts = rel.replace('\\', '/').split('/')
    if any(p in SKIP_DIR_PARTS for p in parts):
        return True
    base = parts[-1]
    if base.startswith('_tmp_') or base.startswith('_tmp.'):
        return True
    if not rel.endswith('.py'):
        return True
    return False


def _allowed(rel: str) -> bool:
    norm = rel.replace('\\', '/')
    return any(token in norm for token in ALLOWLIST_SUBSTRINGS)


def main() -> int:
    parser = argparse.ArgumentParser(description='Scan Python sources for SQLite-only SQL patterns.')
    parser.add_argument(
        '--fail',
        action='store_true',
        help='Exit 1 when actionable hits exist (default: report only).',
    )
    args = parser.parse_args()

    hits: dict[str, list[tuple[int, str, str]]] = {}
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIR_PARTS]
        for name in filenames:
            rel = os.path.relpath(os.path.join(dirpath, name), ROOT)
            if _skip_path(rel):
                continue
            path = os.path.join(dirpath, name)
            try:
                with open(path, encoding='utf-8', errors='replace') as fh:
                    for lineno, line in enumerate(fh, 1):
                        stripped = line.strip()
                        if stripped.startswith('#'):
                            continue
                        for label, rx in PATTERNS:
                            if rx.search(line):
                                hits.setdefault(label, []).append((lineno, rel, stripped[:120]))
            except OSError:
                continue

    print('SQLite-ism audit (Python sources)\n')
    actionable = 0
    for label, _rx in PATTERNS:
        rows = hits.get(label, [])
        bad = [r for r in rows if not _allowed(r[1])]
        print(f'{label}: {len(rows)} total, {len(bad)} outside allowlist')
        for lineno, rel, snippet in bad[:8]:
            safe = snippet.encode('ascii', 'backslashreplace').decode('ascii')
            print(f'  {rel}:{lineno}  {safe}')
        if len(bad) > 8:
            print(f'  ... +{len(bad) - 8} more')
        actionable += len(bad)
        print()

    if actionable:
        print(f'Summary: {actionable} actionable hits outside allowlist.')
        if args.fail:
            print('FAILED (--fail). Fix or extend allowlist deliberately.')
            return 1
        print('Report only (pass `--fail` to gate CI).')
        return 0
    print('OK: no actionable SQLite-isms outside allowlisted paths.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
