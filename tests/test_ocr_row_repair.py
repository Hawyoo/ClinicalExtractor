import copy
import json
from types import SimpleNamespace

import numpy as np

from clinical_extractor.ocr_row_repair import repair_cross_row_boxes, result_rows, assignment_warnings
from clinical_extractor.parser import coordinate_table_rows, TableBlock
from clinical_extractor.table_extractor import extract_table_rows


def merged_document():
    pairs = [('项目名称',[0,0,80,20]),('结果',[150,0,200,20]),
             ('历史结果',[250,0,320,20]),('参考值',[350,0,410,20]),('单位',[450,0,500,20]),
             ('AlphaBetaGamma',[0,90,80,330])]
    for i,value in enumerate(('11','22','33'),1):
        pairs += [(value,[150,100*i,190,100*i+20]),('99',[250,100*i,290,100*i+20])]
    return dict(rec_texts=[p[0] for p in pairs],rec_boxes=[p[1] for p in pairs],rec_scores=[.99]*len(pairs))


def test_generic_cross_row_repair_uses_pixels_not_analyte_replacements():
    ocr = merged_document()
    original_values = [r[1] for r in result_rows(ocr)]
    labels = iter(['Alpha','Beta','Gamma'])
    recognizer = lambda images: iter([{'rec_text':next(labels),'rec_score':.99}])
    pipeline = SimpleNamespace(predict=lambda **kwargs:iter([]))
    repairs = repair_cross_row_boxes(ocr,np.zeros((400,600,3),dtype=np.uint8),pipeline,recognizer)
    assert [r[1] for r in result_rows(ocr)] == original_values == ['11','22','33']
    rows = coordinate_table_rows(ocr)
    table = TableBlock(0,'',rows,row_repairs=repairs)
    records = extract_table_rows(table)
    assert [(r['item_original'],r['value']) for r in records] == [('Alpha','11'),('Beta','22'),('Gamma','33')]
    assert all('item_correction' in r['payload_json'] for r in records)
    assert assignment_warnings(ocr,[table]) == []


def test_failed_repair_never_splits_text_or_duplicates_values():
    ocr = merged_document()
    original = copy.deepcopy(ocr)
    recognizer = lambda images:iter([{'rec_text':'unreliable','rec_score':.1}])
    assert repair_cross_row_boxes(ocr,np.zeros((400,600,3),dtype=np.uint8),
                                 SimpleNamespace(predict=lambda **kwargs:iter([])),recognizer) == []
    assert ocr['rec_texts'] == original['rec_texts']
    assert coordinate_table_rows(ocr) == []
    assert [warning['value'] for warning in assignment_warnings(ocr,[])] == ['11','22','33']


def test_assignment_counts_repeated_equal_results_individually():
    ocr = merged_document()
    ocr['rec_texts'][8] = '11'  # second current result, not its historical value
    table = TableBlock(0,'',[['项目','结果'],['Alpha','11']])
    warnings = assignment_warnings(ocr,[table])
    assert len(warnings) == 2
    assert [w['value'] for w in warnings] == ['11','33']


def test_number_header_prefix_does_not_mark_every_result_as_duplicate():
    from clinical_extractor.ocr_row_repair import saved_assignment_warnings
    from clinical_extractor.parser import table_region
    ocr = merged_document()
    ocr['rec_texts'][0] = 'No项目名称'
    ocr['rec_texts'][5] = 'Alpha'
    ocr['rec_boxes'][5] = [0,100,80,120]
    ocr['rec_texts'].extend(['Beta','Gamma'])
    ocr['rec_boxes'].extend([[0,200,80,220],[0,300,80,320]])
    assert [row[1] for row in result_rows(ocr)] == ['11','22','33']
    rows = coordinate_table_rows(ocr)
    assert [r['value'] for r in extract_table_rows(TableBlock(0,'',rows))] == ['11','22','33']
    assert table_region(ocr, (400,600,3))
    html = '<table><tr><td>项目名称</td><td>结果</td></tr>' + ''.join(
        f'<tr><td>{name}</td><td>{value}</td></tr>' for name,value in [('Alpha','11'),('Beta','22'),('Gamma','33')]) + '</table>'
    page = dict(overall_ocr_res=ocr,table_res_list=[{'pred_html':html}],
                row_warnings=[{'message':'obsolete duplicate warning'}])
    assert saved_assignment_warnings(page) == []


def test_unavailable_source_column_is_not_evidence_of_duplicate_results():
    ocr = merged_document()
    ocr['rec_texts'][0] = '无法辨认的表头'
    table = TableBlock(0,'',[['项目','结果'],['Alpha','11'],['Beta','22']])
    warnings = assignment_warnings(ocr,[table])
    assert len(warnings) == 1
    assert warnings[0]['kind'] == 'verification_unavailable'


def test_real_duplicate_assignment_is_still_reported():
    ocr = merged_document()
    table = TableBlock(0,'',[['项目','结果'],['Alpha','11'],['Beta','22'],['Gamma','33'],['Extra','11']])
    warnings = assignment_warnings(ocr,[table])
    assert len(warnings) == 1 and warnings[0]['value'] == '11'
    assert '配对数量超过' in warnings[0]['message']


def test_ai_accepts_fenced_json_but_still_cannot_generate_values(monkeypatch):
    from clinical_extractor import table_ai, text_extractor
    raw = '```json\n'+json.dumps({'matches':[{'row_id':'0','code':'WBC','reason':'匹配模板'}]})+'\n```'
    fake = SimpleNamespace(infer=lambda prompts:iter([[SimpleNamespace(output=raw)]]))
    monkeypatch.setattr(text_extractor,'_progress_model',lambda settings:fake)
    monkeypatch.setattr(table_ai,'load_settings',lambda:SimpleNamespace(mock_mode=False))
    rows = [dict(item_original='白细胞计数',unit='10^9/L',value='5.1',payload_json={})]
    result = table_ai.correct_names(rows,'cbc')
    assert result[0]['payload_json']['ai_template_code'] == 'WBC'
    assert result[0]['value'] == '5.1'
