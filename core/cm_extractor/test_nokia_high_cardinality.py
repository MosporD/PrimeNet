"""LNREL/LNADJ must stay site-scoped — never dump all-PLMN neighbor relations."""

from __future__ import annotations

import unittest
from typing import Any

from modules.cm_extractor.scripts._bootstrap import bootstrap

bootstrap()

from core.cm_extractor.nokia_semantics import extract_full_mo_class, list_site_mo_ids


class FakeNokiaClient:
    def __init__(self) -> None:
        self.lite_paths: list[str] = []
        self.query_paths: list[str] = []
        self.fetched_mo_ids: list[str] = []
        self.scoped_lites: list[dict[str, str]] = []
        self.scoped_dns: list[str] = [
            'PLMN-PLMN/MRBTS-55635/LNBTS-55635/LNCEL-1/LNREL-1',
            'PLMN-PLMN/MRBTS-55635/LNBTS-55635/LNCEL-1/LNREL-2',
        ]
        self.network_lites = [
            {'moId': f'PLMN-PLMN/MRBTS-51111/LNBTS-51111/LNCEL-1/LNREL-{i}'}
            for i in range(400)
        ] + [{'moId': dn} for dn in self.scoped_dns]

    def query_mo_lites(self, mo_path: str, *, conf_id: int = 1, variables=None) -> list[dict[str, Any]]:
        self.lite_paths.append(mo_path)
        if 'instance()=' in mo_path:
            return list(self.scoped_lites)
        return list(self.network_lites)

    def query(self, mo_path: str, expressions: list[str], *, conf_id: int = 1, variables=None):
        self.query_paths.append(mo_path)
        if 'instance()=' in mo_path:
            return [[dn] for dn in self.scoped_dns]
        return [[lite['moId']] for lite in self.network_lites]

    def get_managed_objects(self, mo_ids: list[str], *, conf_id: int = 1, batch_size=None):
        self.fetched_mo_ids.extend(mo_ids)
        return [{'moId': mo_id, 'parameters': {}} for mo_id in mo_ids]


class HighCardinalityMoTests(unittest.TestCase):
    def test_lnrel_does_not_query_all_plmn_when_lites_empty(self) -> None:
        client = FakeNokiaClient()
        mo_ids = list_site_mo_ids(
            client,
            'NOKLTE',
            'LNREL',
            site_id='55635',
            scope_level='MRBTS',
        )
        self.assertEqual(mo_ids, client.scoped_dns)
        self.assertTrue(any('instance()=' in path for path in client.lite_paths))
        self.assertTrue(all('instance()=' in path for path in client.query_paths))
        self.assertFalse(
            any(
                path.endswith('NOKLTE:LNREL') and 'instance()=' not in path
                for path in client.lite_paths
            )
        )

    def test_lnrel_full_mo_fetches_only_site_instances(self) -> None:
        client = FakeNokiaClient()
        sheet = extract_full_mo_class(client, 'NOKLTE', 'LNREL', site_id='55635', scope_level='MRBTS')
        self.assertEqual(sheet['mo_count'], 2)
        self.assertEqual(client.fetched_mo_ids, client.scoped_dns)
        self.assertFalse(
            any(
                path.endswith('NOKLTE:LNREL') and 'instance()=' not in path
                for path in client.lite_paths
            )
        )

    def test_lnrel_skips_all_plmn_when_scoped_query_also_empty(self) -> None:
        client = FakeNokiaClient()
        client.scoped_dns = []
        mo_ids = list_site_mo_ids(
            client,
            'NOKLTE',
            'LNREL',
            site_id='55635',
            scope_level='MRBTS',
        )
        self.assertEqual(mo_ids, [])
        unscoped_lites = [path for path in client.lite_paths if 'instance()=' not in path]
        unscoped_queries = [path for path in client.query_paths if 'instance()=' not in path]
        self.assertEqual(unscoped_lites, [])
        self.assertEqual(unscoped_queries, [])

    def test_lncel_may_fall_back_to_all_plmn(self) -> None:
        client = FakeNokiaClient()
        client.scoped_dns = []
        client.network_lites = [
            {'moId': 'PLMN-PLMN/MRBTS-55635/LNBTS-55635/LNCEL-1'},
            {'moId': 'PLMN-PLMN/MRBTS-51111/LNBTS-51111/LNCEL-1'},
        ]
        mo_ids = list_site_mo_ids(
            client,
            'NOKLTE',
            'LNCEL',
            site_id='55635',
            scope_level='MRBTS',
        )
        self.assertEqual(mo_ids, ['PLMN-PLMN/MRBTS-55635/LNBTS-55635/LNCEL-1'])
        self.assertTrue(any('instance()=' not in path for path in client.lite_paths))


if __name__ == '__main__':
    unittest.main()
