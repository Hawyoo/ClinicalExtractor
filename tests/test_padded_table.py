from clinical_extractor import config
from pathlib import Path

from clinical_extractor.report_editing import edited_table
from clinical_extractor.report_templates import apply_table_template
from clinical_extractor.table_extractor import extract_table_rows

TEXT = (Path(__file__).parent / 'fixtures' / 'padded_bilingual_report.tsv').read_text(encoding='utf-8')
CODES = 'TBIL DBIL IBIL ALT AST TP ALB GLB A/G ALP GGT TBA AFU PA CHE FBG UREA CREA eGFR-EPI UA CysC C1q TC TG HDL-C LDL-C VLDL-C ApoA1 ApoB Lp(a) LDH CK CK-ISO HBDH IMA Na K Cl HCO3 Ca P GA'.split()


def test_padded_header_recovers_all_current_results_without_touching_evidence():
    block = edited_table(TEXT)
    rows = extract_table_rows(block)
    assert len(rows) == 42
    source = block.rows[1:]
    assert [r['value'] for r in rows] == [r[2] for r in source]
    assert [r['evidence'] for r in rows] == [' | '.join(r) for r in source]
    assert [r['payload_json']['reference_raw'] for r in rows] == [r[4] for r in source]
    result = apply_table_template(rows, 'all')
    assert [r['item_standard'] for r in result] == CODES
    assert result[9]['value'] == '6'
    assert result[31]['value'] == '36' and result[31]['abnormal_flag'] == '1'
    assert all(not r['payload_json'].get('unit_warning') for r in result)


def test_stable_column_does_not_borrow_flag_or_reference_when_result_missing():
    text = TEXT.replace('磷酸肌酸激酶(CK)\t36\t1', '磷酸肌酸激酶(CK)\t\t1')
    rows = extract_table_rows(edited_table(text))
    assert len(rows) == 41
    assert not any(r['item_original'] == '32磷酸肌酸激酶(CK)' for r in rows)


def test_history_column_excluded_from_header_recovery():
    text = '项目名称\t\t本次结果\t历史结果\t参考区间\t单位\n'
    text += '\n'.join(f'白细胞计数\t\t\t{n}\t3.5-9.5\t10^9/L' for n in range(3))
    assert extract_table_rows(edited_table(text)) == []


def test_ai_stage_uses_readable_ocr_text_when_html_structure_is_missing(tmp_path, monkeypatch):
    from clinical_extractor import db, service, table_ai
    monkeypatch.setattr(config, 'DB_PATH', tmp_path / 'reports.sqlite3')
    monkeypatch.setattr(table_ai, 'correct_names', lambda rows, _: rows)
    db.init_db()
    with db.connect() as con:
        rid = con.execute('''INSERT INTO reports(filename,file_path,profile,raw_text,parser_json,created_at)
                             VALUES(?,?,?,?,?,?)''', ('test.png', 'test.png', '表格式报告', TEXT, '[]', db.now_iso())).lastrowid
    assert service.process_report(rid, 'llm') == 42
    with db.connect() as con:
        saved = con.execute('SELECT * FROM extractions ORDER BY sort_order,id').fetchall()
    assert [r['item_standard'] for r in saved] == CODES
    assert [r['value'] for r in saved] == [row.split('\t')[2] for row in TEXT.splitlines()[1:]]
