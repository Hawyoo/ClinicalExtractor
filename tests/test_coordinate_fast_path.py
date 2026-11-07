from copy import deepcopy
from types import SimpleNamespace

import numpy as np

from clinical_extractor.parser import LightweightPipeline, TableBlock, html_to_rows
from clinical_extractor.table_extractor import extract_table_rows


def page():
    pairs = [('项目名称',[0,0,80,20]),('结果',[150,0,200,20]),
             ('参考值',[350,0,410,20]),('单位',[450,0,500,20])]
    for i,(name,value) in enumerate([('白细胞计数','5.10'),('血红蛋白','119'),('血小板计数','228')],1):
        pairs += [(name,[0,100*i,100,100*i+20]),(value,[150,100*i,200,100*i+20]),
                  ('1-999',[350,100*i,400,100*i+20]),('U/L',[450,100*i,490,100*i+20])]
    return dict(rec_texts=[t for t,_ in pairs], rec_boxes=[b for _,b in pairs],
                rec_scores=[.99]*len(pairs), page_index=0,input_path='test.png',
                doc_preprocessor_res={'output_img':np.zeros((400,600,3),dtype=np.uint8)})


def setup(pages):
    calls = dict(ocr_loads=0,table_loads=0,table_runs=0)
    def factory(config,**kwargs):
        if config['pipeline_name']=='OCR':
            calls['ocr_loads']+=1
            return SimpleNamespace(predict=lambda **kwargs:iter([deepcopy(pages.pop(0))]))
        calls['table_loads']+=1
        assert config['use_ocr_model'] is False
        def predict(**kwargs):
            calls['table_runs']+=1
            yield dict(overall_ocr_res=kwargs['overall_ocr_res'],table_res_list=[{
                'pred_html':'<table><tr><td>项目</td><td>结果</td></tr><tr><td>白细胞计数</td><td>5.10</td></tr></table>'}])
        return SimpleNamespace(predict=predict)
    return LightweightPipeline(factory,{},True),calls


def test_reliable_coordinates_skip_both_table_loading_and_inference():
    pipeline,calls=setup([page()])
    result=list(pipeline.predict('test.png'))[0]
    assert calls==dict(ocr_loads=1,table_loads=0,table_runs=0)
    assert result['ocr_pipeline']=='PP-OCRv5+coordinates'
    assert result['row_warnings']==[]
    table=result['table_res_list'][0]
    rows=extract_table_rows(TableBlock(0,table['pred_html'],html_to_rows(table['pred_html'])))
    assert [(r['item_original'],r['value']) for r in rows]==[('白细胞计数','5.10'),('血红蛋白','119'),('血小板计数','228')]
    assert result['stage_timings']['table_seconds']==0


def test_unreliable_page_uses_fallback_then_next_reliable_page_skips_it(monkeypatch):
    broken=page()
    broken['rec_texts'][0]='无法定位的表头'
    pipeline,calls=setup([broken,deepcopy(broken),page()])
    first=list(pipeline.predict('first.png'))[0]
    assert first['ocr_pipeline']=='PP-OCRv5+SLANet_plus'
    assert calls==dict(ocr_loads=1,table_loads=1,table_runs=1)
    assert first['table_res_list'][0]['structure_source']=='SLANet_plus'
    list(pipeline.predict('second.png'))
    last=list(pipeline.predict('third.png'))[0]
    assert calls==dict(ocr_loads=1,table_loads=1,table_runs=2)
    assert last['ocr_pipeline']=='PP-OCRv5+coordinates'
    assert last['stage_timings']['table_seconds']==0


def test_incomplete_coordinate_pairing_falls_back_instead_of_silently_losing_a_value():
    damaged=page()
    damaged['rec_texts'][4]=''  # Lose the first item, retain its independent result.
    pipeline,calls=setup([damaged])
    result=list(pipeline.predict('test.png'))[0]
    assert calls['table_runs']==1
    assert result['ocr_pipeline']=='PP-OCRv5+SLANet_plus'


def test_packaging_can_still_prepare_fallback_without_processing_an_image():
    pipeline,calls=setup([])
    pipeline.prepare_fallback_model()
    pipeline.prepare_fallback_model()
    assert calls==dict(ocr_loads=1,table_loads=1,table_runs=0)
