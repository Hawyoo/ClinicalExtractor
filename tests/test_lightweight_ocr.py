import json
from types import SimpleNamespace

from clinical_extractor.parser import PPStructureParser, lightweight_pipeline_config


def test_pipeline_loads_only_three_models():
    config = lightweight_pipeline_config()
    assert not config['use_layout_detection']
    assert not config['use_doc_preprocessor']
    assert list(config['SubModules']) == ['TableStructureRecognition']
    assert config['SubModules']['TableStructureRecognition']['model_name'] == 'SLANet_plus'
    ocr = config['SubPipelines']['GeneralOCR']
    assert not ocr['use_textline_orientation']
    assert {m['model_name'] for m in ocr['SubModules'].values()} == {
        'PP-OCRv5_server_det', 'PP-OCRv5_server_rec'}
    assert lightweight_pipeline_config(False) == ocr


def test_json_coordinates_and_per_image_results_are_preserved(tmp_path, monkeypatch):
    from clinical_extractor import parser
    monkeypatch.setattr(parser, 'load_settings', lambda: SimpleNamespace(mock_mode=False))
    html = '<table><tr><td>项目</td><td>结果</td></tr><tr><td>WBC</td><td>5.1</td></tr></table>'
    payloads = [dict(overall_ocr_res=dict(rec_texts=['WBC', '5.1'],
                        rec_boxes=[[0, 0, 10, 10], [20, 0, 30, 10]]),
                     table_res_list=[dict(pred_html=html)]),
                dict(overall_ocr_res=dict(rec_texts=['只有项目名称'], rec_boxes=[]), table_res_list=[])]
    pipeline = SimpleNamespace(predict=lambda **kwargs: iter([SimpleNamespace(json={'res': payloads.pop(0)})]))
    instance = PPStructureParser()
    monkeypatch.setattr(instance, '_get_pipeline', lambda table_mode: pipeline)
    first = instance.parse(tmp_path / 'first.png')
    second = instance.parse(tmp_path / 'second.png')
    assert first.tables[0].rows[1] == ['WBC', '5.1']
    assert first.parser_json[0]['overall_ocr_res']['rec_boxes'][0] == [0, 0, 10, 10]
    json.dumps(first.parser_json)
    assert second.tables == []
    assert second.raw_text == '只有项目名称'
    assert '5.1' not in second.raw_text


def test_long_text_skips_tables(tmp_path, monkeypatch):
    from clinical_extractor import parser
    monkeypatch.setattr(parser, 'load_settings', lambda: SimpleNamespace(mock_mode=False))
    pipeline = SimpleNamespace(predict=lambda **kwargs: iter([SimpleNamespace(
        json={'res': {'rec_texts': ['病理结果'], 'rec_boxes': [[1, 2, 3, 4]]}})]))
    instance = PPStructureParser()
    monkeypatch.setattr(instance, '_get_pipeline', lambda table_mode: pipeline if not table_mode else None)
    result = instance.parse(tmp_path / 'pathology.jpg', table_mode=False)
    assert result.raw_text == '病理结果'
    assert result.tables == []
    assert result.parser_json[0]['ocr_pipeline'] == 'PP-OCRv5'


def test_coordinate_rows_never_borrow_history_or_join_two_values():
    from clinical_extractor.parser import coordinate_table_rows
    pairs = [('项目', [0,0,80,20]), ('结果',[150,0,200,20]),
             ('历史结果',[250,0,320,20]), ('参考值',[350,0,410,20]), ('单位',[450,0,500,20])]
    for i, name in enumerate(('WBC', 'HGB', 'PLT', 'RBC'), 1):
        pairs.append((name,[0,i*100,80,i*100+20]))
        pairs.append(('99',[250,i*100,280,i*100+20]))
    pairs += [('5.1',[150,100,180,120]), ('190',[150,300,180,320]),
              ('200',[185,300,210,320]), ('4.3',[150,400,180,420])]
    rows = coordinate_table_rows(dict(rec_texts=[p[0] for p in pairs],rec_boxes=[p[1] for p in pairs]))
    assert [(r[0],r[1]) for r in rows[1:]] == [('WBC','5.1'),('RBC','4.3')]


def test_merged_numeric_cell_is_not_a_result():
    from clinical_extractor.parser import TableBlock
    from clinical_extractor.table_extractor import extract_table_rows
    assert not extract_table_rows(TableBlock(page=0,html='',rows=[['项目','结果'],['LDH','2.8 184']]))


def test_first_row_overlapping_other_columns_header_is_preserved():
    from clinical_extractor.parser import coordinate_table_rows
    pairs = [('项目名称',[0,0,80,20]), ('结果',[150,10,200,30]),
             ('参考值',[350,15,410,35]), ('单位',[450,20,500,40]),
             ('总胆红素',[0,30,80,50]), ('13.50',[150,40,200,60]),
             ('<23',[350,45,390,65]), ('umol/L',[450,50,500,70]),
             ('直接胆红素',[0,130,80,150]), ('3.16',[150,140,200,160]),
             ('<4',[350,145,390,165]), ('umol/L',[450,150,500,170])]
    rows = coordinate_table_rows(dict(rec_texts=[p[0] for p in pairs],rec_boxes=[p[1] for p in pairs]))
    assert [(r[0],r[1]) for r in rows[1:]] == [('总胆红素','13.50'),('直接胆红素','3.16')]
    assert rows[1][2:] == ['<23','umol/L']


def test_json_drops_embedded_images_but_keeps_numeric_coordinates():
    import numpy as np
    from clinical_extractor.parser import result_data
    result = result_data({'res': {'overall_ocr_res': {'rec_boxes':np.array([[1,2,3,4]]),
               'doc_preprocessor_res': {'output_img':np.zeros((20,30,3))}}}})
    assert result['overall_ocr_res']['rec_boxes'] == [[1,2,3,4]]
    assert 'output_img' not in result['overall_ocr_res']['doc_preprocessor_res']
    json.dumps(result)


def test_tilted_columns_and_missing_unit_do_not_shift_units_to_next_row():
    from clinical_extractor.parser import coordinate_table_rows
    pairs = [('项目名称',[0,0,80,80]),('结果',[150,15,200,95]),
             ('参考值',[350,45,410,125]),('单位',[450,65,500,145])]
    for i in range(8):
        y = 200+i*110
        pairs.append((f'Analyte{i}',[0,y-30,60,y+30]))
        vy = 55+(y-40)/1.02
        pairs.append((str(i+1),[150,vy-30,200,vy+30]))
        ry = 85+(y-40)/1.03
        pairs.append((f'{i}-{i+10}',[350,ry-30,410,ry+30]))
        if i != 3:
            uy = 105+(y-40)/1.04
            pairs.append((f'unit{i}',[450,uy-30,500,uy+30]))
    rows = coordinate_table_rows(dict(rec_texts=[p[0] for p in pairs],rec_boxes=[p[1] for p in pairs]))
    assert len(rows)==9
    assert [r[1] for r in rows[1:]] == [str(i+1) for i in range(8)]
    assert [r[3] for r in rows[1:]] == [f'unit{i}' if i!=3 else '' for i in range(8)]
    assert [r[2] for r in rows[1:]] == [f'{i}-{i+10}' for i in range(8)]
