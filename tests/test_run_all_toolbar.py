from types import SimpleNamespace

import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient


@pytest.mark.parametrize('ready',[True,False])
def test_run_all_skips_review_and_active_states_and_selects_ai_handoff(tmp_path,monkeypatch,ready):
    from clinical_extractor import db,main
    monkeypatch.setattr(db,'DB_PATH',tmp_path/'reports.sqlite3')
    monkeypatch.setattr(main,'resume_pending_jobs',lambda:None)
    monkeypatch.setattr(main,'ollama_available',lambda:ready)
    monkeypatch.setattr(main,'is_busy',lambda rid:False)
    calls=[]
    monkeypatch.setattr(main,'start_job',lambda rid,stage,then_ai=False:calls.append((rid,stage,then_ai)))
    db.init_db()
    states=['未处理','失败','OCR已完成','已审核','待审核','OCR排队中','AI排队中','OCR处理中','AI处理中']
    with db.connect() as con:
        ids=[con.execute('INSERT INTO reports(filename,file_path,status,created_at) VALUES(?,?,?,?)',
                         ('sample.png','sample.png',state,db.now_iso())).lastrowid for state in states]
    with TestClient(main.app) as client:
        response=client.post('/process-pending',follow_redirects=False)
        assert response.status_code==303
        assert calls==[(rid,'ocr',ready) for rid in ids[:3]]
        page=BeautifulSoup(client.get('/').text,'html.parser')
        assert page.select_one('form[action="/process-pending"] button').text=='全部运行'
        assert not page.select('form[action="/ocr-pending"], form[action="/llm-pending"]')
        assert page.select_one('header a[href="/export/csv"]').text=='导出'
        assert not page.select('a[href="/export/xlsx"]')
        assert not page.select('a[href*="reviewed_only"]')
        menu=page.select_one('header details.toolbar-menu')
        assert menu and not menu.has_attr('open')
        assert menu.select_one('form[action="/transfer/import-ocr"]')


@pytest.mark.parametrize('models,expected', [([{'name':'qwen3:8b'}],True),([],False),([{'name':'other:8b'}],False)])
def test_batch_ollama_check_requires_configured_model(monkeypatch,models,expected):
    from clinical_extractor import main
    import requests
    monkeypatch.setattr(main,'load_settings',lambda:SimpleNamespace(mock_mode=False,ollama_url='http://localhost:11434',ollama_model='qwen3:8b'))
    monkeypatch.setattr(requests,'get',lambda *args,**kwargs:SimpleNamespace(raise_for_status=lambda:None,json=lambda:{'models':models}))
    assert main.ollama_available() is expected
