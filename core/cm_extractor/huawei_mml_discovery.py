"""
Probe U2020 MML commands per NE product type.

Huawei wireless Open API has no REST endpoint to list supported MML commands.
Discovery works by issuing candidate ``LST <object>:;`` commands against a sample NE
for each ``product_name`` (e.g. BTS3900) and classifying the response.
"""

from __future__ import annotations

import re
import time
from typing import Any

from core.cm_extractor.huawei_client import HuaweiCmClient
from core.cm_extractor.http_util import request_json
from core.cm_extractor.mml_parser import normalize_mml_command, parse_mml_report

# Candidate LST objects to probe (object name, label, technology, UI group).
CANDIDATE_LST_OBJECTS: list[tuple[str, str, str, str]] = [
    ('CELL', 'LTE Cell', '4G', 'LTE'),
    ('ENODEBFUNCTION', 'eNodeB Function', '4G', 'LTE'),
    ('NRCELL', 'NR Cell', '5G', 'NR'),
    ('NRDUCELL', 'NR DU Cell', '5G', 'NR'),
    ('CNOPERATOR', 'CN Operator', '4G', 'LTE'),
    ('CNOPERATORHOCFG', 'CN Operator HO Config', '4G', 'LTE'),
    ('S1', 'S1 Interface', '4G', 'LTE'),
    ('X2', 'X2 Interface', '4G', 'LTE'),
    ('DEVIP', 'Device IP', '4G', 'Platform'),
    ('SUBRACK', 'Subrack', '4G', 'Platform'),
    ('BRD', 'Board', '4G', 'Platform'),
    ('RET', 'RET Antenna', '4G', 'RF'),
    ('SECTOR', 'Sector', '4G', 'RF'),
    ('PDSCHCFG', 'PDSCH Config', '4G', 'LTE'),
    ('EUTRANEXTERNALCELL', 'E-UTRAN External Cell', '4G', 'LTE'),
    ('UTRANNCELL', 'UTRAN NCell', '3G', '3G'),
    ('UTRANCELL', 'UTRAN Cell', '3G', '3G'),
    ('UTRANRELATION', 'UTRAN Relation', '3G', '3G'),
    ('NODEB', 'NodeB', '3G', '3G'),
    ('GSMCELL', 'GSM Cell', '2G', '2G'),
    ('GNB', 'gNodeB', '5G', 'NR'),
    ('ENODEB', 'eNodeB (legacy name)', '4G', 'LTE'),
    ('EUTRANRELATION', 'E-UTRAN Relation', '4G', 'LTE'),
    ('EUTRANCELL', 'E-UTRAN Cell', '4G', 'LTE'),
    ('SCTPHOST', 'SCTP Host', '4G', 'Transport'),
    ('GERANNFREQGROUP', 'GERAN NFreq Group', '4G', 'LTE'),
]

_PROBE_SLEEP_SEC = 0.05


def classify_mml_probe(report: str, result: str = '') -> str:
    """
    Classify a single NE MML probe response.

    Returns one of: success, permission_denied, unsupported, failed, empty.
    """
    text = f'{report} {result}'.strip().lower()
    if not text:
        return 'empty'
    if 'inexecutable' in text or 'invalid command' in text:
        return 'unsupported'
    if 'permission denied' in text:
        return 'permission_denied'
    if 'not exist' in text:
        return 'failed'
    if 'incorrect command format' in text:
        return 'unsupported'
    if 'retcode = 0' in text or 'operation succeeded' in text:
        return 'success'
    if 'number of results' in text:
        return 'success'
    # Parsed table without explicit error text
    if report.strip() and not any(
        marker in text
        for marker in ('failed', 'error', 'denied', 'invalid')
    ):
        return 'success'
    return 'failed'


def probe_mml_command(
    client: HuaweiCmClient,
    ne_name: str,
    object_name: str,
) -> dict[str, Any]:
    """Probe one ``LST <object>:;`` command on a single NE."""
    command = normalize_mml_command(f'LST {object_name}')
    status, payload = request_json(
        'POST',
        client._url('/api/rest/mmlManagement/v1/command'),
        headers={**client._auth_headers(), 'Accept-Language': 'en-US'},
        body={'command': command, 'neNames': [ne_name]},
        timeout=120,
        verify_ssl=client.verify_ssl,
    )
    item = ((payload or {}).get('results') or [{}])[0] if isinstance(payload, dict) else {}
    report = str(item.get('report') or '')
    result = str(item.get('result') or '')
    state = classify_mml_probe(report, result)

    columns: list[str] = []
    if state == 'success':
        for row in parse_mml_report(report):
            for key in row:
                if key not in columns:
                    columns.append(key)

    return {
        'object_name': object_name.upper(),
        'command': command,
        'state': state,
        'executable': state in ('success', 'permission_denied'),
        'permission_denied': state == 'permission_denied',
        'columns': columns,
        'report_snippet': report.replace('\n', ' ')[:160],
        'http_status': status,
    }


def discover_commands_for_ne(
    client: HuaweiCmClient,
    ne_name: str,
    *,
    product_name: str = '',
) -> list[dict[str, Any]]:
    """Probe all candidate LST objects against one NE."""
    items: list[dict[str, Any]] = []
    for object_name, label, technology, group in CANDIDATE_LST_OBJECTS:
        probe = probe_mml_command(client, ne_name, object_name)
        if not probe['executable']:
            continue
        items.append({
            'id': object_name.upper(),
            'label': label,
            'technology': technology,
            'group': group,
            'command': probe['command'],
            'recommended': object_name.upper() in ('CELL', 'ENODEBFUNCTION'),
            'products': [product_name] if product_name else [],
            'sample_ne': ne_name,
            'permission_denied': probe['permission_denied'],
            'columns': probe['columns'],
            'state': probe['state'],
        })
        time.sleep(_PROBE_SLEEP_SEC)
    return items


def discover_commands_by_product(
    client: HuaweiCmClient,
    nes: list[dict[str, Any]],
    *,
    max_products: int = 8,
) -> dict[str, Any]:
    """
    Pick one sample NE per product_name and probe candidate LST commands.

    Returns ``commands_by_product`` and a flattened union list for the MO picker.
    """
    samples: dict[str, dict[str, Any]] = {}
    for row in nes:
        product = str(row.get('product_name') or 'Unknown').strip() or 'Unknown'
        if product not in samples:
            samples[product] = row
        if len(samples) >= max_products:
            break

    commands_by_product: dict[str, list[dict[str, Any]]] = {}
    for product, row in samples.items():
        ne_name = str(row.get('ne_name') or '').strip()
        if not ne_name:
            continue
        commands_by_product[product] = discover_commands_for_ne(
            client,
            ne_name,
            product_name=product,
        )

    # Union catalog keyed by object id (prefer BTS3900 entry when duplicated).
    union: dict[str, dict[str, Any]] = {}
    for product in sorted(commands_by_product.keys()):
        for item in commands_by_product[product]:
            mo_id = item['id']
            existing = union.get(mo_id)
            if not existing:
                union[mo_id] = dict(item)
                continue
            products = set(existing.get('products') or [])
            products.update(item.get('products') or [])
            existing['products'] = sorted(products)
            if item.get('columns') and not existing.get('columns'):
                existing['columns'] = item['columns']

    return {
        'commands_by_product': commands_by_product,
        'mo_catalog': sorted(union.values(), key=lambda row: (row.get('group', ''), row['label'])),
        'product_samples': {
            product: str(row.get('ne_name') or '')
            for product, row in samples.items()
        },
    }
