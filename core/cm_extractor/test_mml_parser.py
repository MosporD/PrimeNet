"""Regression tests for Huawei MML report parsing."""

from core.cm_extractor.mml_parser import parse_mml_report, repair_mml_rows


def test_cell_horizontal_table():
    report = """
Local Cell ID  Cell Name  Physical cell ID  Csg indicator  Cell active state
1  WA_Cell_1  101  FALSE  Cell active
2  WA_Cell_2  102  FALSE  Cell active
"""
    rows = parse_mml_report(report)
    assert len(rows) == 2
    assert rows[0]['Local Cell ID'] == '1'
    assert rows[0]['Cell Name'] == 'WA_Cell_1'


def test_cell_hybrid_vertical_pairs():
    report = """
Local Cell ID  Cell Name  Physical cell ID  Csg indicator  Cell active state
Local Cell ID  1
Cell Name  WA_Foo
Physical cell ID  101
Csg indicator  FALSE
Cell active state  Cell active
Local Cell ID  2
Cell Name  WA_Bar
Physical cell ID  102
"""
    rows = parse_mml_report(report)
    assert len(rows) == 2
    assert rows[0]['Local Cell ID'] == '1'
    assert rows[0]['Cell Name'] == 'WA_Foo'
    assert rows[1]['Cell Name'] == 'WA_Bar'


def test_cell_vertical_equals_format():
    report = """
Display static parameters of cells
----------------------------------
                              Local Cell ID  =  1
                                  Cell Name  =  Tdd8T
                           Physical cell ID  =  1
                     Uplink EARFCN indication  =  Not configure
                            High speed flag  =  Low speed cell flag
                           Root sequence index  =  223
"""
    rows = parse_mml_report(report)
    assert len(rows) == 1
    assert rows[0]['Local Cell ID'] == '1'
    assert rows[0]['Cell Name'] == 'Tdd8T'
    assert rows[0]['Root sequence index'] == '223'
    assert rows[0]['High speed flag'] == 'Low speed cell flag'


def test_cellmlbho_vertical_equals_with_continuation():
    report = """
                               Local cell ID  =  1
                Mlb Handover-in Protect Mode  =  PROTECTTIMER MODE:Off
                                              =  SPECEVENTA1A2 MODE:Off
                      Inter-RAT MLB Strategy  =  UtranRedirectIMMCI:Off
"""
    rows = parse_mml_report(report)
    assert len(rows) == 1
    assert rows[0]['Local cell ID'] == '1'
    assert 'SPECEVENTA1A2 MODE:Off' in rows[0]['Mlb Handover-in Protect Mode']


def test_cellmlb_headerless_repair():
    good = """
Local cell ID  Inter-Frequency Mobility Load Balancing Threshold(%)  Load Offset(%)
1  85  8
"""
    bad = """
1              85              8
2              85              8
"""
    rows = parse_mml_report(good)
    for row in rows:
        row['NE'] = 'good-ne'
    rows += [{**row, 'NE': 'bad-ne'} for row in parse_mml_report(bad)]
    fixed = repair_mml_rows(rows)
    assert len(fixed) == 3
    bad_rows = [row for row in fixed if row.get('NE') == 'bad-ne']
    assert bad_rows[0]['Inter-Frequency Mobility Load Balancing Threshold(%)'] == '85'