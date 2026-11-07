from clinical_extractor import config
import json

from bs4 import BeautifulSoup
from fastapi.testclient import TestClient


def test_theme_and_sort_survive_new_port_without_browser_storage(tmp_path,monkeypatch):
    from clinical_extractor import db,main,preferences,config
    monkeypatch.setattr(config, 'DB_PATH',tmp_path/'reports.sqlite3')
    monkeypatch.setattr(preferences,'PREFERENCES_PATH',tmp_path/'ui_preferences.json')
    monkeypatch.setattr(config,'SETTINGS_PATH',tmp_path/'settings.json')
    with TestClient(main.app,base_url='http://127.0.0.1:18101') as client:
        assert client.post('/preferences',data={'theme':'dark'}).json()['theme']=='dark'
        assert client.post('/preferences',data={'report_sort':'added'}).json()=={'theme':'dark','report_sort':'added'}
        assert client.post('/preferences',data={'theme':'invalid'}).status_code==422
        assert preferences.load_preferences()=={'theme':'dark','report_sort':'added'}
        client.post('/settings',data={'ollama_url':'http://localhost:11434','ollama_model':'qwen3:8b','ocr_cpu_threads':'4'})
    with TestClient(main.app,base_url='http://127.0.0.1:28202') as client:
        page=BeautifulSoup(client.get('/').text,'html.parser')
        assert page.html['data-theme']=='dark'
        assert '"report_sort": "added"' in str(page)
        assert 'preferences.js' in str(page)
        assert config.load_settings().ocr_cpu_threads==4
        assert preferences.load_preferences()['theme']=='dark'
    assert json.loads(preferences.PREFERENCES_PATH.read_text(encoding='utf-8'))=={'theme':'dark','report_sort':'added'}


def test_invalid_optional_ui_file_values_do_not_break_pages(tmp_path,monkeypatch):
    from clinical_extractor import preferences
    path=tmp_path/'ui_preferences.json'
    monkeypatch.setattr(preferences,'PREFERENCES_PATH',path)
    path.write_text('{"theme":[],"report_sort":"invalid"}',encoding='utf-8')
    assert preferences.load_preferences()=={'theme':None,'report_sort':None}
    path.write_text('{broken',encoding='utf-8')
    assert preferences.load_preferences()=={'theme':None,'report_sort':None}
