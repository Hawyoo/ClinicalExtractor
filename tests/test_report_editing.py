from clinical_extractor import config
import json
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from bs4 import BeautifulSoup

from clinical_extractor import db,main,service,exporter
from clinical_extractor.parser import TableBlock
from clinical_extractor.report_editing import edited_table
from clinical_extractor.table_extractor import extract_table_rows


@pytest.fixture
def report(tmp_path,monkeypatch):
    monkeypatch.setattr(config, 'DB_PATH',tmp_path/'reports.sqlite3')
    db.init_db()
    raw='项目名称\t结果\t单位\n白细胞计数\t5.1\t10^9/L'
    html='<table><tr><td>项目名称</td><td>结果</td><td>单位</td></tr><tr><td>白细胞计数</td><td>5.1</td><td>10^9/L</td></tr></table>'
    with db.connect() as con:
        rid=con.execute('''INSERT INTO reports(filename,file_path,profile,template_id,status,raw_text,parser_json,created_at)
                           VALUES(?,?,?,?,?,?,?,?)''',('sample.png','sample.png','表格式报告','all','已审核',raw,
                           json.dumps([{'table_res_list':[{'pred_html':html}]}]),db.now_iso())).lastrowid
        eid=con.execute('INSERT INTO extractions(report_id,item_original,item_standard,value,unit,reviewed,sort_order) VALUES(?,?,?,?,?,?,?)',
                        (rid,'白细胞计数','WBC','5.1','10^9/L',1,1)).lastrowid
    return rid,eid,raw


def test_saved_ocr_text_is_actual_ai_input_and_original_can_be_restored(report,monkeypatch):
    rid,eid,original=report
    from clinical_extractor import table_ai
    monkeypatch.setattr(table_ai,'correct_names',lambda rows,template_id:rows)
    queued=[]
    monkeypatch.setattr(main,'start_job',lambda rid,stage:queued.append((rid,stage)))
    edited=original.replace('5.1','5.8')
    with TestClient(main.app) as client:
        result=client.post(f'/report/{rid}/ocr-text',headers={'Accept':'application/json'},data={'text':edited,'action':'save_ai'})
        assert result.json()['saved'] and result.json()['queued']
        assert queued==[(rid,'llm')]
        with db.connect() as con:
            stored=con.execute('SELECT * FROM reports WHERE id=?',(rid,)).fetchone()
            assert stored['raw_text']==edited and stored['ocr_text_original']==original
            assert stored['ocr_text_edited']==1
            assert con.execute('SELECT value,reviewed FROM extractions WHERE id=?',(eid,)).fetchone()['value']=='5.1'
            assert con.execute('SELECT reviewed FROM extractions WHERE id=?',(eid,)).fetchone()[0]==0
        assert service.process_report(rid,'llm')==1
        assert exporter.dataframe().iloc[0]['result']=='5.8'
        restored=client.post(f'/report/{rid}/ocr-text',headers={'Accept':'application/json'},data={'action':'restore'})
        assert restored.json()['text']==original and not restored.json()['edited']
        assert service.process_report(rid,'llm')==1
        assert exporter.dataframe().iloc[0]['result']=='5.1'
        with db.connect() as con:
            assert con.execute('SELECT COUNT(*) FROM ocr_text_revisions WHERE report_id=?',(rid,)).fetchone()[0]==2


def test_names_only_edited_text_never_generates_results(report):
    rid,eid,_=report
    with TestClient(main.app) as client:
        assert client.post(f'/report/{rid}/ocr-text',data={'text':'白细胞计数\n红细胞计数'}).status_code==200
        with pytest.raises(ValueError,match='不能根据项目名单'):
            service.process_report(rid,'llm')
        with db.connect() as con:
            assert con.execute('SELECT value FROM extractions WHERE id=?',(eid,)).fetchone()[0]=='5.1'


def test_manual_rows_insert_at_selected_position_export_and_survive_reprocessing(report):
    rid,eid,_=report
    with TestClient(main.app) as client:
        first=client.post(f'/report/{rid}/extractions/add',headers={'Accept':'application/json'},
                          data={'item_name':'血红蛋白','value':'119','after_eid':eid}).json()
        assert first['added'] and first['after_eid']==eid
        assert 'g/L' in first['html']
        second=client.post(f'/report/{rid}/extractions/add',headers={'Accept':'application/json'},
                           data={'item_name':'血小板计数','value':'200','after_eid':'0'}).json()
        assert second['after_eid']==0
        assert exporter.dataframe()['item_abbr'].tolist()==['PLT','WBC','HGB']
        duplicate=client.post(f'/report/{rid}/extractions/add',data={'item_name':'HGB','value':'88'})
        assert duplicate.status_code==409
        with db.connect() as con:
            assert con.execute('SELECT reviewed FROM extractions WHERE id=?',(first['eid'],)).fetchone()[0]==0
            count=service._store_extractions(con,rid,[dict(item_original='WBC',item_standard='WBC',value='5.8'),
                                                    dict(item_original='HGB',item_standard='HGB',value='88')])
            assert count==3
            assert con.execute('SELECT value FROM extractions WHERE id=?',(first['eid'],)).fetchone()[0]=='119'
        assert exporter.dataframe()['result'].tolist()==['200','5.8','119']
        page=BeautifulSoup(client.get(f'/report/{rid}').text,'html.parser')
        assert [row.select_one('[name=value]')['value'] for row in page.select('[data-review-row]')]==['200','5.8','119']


def test_editing_and_adding_are_blocked_while_report_is_busy(report,monkeypatch):
    rid,eid,_=report
    monkeypatch.setattr(main,'is_busy',lambda rid:True)
    with TestClient(main.app) as client:
        assert client.post(f'/report/{rid}/ocr-text',data={'text':'new'}).status_code==409
        assert client.post(f'/report/{rid}/extractions/add',data={'item_name':'HGB','value':'119'}).status_code==409
        with db.connect() as con:
            assert con.execute('SELECT COUNT(*) FROM ocr_text_revisions').fetchone()[0]==0
            assert con.execute('SELECT COUNT(*) FROM extractions WHERE report_id=?',(rid,)).fetchone()[0]==1


def test_tab_and_markdown_empty_cells_do_not_borrow_history():
    for text in ['项目名称\t结果\t历史结果\t单位\n白细胞计数\t\t9.9\t10^9/L',
                 '| 项目名称 | 结果 | 历史结果 | 单位 |\n|---|---|---|---|\n|白细胞计数||9.9|10^9/L|']:
        assert extract_table_rows(edited_table(text))==[]


def test_edited_text_and_manual_order_survive_transfer(report,tmp_path,monkeypatch):
    from clinical_extractor import transfer
    rid,eid,original=report
    with TestClient(main.app) as client:
        client.post(f'/report/{rid}/ocr-text',data={'text':original.replace('5.1','5.8')})
        assert client.post(f'/report/{rid}/extractions/add',data={'item_name':'HGB','value':'119','after_eid':'0'}).status_code==200
    packet=tmp_path/'edited.ceocr'
    transfer.create_transfer(packet)
    monkeypatch.setattr(config, 'DB_PATH',tmp_path/'destination.sqlite3')
    monkeypatch.setattr(config, 'UPLOAD_DIR',tmp_path)
    db.init_db()
    transfer.import_transfer(packet)
    with db.connect() as con:
        incoming=con.execute('SELECT * FROM reports').fetchone()
        assert incoming['raw_text'].endswith('5.8\t10^9/L')
        assert incoming['ocr_text_original']==original and incoming['ocr_text_edited']==1
        assert [r['item_standard'] for r in con.execute('SELECT item_standard FROM extractions ORDER BY sort_order,id')]==['HGB','WBC']
