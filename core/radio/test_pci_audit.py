"""Unit tests for the PCI audit classifier (pure functions, no database)."""

from core.radio.pci_audit import (
    classify_relations,
    is_lte_or_nr,
    pci_value,
)


def _rel(src, tgt, *, attempts=100, tech="4G-4G"):
    return {
        "source_cell": src,
        "target_cell": tgt,
        "ho_attempts": attempts,
        "technology": tech,
        "vendor": "Nokia",
        "source_site_id": "S1",
    }


def _kinds(findings):
    return sorted(f["kind"] for f in findings)


# ── pci_value ──────────────────────────────────────────────────────────────
def test_pci_value_parses_ints_strings_and_floats():
    assert pci_value(42) == 42
    assert pci_value("42") == 42
    assert pci_value("42.0") == 42
    assert pci_value(0) == 0


def test_pci_value_rejects_blank_and_out_of_range():
    for bad in (None, "", "   ", "abc", -1, 1008, 5000):
        assert pci_value(bad) is None, bad


def test_pci_value_accepts_nr_range_above_lte():
    assert pci_value(1007) == 1007


# ── technology gate ────────────────────────────────────────────────────────
def test_is_lte_or_nr_gate():
    assert is_lte_or_nr("4G-4G")
    assert is_lte_or_nr("5G-5G")
    assert is_lte_or_nr("LTE")
    assert not is_lte_or_nr("3G-3G")
    assert not is_lte_or_nr("2G-2G")
    assert not is_lte_or_nr(None)


# ── collision ──────────────────────────────────────────────────────────────
def test_collision_when_relation_ends_share_pci():
    findings = classify_relations([_rel("A", "B")], {"a": 100, "b": 100})
    assert _kinds(findings) == ["collision"]
    assert findings[0]["pci"] == 100
    assert findings[0]["target_cells"] == ["B"]


def test_collision_reported_once_for_both_directions():
    rels = [_rel("A", "B"), _rel("B", "A")]
    findings = [f for f in classify_relations(rels, {"a": 7, "b": 7}) if f["kind"] == "collision"]
    assert len(findings) == 1


def test_no_collision_across_different_bands():
    findings = classify_relations(
        [_rel("A", "B")], {"a": 100, "b": 100}, band_by_cell={"a": "L1800", "b": "L2100"}
    )
    assert findings == []


def test_collision_still_found_when_band_unknown():
    findings = classify_relations([_rel("A", "B")], {"a": 5, "b": 5}, band_by_cell={"a": "L1800"})
    assert _kinds(findings) == ["collision"]


# ── confusion ──────────────────────────────────────────────────────────────
def test_confusion_when_two_neighbours_share_pci():
    rels = [_rel("A", "B"), _rel("A", "C")]
    findings = [f for f in classify_relations(rels, {"a": 1, "b": 55, "c": 55}) if f["kind"] == "confusion"]
    assert len(findings) == 1
    assert findings[0]["source_cell"] == "A"
    assert findings[0]["target_cells"] == ["B", "C"]
    assert findings[0]["pci"] == 55


def test_no_confusion_when_neighbour_pcis_differ():
    rels = [_rel("A", "B"), _rel("A", "C")]
    findings = classify_relations(rels, {"a": 1, "b": 55, "c": 56})
    assert "confusion" not in _kinds(findings)


def test_confusion_ignores_neighbours_on_another_band():
    rels = [_rel("A", "B"), _rel("A", "C")]
    findings = classify_relations(
        rels, {"a": 1, "b": 55, "c": 55}, band_by_cell={"a": "L1800", "b": "L1800", "c": "L2600"}
    )
    assert "confusion" not in _kinds(findings)


def test_confusion_counts_three_neighbours():
    rels = [_rel("A", "B"), _rel("A", "C"), _rel("A", "D")]
    findings = [f for f in classify_relations(rels, {"a": 1, "b": 9, "c": 9, "d": 9}) if f["kind"] == "confusion"]
    assert len(findings) == 1
    assert findings[0]["target_cells"] == ["B", "C", "D"]


# ── mod3 / mod30 ───────────────────────────────────────────────────────────
def test_mod3_flagged_for_busy_lte_pair():
    findings = classify_relations([_rel("A", "B")], {"a": 3, "b": 6})
    assert "mod3" in _kinds(findings)


def test_mod3_skipped_below_attempt_threshold():
    findings = classify_relations([_rel("A", "B", attempts=5)], {"a": 3, "b": 6})
    assert findings == []


def test_mod3_skipped_for_non_lte_technology():
    findings = classify_relations([_rel("A", "B", tech="3G-3G")], {"a": 3, "b": 6})
    assert findings == []


def test_mod30_flagged_and_implies_mod3():
    # 10 and 40 differ by 30, so they collide on both mod3 and mod30.
    findings = classify_relations([_rel("A", "B")], {"a": 10, "b": 40})
    assert _kinds(findings) == ["mod3", "mod30"]


def test_collision_short_circuits_modulo_checks():
    # Identical PCIs are a collision; they should not also be logged as mod3.
    findings = classify_relations([_rel("A", "B")], {"a": 9, "b": 9})
    assert _kinds(findings) == ["collision"]


# ── robustness ─────────────────────────────────────────────────────────────
def test_relations_without_pci_metadata_are_skipped():
    assert classify_relations([_rel("A", "B")], {"a": 100}) == []


def test_self_relation_ignored():
    assert classify_relations([_rel("A", "A")], {"a": 100}) == []


def test_blank_cell_names_ignored():
    assert classify_relations([_rel("", "B"), _rel("A", "")], {"a": 1, "b": 1}) == []


def test_non_numeric_attempts_do_not_raise():
    findings = classify_relations([_rel("A", "B", attempts="n/a")], {"a": 3, "b": 6})
    assert findings == []  # unparseable attempts fall back to 0, below threshold
