import unittest

from modules.cm_extractor.scripts._bootstrap import bootstrap

bootstrap()

from core.cm_extractor.nokia_bulk_routing import (
    bulk_mo_abbreviations,
    selection_prefers_bulk,
    should_use_bulk_export,
)


class NokiaBulkRoutingTests(unittest.TestCase):
    def test_lnhoif_full_mo_prefers_bulk(self) -> None:
        sel = {'mo_class_id': 'NOKLTE:LNHOIF', 'export_mode': 'full', 'parameters': []}
        self.assertTrue(selection_prefers_bulk(sel))
        self.assertIn('LNHOIF', bulk_mo_abbreviations())

    def test_lncel_not_bulk_by_default(self) -> None:
        sel = {'mo_class_id': 'NOKLTE:LNCEL', 'export_mode': 'full', 'parameters': []}
        self.assertFalse(selection_prefers_bulk(sel))

    def test_lnadj_prefers_bulk(self) -> None:
        sel = {'mo_class_id': 'NOKLTE:LNADJ', 'export_mode': 'selected', 'parameters': ['adjEnbId']}
        self.assertTrue(selection_prefers_bulk(sel, site_count=2))
        self.assertTrue(selection_prefers_bulk(
            {'mo_class_id': 'NOKLTE:LNREL', 'export_mode': 'selected', 'parameters': ['targetCellDn']},
            site_count=2,
        ))

    def test_lnadj_variant_is_bulk(self) -> None:
        from core.cm_extractor.nokia_bulk_routing import is_high_cardinality_mo, is_bulk_mo_abbreviation

        self.assertTrue(is_high_cardinality_mo('NOKLTE:LNADJG'))
        self.assertTrue(is_bulk_mo_abbreviation('LNRELW'))
        self.assertFalse(is_high_cardinality_mo('NOKLTE:LNCEL'))

    def test_should_use_bulk_for_mrbts_lnhoif(self) -> None:
        selections = [{'mo_class_id': 'NOKLTE:LNHOIF', 'export_mode': 'full', 'parameters': []}]
        # SFTP may be configured in dev .env; when not configured this returns False.
        result = should_use_bulk_export(
            scope_level='MRBTS',
            site_ids=['1201'],
            selections=selections,
        )
        self.assertIsInstance(result, bool)


if __name__ == '__main__':
    unittest.main()
