"""Live Huawei MML: LST CELL / LST UCELL / LST GCELL for 5 sample sites."""
from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / '.env', override=True)

from db.runtime import connect_metadata, execute_query
from core.cm_extractor.config import huawei_configured, huawei_defaults
from core.cm_extractor.excel_writer import write_huawei_sheets_excel
from core.cm_extractor.extraction import build_huawei_client
from core.cm_extractor.mml_parser import repair_mml_rows
from core.cm_extractor.site_catalog import resolve_huawei_ne_names

SITE_IDS = ['1004', '1005', '1006', '1007', '1008']
OUT = ROOT / 'uploads' / 'cm_extractor' / 'samples' / 'huawei_cm_live_lst_cell_ucell_gcell.xlsx'
CATALOG = ROOT / 'data' / 'huawei_u2020_ne_catalog.json'


def _nbi_open(host: str, port: int, timeout: float = 8) -> bool:
    sock = socket.create_connection
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _site_controllers() -> list[dict]:
    conn = connect_metadata()
    ph = ','.join('?' for _ in SITE_IDS)
    try:
        rows = execute_query(
            conn,
            f'''
            SELECT
                s.site_id,
                s.site_name,
                (SELECT MIN(rnc) FROM cells_3g c3
                  WHERE CAST(c3.nodeb_id AS TEXT)=s.site_id
                    AND LOWER(COALESCE(c3.vendor,'')) LIKE '%huawei%') AS rnc,
                (SELECT MIN(rnc_name) FROM cells_3g c3
                  WHERE CAST(c3.nodeb_id AS TEXT)=s.site_id
                    AND LOWER(COALESCE(c3.vendor,'')) LIKE '%huawei%') AS rnc_name,
                (SELECT MIN(bsc) FROM cells_2g c2
                  WHERE CAST(c2.site_id AS TEXT)=s.site_id
                    AND LOWER(COALESCE(c2.vendor,'')) LIKE '%huawei%') AS bsc,
                (SELECT MIN(bsc_name) FROM cells_2g c2
                  WHERE CAST(c2.site_id AS TEXT)=s.site_id
                    AND LOWER(COALESCE(c2.vendor,'')) LIKE '%huawei%') AS bsc_name,
                (SELECT MIN(nodeb_name) FROM cells_3g c3
                  WHERE CAST(c3.nodeb_id AS TEXT)=s.site_id
                    AND LOWER(COALESCE(c3.vendor,'')) LIKE '%huawei%') AS nodeb_name
            FROM sites s
            WHERE s.site_id IN ({ph})
            ORDER BY CAST(s.site_id AS INTEGER)
            ''',
            SITE_IDS,
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _catalog_nes() -> list[dict]:
    payload = json.loads(CATALOG.read_text(encoding='utf-8'))
    return list(payload.get('nes') or [])


def _match_controller(candidates: list[str], nes: list[dict], products: tuple[str, ...]) -> str:
    wanted = {c.strip().upper() for c in candidates if str(c or '').strip()}
    if not wanted:
        return ''
    by_name = {str(ne.get('ne_name') or '').strip(): ne for ne in nes if str(ne.get('ne_name') or '').strip()}
    for cand in wanted:
        for name in by_name:
            if name.upper() == cand:
                return name
    product_ok = {p.upper() for p in products}
    for ne in nes:
        product = str(ne.get('product_name') or '').upper()
        if product not in product_ok:
            continue
        name = str(ne.get('ne_name') or '').strip()
        if name.upper() in wanted:
            return name
    # Prefix match: metadata rnc "1" -> RNC01, bsc "HQ_01" -> BSC_HQ_01
    for ne in nes:
        product = str(ne.get('product_name') or '').upper()
        if product not in product_ok:
            continue
        name = str(ne.get('ne_name') or '').strip()
        upper = name.upper().replace(' ', '_')
        for cand in wanted:
            token = cand.replace(' ', '_')
            if token and (token in upper or upper.endswith(token.zfill(2)) or upper.endswith(token)):
                return name
            if token.isdigit() and upper.replace('RNC', '').lstrip('0') == token.lstrip('0'):
                return name
    return ''


def _row_matches_sites(row: dict, site_ids: list[str], extra_needles: list[str]) -> bool:
    blob = ' '.join(str(v) for v in row.values()).upper()
    for sid in site_ids:
        if sid in blob:
            return True
    for needle in extra_needles:
        if needle and needle.upper() in blob:
            return True
    return False


def _run(client, command: str, ne_names: list[str]) -> tuple[list[dict], list[str], list[dict]]:
    client.clear_skipped_mml_nes()
    rows = client.run_mml_chunked(command, ne_names) if ne_names else []
    rows = repair_mml_rows(rows)
    errors = client.consume_mml_errors()
    skipped = client.consume_skipped_mml_nes()
    return rows, errors, skipped


def main() -> int:
    cfg = huawei_defaults()
    print(f'U2020 {cfg["host"]}:{cfg["port"]} user={cfg["username"]!r} configured={huawei_configured()}')
    if not huawei_configured():
        print('Huawei CM not configured.')
        return 1

    nbi_ok = _nbi_open(cfg['host'], int(cfg['port']))
    print(f'NBI {cfg["host"]}:{cfg["port"]} reachable={nbi_ok}')
    controllers = _site_controllers()
    print('\nSite controllers:')
    for row in controllers:
        print(
            f"  {row['site_id']} rnc={row.get('rnc')} ({row.get('rnc_name')}) "
            f"bsc={row.get('bsc')} ({row.get('bsc_name')})"
        )
    if not nbi_ok:
        print('Cannot run live MML: Open API port is closed from this PC.')
        return 2

    controllers = _site_controllers()
    nes = _catalog_nes()
    print('\nSite controllers:')
    for row in controllers:
        print(
            f"  {row['site_id']} rnc={row.get('rnc')} ({row.get('rnc_name')}) "
            f"bsc={row.get('bsc')} ({row.get('bsc_name')})"
        )

    enb_names, unresolved, _alts, skipped_enb = resolve_huawei_ne_names(SITE_IDS, scope_level='ENODEB')
    print(f'\n4G NEs: {enb_names} unresolved={unresolved} skipped={skipped_enb}')

    rnc_names: list[str] = []
    bsc_names: list[str] = []
    nodeb_needles: list[str] = []
    for row in controllers:
        rnc_ne = _match_controller(
            [str(row.get('rnc_name') or ''), f"RNC{row.get('rnc')}", f"RNC{str(row.get('rnc') or '').zfill(2)}"],
            nes,
            ('BSC6900 UMTS', 'BSC6910 UMTS', 'RNC'),
        )
        bsc_ne = _match_controller(
            [str(row.get('bsc_name') or ''), str(row.get('bsc') or '')],
            nes,
            ('BSC6900 GSM', 'BSC6910 GSM', 'BSC'),
        )
        if rnc_ne and rnc_ne not in rnc_names:
            rnc_names.append(rnc_ne)
        if bsc_ne and bsc_ne not in bsc_names:
            bsc_names.append(bsc_ne)
        if row.get('nodeb_name'):
            nodeb_needles.append(str(row['nodeb_name']))
        print(f"  {row['site_id']} -> RNC NE {rnc_ne or '?'}  BSC NE {bsc_ne or '?'}")

    print(f'\n3G RNC NEs: {rnc_names}')
    print(f'2G BSC NEs: {bsc_names}')

    client = build_huawei_client()
    sheets: dict[str, list[dict]] = {}
    notes: list[dict] = []

    print('\nLST CELL on 4G eNodeBs...')
    cell_rows, cell_err, cell_skip = _run(client, 'LST CELL', enb_names)
    sheets['4G_LST_CELL'] = cell_rows
    notes.append({'command': 'LST CELL', 'nes': ', '.join(enb_names), 'rows': len(cell_rows),
                  'errors': '; '.join(cell_err[:5]), 'skipped': len(cell_skip)})
    print(f'  rows={len(cell_rows)} errors={len(cell_err)} skipped={len(cell_skip)}')
    for err in cell_err[:5]:
        print(f'  ERR {err[:220]}')

    print('\nLST UCELL on 3G RNCs...')
    if rnc_names:
        ucell_all, ucell_err, ucell_skip = _run(client, 'LST UCELL', rnc_names)
        ucell_rows = [r for r in ucell_all if _row_matches_sites(r, SITE_IDS, nodeb_needles)]
        sheets['3G_LST_UCELL'] = ucell_rows
        if len(ucell_all) != len(ucell_rows):
            sheets['3G_LST_UCELL_ALL_RNC'] = ucell_all
        notes.append({
            'command': 'LST UCELL', 'nes': ', '.join(rnc_names),
            'rows': len(ucell_rows), 'rnc_total_rows': len(ucell_all),
            'errors': '; '.join(ucell_err[:5]), 'skipped': len(ucell_skip),
        })
        print(f'  RNC total={len(ucell_all)} filtered to 5 sites={len(ucell_rows)} errors={len(ucell_err)}')
        for err in ucell_err[:5]:
            print(f'  ERR {err[:220]}')
    else:
        print('  No RNC NE names resolved.')
        notes.append({'command': 'LST UCELL', 'nes': '', 'rows': 0, 'errors': 'RNC NE not resolved'})

    print('\nLST GCELL on 2G BSCs...')
    if bsc_names:
        gcell_all, gcell_err, gcell_skip = _run(client, 'LST GCELL', bsc_names)
        gcell_rows = [r for r in gcell_all if _row_matches_sites(r, SITE_IDS, nodeb_needles)]
        sheets['2G_LST_GCELL'] = gcell_rows
        if len(gcell_all) != len(gcell_rows):
            sheets['2G_LST_GCELL_ALL_BSC'] = gcell_all
        notes.append({
            'command': 'LST GCELL', 'nes': ', '.join(bsc_names),
            'rows': len(gcell_rows), 'bsc_total_rows': len(gcell_all),
            'errors': '; '.join(gcell_err[:5]), 'skipped': len(gcell_skip),
        })
        print(f'  BSC total={len(gcell_all)} filtered to 5 sites={len(gcell_rows)} errors={len(gcell_err)}')
        for err in gcell_err[:5]:
            print(f'  ERR {err[:220]}')
    else:
        print('  No BSC NE names resolved — trying LST GCELL on eNodeBs.')
        gcell_rows, gcell_err, gcell_skip = _run(client, 'LST GCELL', enb_names)
        sheets['2G_LST_GCELL'] = gcell_rows
        notes.append({
            'command': 'LST GCELL', 'nes': ', '.join(enb_names),
            'rows': len(gcell_rows), 'errors': '; '.join(gcell_err[:5]), 'skipped': len(gcell_skip),
        })
        print(f'  rows={len(gcell_rows)} errors={len(gcell_err)}')
        for err in gcell_err[:5]:
            print(f'  ERR {err[:220]}')

    sheets['Run_notes'] = notes
    skipped_all = cell_skip
    if skipped_all:
        sheets['Skipped_NEs'] = skipped_all

    OUT.parent.mkdir(parents=True, exist_ok=True)
    write_huawei_sheets_excel(str(OUT), sheets)
    print(f'\nWrote {OUT}')
    print('Sheets:', {k: len(v) for k, v in sheets.items()})
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
