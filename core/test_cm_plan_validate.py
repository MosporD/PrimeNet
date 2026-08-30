"""Schema checks for Nokia RAML plan validation (no dictionary required)."""

from pathlib import Path

from core.cm_plan_validate import validate_raml_plan


def test_validate_raml_plan_flags_missing_objects(tmp_path: Path):
    xml_path = tmp_path / "empty.xml"
    xml_path.write_text("<raml version='2.0'><cmData type='plan'></cmData></raml>", encoding="utf-8")
    payload = validate_raml_plan(str(xml_path), against_snapshot=False)
    assert payload["success"] is True
    assert payload["mo_count"] == 0
    codes = {item["code"] for item in payload["findings"]}
    assert "no_managed_objects" in codes


def test_validate_raml_plan_accepts_managed_object(tmp_path: Path):
    xml_path = tmp_path / "plan.xml"
    xml_path.write_text(
        """<raml version="2.0"><cmData type="plan">
        <managedObject class="LNCEL" distName="PLMN-PLMN/MRBTS-1/LNBTS-1/LNCEL-1" operation="update">
            <p name="pci">101</p>
        </managedObject>
        </cmData></raml>""",
        encoding="utf-8",
    )
    payload = validate_raml_plan(str(xml_path), against_snapshot=False)
    assert payload["success"] is True
    assert payload["mo_count"] == 1
    assert payload["param_count"] == 1
    codes = {item["code"] for item in payload["findings"]}
    assert "no_managed_objects" not in codes
    assert "missing_class" not in codes
    assert "missing_distname" not in codes
