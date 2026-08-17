"""RAML XML dry-run for Nokia Load Balancing apply path."""

from modules.nokia_load_balancing.export import build_backup_xml, build_changes_xml
from modules.nokia_load_balancing.verify import verify_pipeline


def test_build_changes_xml_contains_amlepr_params():
    changes = [
        {
            "mo_class": "NOKLTE:AMLEPR",
            "dist_name": "PLMN-PLMN/MRBTS-1/LNBTS-1/LNCEL-1/AMLEPR-1",
            "parameter": "cacHeadroom",
            "new_value": "40",
            "old_value": "50",
        }
    ]
    xml_text = build_changes_xml(changes)
    assert "NOKLTE:AMLEPR" in xml_text
    assert "cacHeadroom" in xml_text
    assert ">40<" in xml_text
    assert "raml" in xml_text


def test_backup_xml_restores_old_value():
    changes = [
        {
            "mo_class": "NOKLTE:AMLEPR",
            "dist_name": "PLMN-PLMN/MRBTS-1/LNBTS-1/LNCEL-1/AMLEPR-1",
            "parameter": "deltaCac",
            "new_value": "60",
            "old_value": "50",
        }
    ]
    xml_text = build_backup_xml(changes)
    assert ">50<" in xml_text
    assert "deltaCac" in xml_text


def test_verify_pipeline_runs_xml_and_rules():
    payload = verify_pipeline()
    names = {c["name"]: c for c in payload.get("checks") or []}
    assert names["amle_rules"]["ok"] is True
    assert names["raml_xml_dry_run"]["ok"] is True
    assert payload.get("live_oss_push_attempted") is False
