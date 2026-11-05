from fastapi.testclient import TestClient
from clinical_extractor import db, main, exporter
import json
from bs4 import BeautifulSoup


def test_confirmation_and_export_keep_internal_checks(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'review.sqlite3')
    db.init_db()
    with db.connect() as con:
        rid = con.execute('''INSERT INTO reports(patient_id,profile,filename,file_path,created_at,template_id)
                             VALUES(?,?,?,?,?,?)''', ('test','表格式报告','a.jpg','a.jpg',db.now_iso(),'cbc')).lastrowid
        eid = con.execute('''INSERT INTO extractions(report_id,item_standard,item_original,value,unit,reference_low,reference_high,abnormal_flag)
                             VALUES(?,?,?,?,?,?,?,?)''', (rid,'HGB','HGB','100','g/L','130','175','低')).lastrowid
    with TestClient(main.app) as client:
        html = client.get(f'/report/{rid}').text
        assert '血红蛋白浓度' in html
        assert 'type="checkbox"' not in html
        assert 'name="reference_low"' not in html
        assert client.post(f'/extraction/{eid}/update', data={
            'item_standard':'血红蛋白浓度','value':'110','unit':'g/L'}).status_code == 200
        frame = exporter.dataframe(True)
        assert frame.iloc[0]['item_name'] == '血红蛋白浓度'
        assert frame.iloc[0]['item_abbr'] == 'HGB'
        assert frame.iloc[0]['result'] == '110'
        assert not {'reference_low','reference_high','abnormal_flag','参考下限','参考上限','异常'} & set(frame.columns)
        assert client.post(f'/report/{rid}/mark-reviewed', data={
            'eids':str(eid),'names':'血红蛋白','values':'115','units':'g/L'}).status_code == 200
    with db.connect() as con:
        item = con.execute('SELECT * FROM extractions WHERE id=?',(eid,)).fetchone()
        assert (item['reference_low'],item['reference_high'],item['abnormal_flag']) == ('130','175','低')
        assert item['value_num'] == 115 and item['reviewed'] == 1
    assert exporter.dataframe(True).iloc[0]['item_name'] == '血红蛋白浓度'


def test_export_column_names_are_r_friendly(tmp_path, monkeypatch):
    import re
    import pandas as pd
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'export.sqlite3')
    db.init_db()
    with db.connect() as con:
        rid = con.execute('''INSERT INTO reports(patient_id,filename,file_path,created_at)
                             VALUES(?,?,?,?)''', ('00001','a.jpg','a.jpg',db.now_iso())).lastrowid
        con.execute('''INSERT INTO extractions(report_id,item_standard,value,unit,reviewed)
                       VALUES(?,?,?,?,?)''',(rid,'WBC','5.2','10^9/L',1))
    expected = ['patient_id','report_type','file_name','item_name','item_abbr','result','unit','reviewed']
    assert all(re.fullmatch('[a-z][a-z0-9_]*', col) for col in exporter.dataframe().columns)
    assert list(exporter.dataframe().columns) == expected
    path = exporter.export_xlsx(tmp_path / 'result.xlsx')
    saved = pd.read_excel(path, dtype={'patient_id':str})
    assert list(saved.columns) == expected
    assert saved.iloc[0]['item_name'] == '白细胞计数'
    assert saved.iloc[0]['item_abbr'] == 'WBC'
    assert saved.iloc[0]['patient_id'] == '00001'
    assert saved.iloc[0]['reviewed'] == 1
    csv = exporter.export_csv(tmp_path / 'result.csv')
    assert pd.read_csv(csv).columns.tolist() == expected


def test_review_attention_hides_clean_rows_and_prioritizes_warnings(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'attention.sqlite3')
    db.init_db()
    with db.connect() as con:
        rid = con.execute('''INSERT INTO reports(patient_id,profile,filename,file_path,created_at,template_id)
                             VALUES(?,?,?,?,?,?)''', ('test','表格式报告','a.jpg','a.jpg',db.now_iso(),'cbc')).lastrowid
        ids = []
        for code, payload, evidence in [
            ('WBC', {'template_alignment':'名称/范围/单位一致'}, 'clean-evidence'),
            ('MCV', {'item_correction':'项目名称已校正', 'unit_correction':'f → fL'}, 'corrected-evidence'),
            ('RBC', {'template_warning':'候选冲突'}, 'warning-evidence'),
            ('PLT', {'unit_correction':'单位写法已统一'}, 'unit-only-evidence'),
        ]:
            ids.append(con.execute('''INSERT INTO extractions(report_id,item_standard,value,unit,payload_json,evidence)
                                      VALUES(?,?,?,?,?,?)''',
                                   (rid,code,'5','',json.dumps(payload,ensure_ascii=False),evidence)).lastrowid)
    with TestClient(main.app) as client:
        soup = BeautifulSoup(client.get(f'/report/{rid}').text, 'html.parser')
    details = soup.select_one('#review-attention-records')
    assert 'clean-evidence' not in details.get_text()
    assert 'unit-only-evidence' not in details.get_text()
    assert 'f → fL' not in details.get_text()
    assert [entry['id'] for entry in details.select('.attention-evidence')] == [f'audit-{ids[2]}',f'audit-{ids[1]}']
    rows = soup.select('[data-review-row]')
    assert not rows[0].select('.review-marker')
    assert soup.select_one(f'[data-review-row="{ids[1]}"] .review-marker').get_text() == '智能纠错'
    assert soup.select_one(f'[data-review-row="{ids[2]}"] .review-marker').get_text() == '待核对'
    assert not soup.select_one(f'[data-review-row="{ids[3]}"] .review-marker')


def test_preview_export_order_and_json_confirmation(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'ordered.sqlite3')
    db.init_db()
    with db.connect() as con:
        rid = con.execute('''INSERT INTO reports(patient_id,profile,filename,file_path,created_at,template_id)
                             VALUES(?,?,?,?,?,?)''', ('test','表格式报告','a.jpg','a.jpg',db.now_iso(),'cbc')).lastrowid
        ids = {}
        for code in ['PLT','其他项目','HGB','WBC']:
            ids[code] = con.execute('''INSERT INTO extractions(report_id,item_standard,value,unit)
                                      VALUES(?,?,?,?)''', (rid,code,'5','g/L')).lastrowid
    with TestClient(main.app) as client:
        soup = BeautifulSoup(client.get(f'/report/{rid}').text,'html.parser')
        assert [int(row['data-review-row']) for row in soup.select('[data-review-row]')] == [ids[c] for c in ['PLT','其他项目','HGB','WBC']]
        response = client.post(f'/extraction/{ids["WBC"]}/update',headers={'Accept':'application/json'},
                               data={'item_standard':'白细胞计数','value':'6.2','unit':'10^9/L'})
        assert response.status_code == 200
        assert not response.history and response.json() == {'reviewed':True,'report_reviewed':False}
        response = client.post(f'/report/{rid}/mark-reviewed',headers={'Accept':'application/json'},
                               data={'eids':str(ids['HGB']),'names':'血红蛋白浓度','values':'130','units':'g/L'})
        assert not response.history and response.json()['report_reviewed']
        assert soup.select_one('script[src^="/static/review.js"]')
    frame = exporter.dataframe(True)
    assert frame['item_name'].tolist() == ['血小板计数','其他项目','血红蛋白浓度','白细胞计数']
    assert frame['result'].tolist() == ['5','5','130','6.2']
