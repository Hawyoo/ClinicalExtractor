from clinical_extractor import config
import pytest

from clinical_extractor.parser import TableBlock
from clinical_extractor.report_editing import edited_table
from clinical_extractor.table_extractor import extract_table_rows
from clinical_extractor.report_templates import apply_table_template
from clinical_extractor.review import attention_for


LIPIDS = '''24\t总胆固醇\t\t3.58\t\t\t以\t2.8-5.2\tmmol/L
25\t甘油三酯\t\t0.82\t\t\tK\t0.56-1.7\tmmol/L
26\t\t高密度脂蛋白\t1.06\t\t\t\t1.04-1.55\tmmol/L
27\t低密度脂蛋白\t\t2.16\t\t\t区\t2.1-3.1\tmmol/L
28\t\t极低密度脂蛋白\t0.36\t\t\t\t0.26-1.3\tmmol/L
29\t载脂蛋白A1\t\t0.99\t↓\t\tK\t1.00-1.70\tg/L
30\t载脂蛋白B\t\t0.62\t\t\t\t0.60-1.10\tg/L
31\t脂蛋白a\t\t42.7\t↑\t-\tW\t3.4-30.0\tmg/dL'''


@pytest.mark.parametrize('separator', ['\t', '|', '  '])
def test_headerless_lipids_preserve_all_source_results(separator):
    text = LIPIDS.replace('\t', separator)
    rows = extract_table_rows(edited_table(text))
    assert [r['value'] for r in rows] == ['3.58','0.82','1.06','2.16','0.36','0.99','0.62','42.7']
    assert rows[0]['item_original'] == '总胆固醇'
    assert rows[-1]['abnormal_flag'] == '高'
    assert rows[-3]['abnormal_flag'] == '低'
    assert all(r['payload_json']['headerless_recovery'] for r in rows)
    assert all(not r['payload_json'].get('ai_review_warning') for r in rows)
    matched = apply_table_template(rows, 'all')
    assert matched[0]['item_standard'] == 'TC'
    assert matched[-1]['value'] == '42.7'  # Out-of-range results are not reassigned.


def test_ambiguous_row_keeps_evidence_and_does_not_block_other_rows():
    text = '尿酸 | 373 | 208-428 | umol/L\n胱抑素C | 1.11 | 0.88 | 0.50-1.03 | mg/L'
    rows = extract_table_rows(edited_table(text))
    assert rows[0]['value'] == '373'
    assert rows[1]['value'] == ''
    assert '1.11' in rows[1]['evidence'] and '0.88' in rows[1]['evidence']
    assert attention_for(rows[1])['visible']
    assert attention_for(apply_table_template(rows, 'all')[1])['warnings']


def test_flag_arrows_and_equals_do_not_discard_unambiguous_results():
    text = ('30 | | 载脂蛋白B | 0.34 | → | | 以 | 0.60-1.10 | g/L\n'
            '35 | | 羟丁酸脱氢酶 | 145 | | = | K | 26-195 | IU/L')
    rows = extract_table_rows(edited_table(text))
    assert [r['value'] for r in rows] == ['0.34', '145']
    assert all(not attention_for(r)['warnings'] for r in rows)
    assert rows[0]['payload_json']['reference_raw'] == '0.60-1.10'


@pytest.mark.parametrize('noise', [',', '，', '、', '；', '。', '·', ':', '：', 'K ,'])
def test_standalone_punctuation_does_not_erase_independent_result(noise):
    text = f'22 | | 胱抑素C | 0.60 | | {noise} | | 0.50-1.03 | mg/L'
    row = extract_table_rows(edited_table(text))[0]
    assert row['value'] == '0.60'
    assert row['payload_json']['reference_raw'] == '0.50-1.03'
    assert noise in row['evidence']
    assert noise in row['payload_json']['layout_noise']
    assert not attention_for(apply_table_template([row], 'all')[0])['warnings']


@pytest.mark.parametrize('cells', ['0,60 | 0.50-1.03', '0.60, | 0.50-1.03',
                                   '0.60 | , | 0.88 | 0.50-1.03',
                                   '0.60 | , 9.9 | 0.50-1.03'])
def test_punctuation_does_not_join_or_drop_numbers(cells):
    row = extract_table_rows(edited_table('胱抑素C | ' + cells + ' | mg/L'))[0]
    assert row['value'] == ''
    assert attention_for(row)['warnings']


@pytest.mark.parametrize('cells', [
    '16.8 | K 3.4-30.0 | mg/dL',
    '16.8 | K3.4-30.0 | mg/dL',
    '16.8 | 以 3.4-30.0 mg/dL',
    '16.8 K 3.4-30.0 mg/dL',
    '16.8 → | 3.4-30.0mg/dL',
])
def test_merged_cells_preserve_exact_result_range_unit_and_evidence(cells):
    text = '31 | | 脂蛋白a | ' + cells
    rows = extract_table_rows(edited_table(text))
    assert len(rows) == 1
    row = rows[0]
    assert row['value'] == '16.8'
    assert row['payload_json']['reference_raw'] == '3.4-30.0'
    assert row['unit'] == 'mg/dL'
    assert 'cell_fragments' in row['payload_json']
    assert not attention_for(row)['warnings']
    assert ' '.join(cells.split()) in ' '.join(row['evidence'].split())


@pytest.mark.parametrize('cell', ['16.8 9.9 K 3.4-30.0 mg/dL',
                                  '16.8 K 3.4-30.0 4.0-40.0 mg/dL',
                                  '16.8 未知数据 9.9 K 3.4-30.0 mg/dL'])
def test_merged_cells_never_choose_between_competing_results_or_ranges(cell):
    rows = extract_table_rows(edited_table('脂蛋白a | ' + cell))
    assert rows[0]['value'] == ''
    assert attention_for(rows[0])['warnings']


def test_pasted_sixteen_report_rows_with_misaligned_tabs_are_preserved():
    text = '''30\t\t载脂蛋白B\t0.53\t→\t\t\t0.60-1.10\tg/L
31\t\t脂蛋白a\t16.8\t\t\tK 3.4-30.0\t\tmg/dL
32\t\t乳酸脱氢酶\t155\t\t\t以\t120-250\tIU/L
33\t\t磷酸肌酸激酶\t66\t\t\tK\t50-310\tU/L
34\t\t磷酸肌酸激酶同工酶\t10\t\t\t2-30\t\tU/L
35\t\t羟丁酸脱氢酶\t106\t\t\tK\t26-195\tIU/L
36\t\t缺血修饰性白蛋白\t68.7\t\t\t\t<79.6\tU/ml
37\t\t氧化氮\t25\t→\t\tK\t30-60\tumol/L
38\t\t血管紧张素转化酶\t67\t\t\t以\t6-68\tU/L
39\t\t钠\t139.9\t\t\tK\t137-147\tmmol/L
40\t\t钾\t4.1\t\t\t\t3.5-5.3\tmmol/L
41\t\t氯\t106.0\t\t=\tK\t99-110\tmmol/L
42\t\t碳酸氢根\t27.20\t\t\t以\t20-31\tmmol/L
43\t\t钙\t2.16\t\t\tK\t2.11-2.52\tmmol/L
44\t\t磷\t1.11\t\t\t\t0.85-1.51\tmmol/L
45\t\t糖化白蛋白\t11.57\t\t\tK\t11-16\t%'''
    rows = extract_table_rows(edited_table(text))
    assert [r['value'] for r in rows] == ['0.53','16.8','155','66','10','106','68.7','25',
                                         '67','139.9','4.1','106.0','27.20','2.16','1.11','11.57']
    assert all(not attention_for(r)['warnings'] for r in rows)
    assert rows[1]['payload_json']['reference_raw'] == '3.4-30.0'
    assert 'K 3.4-30.0' in rows[1]['evidence']


@pytest.mark.parametrize('text', ['白细胞计数\n红细胞计数', '5.1\n3.8-5.1\n10^12/L'])
def test_unrelated_columns_and_name_lists_are_not_paired(text):
    with pytest.raises(ValueError, match='不能根据项目名单'):
        edited_table(text)


def test_single_headerless_row_and_ratio_and_comparator():
    rows = extract_table_rows(edited_table('白/球 | 1.18 | ↓ - W | 1.2-2.4 |'))
    assert rows[0]['value'] == '1.18'
    assert apply_table_template(rows, 'all')[0]['item_standard'] == 'A/G'
    rows = extract_table_rows(edited_table('总胆红素 | 9.40 | <23 | umol/L'))
    assert rows[0]['value'] == '9.40'
    assert rows[0]['payload_json']['reference_raw'] == '<23'
    # Without another result cell, a lone bound could be a reference interval.
    rows = extract_table_rows(edited_table('总胆红素 | <23 | umol/L'))
    assert rows[0]['value'] == ''
    assert attention_for(rows[0])['warnings']


def test_partial_header_must_not_reinterpret_history_as_current_result():
    block = TableBlock(page=0, html='', rows=[['项目名称','历史结果'],['白细胞计数','8']])
    assert extract_table_rows(block) == []
    text = '项目名称|结果|历史结果|参考值|单位\n白细胞计数||8|3.5-9.5|10^9/L'
    assert extract_table_rows(edited_table(text)) == []


def test_service_fallback_reads_headerless_text_without_html(tmp_path, monkeypatch):
    from clinical_extractor import db, service, table_ai
    monkeypatch.setattr(config, 'DB_PATH', tmp_path/'reports.sqlite3')
    monkeypatch.setattr(table_ai, 'correct_names', lambda rows, template_id: rows)
    db.init_db()
    with db.connect() as con:
        rid = con.execute('''INSERT INTO reports(profile,filename,file_path,created_at,raw_text,parser_json,template_id)
                             VALUES(?,?,?,?,?,?,?)''', ('表格式报告','lipids.png','lipids.png',db.now_iso(),
                                                       LIPIDS,'[]','all')).lastrowid
    assert service.process_report(rid, 'llm') == 8
    with db.connect() as con:
        assert con.execute('SELECT status FROM reports WHERE id=?', (rid,)).fetchone()[0] == '待审核'
        results = con.execute('SELECT value FROM extractions WHERE report_id=? ORDER BY sort_order', (rid,)).fetchall()
        assert [r[0] for r in results] == ['3.58','0.82','1.06','2.16','0.36','0.99','0.62','42.7']
    from fastapi.testclient import TestClient
    from clinical_extractor import main
    with TestClient(main.app) as client:
        page = client.get(f'/report/{rid}').text
        assert page.count('id="headerless-table-note"') == 1
        assert '<small>本报告部分表格未识别到表头，已按行解析。</small>' in page
        assert '缺少结果' not in page
