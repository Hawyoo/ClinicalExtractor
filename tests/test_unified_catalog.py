from copy import deepcopy
from io import BytesIO

from fastapi.testclient import TestClient

from clinical_extractor.report_templates import table_templates, merge_templates, apply_table_template


def test_all_catalog_preserves_distinct_codes_and_matches_mixed_partial_report():
    catalog=table_templates()
    definitions=catalog['all']['items']
    assert len(definitions)==len({item['code'] for item in definitions})==73
    assert {'UREA','BUN','HCO3','CO2CP'}.issubset({item['code'] for item in definitions})
    rows=[dict(item_original='同型半胱氨酸',value='12.00',unit='umol/L'),
          dict(item_original='白细胞计数',value='3.46',unit='10^9/L'),
          dict(item_original='尿素氮',value='5.20',unit='mmol/L'),
          dict(item_original='二氧化碳结合力',value='24.4',unit='mmol/L'),
          dict(item_original='无法辨别的指标',value='7.1',unit='mmol/L',reference_low='20',reference_high='31')]
    output=apply_table_template(deepcopy(rows),'all')
    assert [r['item_standard'] for r in output[:4]]==['HCY','WBC','BUN','CO2CP']
    assert [r['value'] for r in output]==[r['value'] for r in rows]
    assert 'template_warning' in output[-1]['payload_json']
    assert len(output)==len(rows)
    rows[-1]['payload_json']={'ai_template_code':'HCO3'}
    assert 'template_warning' in apply_table_template(deepcopy(rows),'all')[-1]['payload_json']


def test_duplicate_definition_merges_aliases_and_reference_variants_without_mutating_sources():
    sources={'one':{'items':[dict(code='X',name='指标一',aliases=['名称甲'],expected_unit='umol/L',reference_range='1-2')]},
             'two':{'items':[dict(code='X',name='指标一别名',aliases=['名称乙'],expected_unit='umol/L',reference_range='3-4',alternative_reference_ranges=['5-6']),
                             dict(code='Y',name='另一个指标',expected_unit='umol/L',reference_range='1-2')]}}
    original=deepcopy(sources)
    output=merge_templates(sources)
    assert len(output['items'])==2
    assert set(output['items'][0]['aliases'])=={'名称甲','名称乙','指标一别名'}
    assert output['items'][0]['alternative_reference_ranges']==['3-4','5-6']
    assert sources==original


def test_upload_metadata_and_legacy_reports_use_all_without_template_controls(tmp_path,monkeypatch):
    from clinical_extractor import db,main
    monkeypatch.setattr(db,'DB_PATH',tmp_path/'reports.sqlite3')
    monkeypatch.setattr(main,'UPLOAD_DIR',tmp_path)
    db.init_db()
    with db.connect() as con:
        rid=con.execute('''INSERT INTO reports(filename,file_path,profile,template_id,created_at)
                           VALUES(?,?,?,?,?)''',('old.jpg','old.jpg','表格式报告','cbc',db.now_iso())).lastrowid
        con.execute('INSERT INTO extractions(report_id,item_standard,value,reviewed) VALUES(?,?,?,?)',(rid,'WBC','3.46',1))
    with TestClient(main.app) as client:
        with db.connect() as con:
            assert con.execute('SELECT template_id FROM reports WHERE id=?',(rid,)).fetchone()[0]=='all'
            assert con.execute('SELECT value,reviewed FROM extractions WHERE report_id=?',(rid,)).fetchone()['reviewed']==1
        page=client.get(f'/report/{rid}').text
        assert 'name="template_id"' not in page
        assert '套用模板' not in page
        home=client.get('/').text
        assert "select('template_ids'" not in home
        response=client.post('/upload',files=[('files',('mixed.txt',BytesIO(b'OCR source'),'text/plain'))],
                             data={'profiles':'表格式报告','template_ids':'cbc'},follow_redirects=False)
        assert response.status_code==303
        with db.connect() as con:
            newest=con.execute('SELECT id,template_id FROM reports ORDER BY id DESC LIMIT 1').fetchone()
            assert newest['template_id']=='all'
        client.post(f'/report/{rid}/metadata',data={'patient_id':'P','profile':'表格式报告','template_id':'liver_kidney'})
        with db.connect() as con:
            assert con.execute('SELECT template_id FROM reports WHERE id=?',(rid,)).fetchone()[0]=='all'
