from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from clinical_extractor import table_pairing
from clinical_extractor.review import attention_for


def sample():
    pairs=[('项目名称',[0,0,80,20]),('结果',[150,0,200,20]),('参考值',[350,0,410,20]),('单位',[450,0,500,20])]
    for i,(name,value,ref) in enumerate([('eGFR-EPI','11','>90 208-428'),('尿酸','22',''),('胱抑素C','33','1-3')],1):
        pairs += [(name,[0,i*100,80,i*100+20]),(value,[150,i*100,190,i*100+20]),
                  (ref,[350,i*100,410,i*100+20]),('U/L',[450,i*100,500,i*100+20])]
    page=dict(page_index=0,overall_ocr_res=dict(rec_texts=[t for t,_ in pairs],rec_boxes=[b for _,b in pairs]))
    rows=[dict(item_original=n,value=v,unit='U/L',page=0,evidence=f'{n} | {v} | {r}',payload_json={'reference_raw':r})
          for n,v,r in [('eGFR-EPI','22','>90 208-428'),('尿酸','11',''),('胱抑素C','33','1-3')]]
    _,values,refs=table_pairing.sources(page)
    vid={v['text']:v['id'] for v in values};rid={r['text']:r['id'] for r in refs}
    proposal=[dict(row_id=str(i),value_id=vid[v],reference_id=rid[r]) for i,(v,r) in enumerate([('11','>90'),('22','208-428'),('33','1-3')])]
    return rows,page,proposal


def model(monkeypatch,response):
    from clinical_extractor import config,text_extractor
    monkeypatch.setattr(config,'load_settings',lambda:SimpleNamespace(mock_mode=False))
    fake=SimpleNamespace(infer=lambda prompts:iter([[SimpleNamespace(output=json.dumps({'matches':response}))]]))
    monkeypatch.setattr(text_extractor,'_progress_model',lambda settings:fake)


def test_ai_moves_only_existing_cells_and_preserves_original_audit(monkeypatch):
    rows,page,proposal=sample();original=deepcopy(rows)
    model(monkeypatch,proposal)
    result=table_pairing.repair_pairings(rows,[page])
    assert rows==original
    assert [r['value'] for r in result]==['11','22','33']
    assert [r['payload_json']['reference_raw'] for r in result]==['>90','208-428','1-3']
    for row in result[:2]:
        audit=row['payload_json']['ai_pairing']
        assert audit['value_source']['text']==row['value']
        assert audit['value_source']['box']
        assert audit['before']['evidence']
        assert attention_for(row)['label']=='AI重新配对'
        assert attention_for(row)['priority']==-1
    assert 'ai_pairing' not in result[2]['payload_json']


@pytest.mark.parametrize('attack',['invent','duplicate_value','duplicate_reference','extra_number','partial_steal','wrong_column'])
def test_invalid_model_assignments_never_change_results(monkeypatch,attack):
    rows,page,proposal=sample()
    if attack=='invent':proposal[0]['value_id']='99999'
    elif attack=='duplicate_value':proposal[1]['value_id']=proposal[0]['value_id']
    elif attack=='duplicate_reference':proposal[1]['reference_id']=proposal[0]['reference_id']
    elif attack=='extra_number':proposal[0]['value']='99999'
    elif attack=='partial_steal':proposal=proposal[:1]
    else:proposal[0]['value_id']=proposal[0]['reference_id']
    model(monkeypatch,proposal)
    result=table_pairing.repair_pairings(rows,[page])
    assert [r['value'] for r in result]==[r['value'] for r in rows]
    assert [r['payload_json']['reference_raw'] for r in result]==[r['payload_json']['reference_raw'] for r in rows]
    assert all('ai_pairing' not in r['payload_json'] for r in result)


def test_red_pairing_marker_is_rendered_in_review_row():
    from clinical_extractor.main import templates
    from bs4 import BeautifulSoup
    row=dict(id=1,display_name='Alpha',value='11',unit='U/L',reviewed=0,
             payload_json={'ai_pairing':{'before':{'value':'22'},'after':{'value':'11'}}})
    row['attention']=attention_for(row)
    html=templates.env.get_template('extraction_row.html').render(x=row)
    soup=BeautifulSoup(html,'html.parser')
    assert soup.select_one('.row-ai-pairing .review-marker-pairing').text=='AI重新配对'


def test_quantity_audit_uses_repaired_results_instead_of_old_table_duplicates():
    from clinical_extractor.row_validation import saved_assignment_warnings
    rows,page,_=sample()
    page['table_res_list']=[{'pred_html':'<table><tr><td>项目</td><td>结果</td></tr>'
        '<tr><td>Alpha</td><td>11</td></tr><tr><td>Beta</td><td>11</td></tr><tr><td>Gamma</td><td>33</td></tr></table>'}]
    assert saved_assignment_warnings(page)
    for row,value in zip(rows,['11','22','33']):row['value']=value
    assert saved_assignment_warnings(page,rows)==[]


def test_clear_source_rows_cannot_be_swapped_even_if_ai_moves_their_ranges_too(monkeypatch):
    rows,page,proposal=sample()
    # Start from correct values; a missing interval triggers AI to inspect neighbors.
    for row,value in zip(rows,['11','22','33']):row['value']=value
    proposal[1]['value_id'],proposal[2]['value_id']=proposal[2]['value_id'],proposal[1]['value_id']
    proposal[1]['reference_id'],proposal[2]['reference_id']=proposal[2]['reference_id'],proposal[1]['reference_id']
    model(monkeypatch,proposal)
    result=table_pairing.repair_pairings(rows,[page])
    assert [r['value'] for r in result]==['11','22','33']
    assert all('ai_pairing' not in r['payload_json'] for r in result)


def test_merged_range_fragment_must_match_the_named_project(monkeypatch):
    rows,page,proposal=sample()
    proposal[0]['reference_id'],proposal[1]['reference_id']=proposal[1]['reference_id'],proposal[0]['reference_id']
    model(monkeypatch,proposal)
    result=table_pairing.repair_pairings(rows,[page])
    assert [r['value'] for r in result]==[r['value'] for r in rows]
    assert all('ai_pairing' not in r['payload_json'] for r in result)




def test_uric_acid_373_and_cystatin_1_11_cannot_be_swapped(monkeypatch):
    pairs=[('项目名称',[0,0,80,11]),('结果',[210,0,234,12]),('参考范围',[320,0,360,11]),('单位',[428,0,450,11]),
           ('21尿酸（URIC）',[2,235,65,245]),('373',[211,234,229,245]),('208-428',[320,234,356,245]),
           ('22胱抑素C(CysC)',[1,244,82,258]),('1.11',[209,245,231,257]),('0.50-1.03',[316,245,361,256])]
    page=dict(page_index=0,overall_ocr_res=dict(rec_texts=[t for t,_ in pairs],rec_boxes=[b for _,b in pairs]))
    rows=[dict(item_original=name,value=value,unit=unit,page=0,payload_json={'reference_raw':ref}) for name,value,unit,ref in
          [('21尿酸（URIC）','373','unol/L',''),('22胱抑素C(CysC)','1.11','mg/L','0.50-1.03')]]
    _,values,refs=table_pairing.sources(page)
    vids={t['text']:t['id'] for t in values};rids={t['text']:t['id'] for t in refs}
    proposal=[dict(row_id='0',value_id=vids['1.11'],reference_id=rids['0.50-1.03']),
              dict(row_id='1',value_id=vids['373'],reference_id=rids['208-428'])]
    model(monkeypatch,proposal)
    result=table_pairing.repair_pairings(rows,[page])
    assert [row['value'] for row in result]==['373','1.11']
    assert all('ai_pairing' not in row['payload_json'] for row in result)
