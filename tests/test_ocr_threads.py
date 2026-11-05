import sys
from types import SimpleNamespace


def test_auto_and_manual_threads_respect_available_cpu(monkeypatch):
    from clinical_extractor import config
    monkeypatch.setattr(config,'AUTO_OCR_THREADS',6)
    monkeypatch.setattr(config.os,'cpu_count',lambda:12)
    assert config.ocr_thread_count(0)==6
    assert config.ocr_thread_count(11)==11
    assert config.ocr_thread_count(100)==12
    monkeypatch.setattr(config.os,'cpu_count',lambda:1)
    assert config.ocr_thread_count(0)==config.ocr_thread_count(11)==1


def test_next_task_reloads_pipeline_when_thread_setting_changes(monkeypatch):
    from clinical_extractor import config,parser
    settings=config.Settings(ocr_cpu_threads=4)
    calls=[]
    monkeypatch.setattr(parser,'load_settings',lambda:settings)
    monkeypatch.setattr(config.os,'cpu_count',lambda:12)
    monkeypatch.setitem(sys.modules,'paddle',SimpleNamespace(set_flags=lambda flags:None))
    def create_pipeline(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace()
    monkeypatch.setitem(sys.modules,'paddlex',SimpleNamespace(create_pipeline=create_pipeline))
    instance=parser.PPStructureParser()
    first=instance._get_pipeline(True)
    assert instance._get_pipeline(True) is first
    assert len(calls)==1
    first.prepare_fallback_model()
    assert len(calls)==2
    settings.ocr_cpu_threads=11
    second=instance._get_pipeline(True)
    assert second is not first
    assert len(calls)==3
    second.prepare_fallback_model()
    assert len(calls)==4
    assert calls[-1]['engine_config']['paddle_static']=={'run_mode':'paddle','cpu_threads':11}


def test_settings_allow_n_minus_one_threads_and_reject_negative_counts(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from clinical_extractor import config,db,main
    monkeypatch.setattr(config,'SETTINGS_PATH',tmp_path/'settings.json')
    monkeypatch.setattr(db,'DB_PATH',tmp_path/'reports.sqlite3')
    with TestClient(main.app) as client:
        values=dict(ollama_url='http://localhost:11434',ollama_model='qwen3:8b',ocr_cpu_threads='11')
        assert client.post('/settings',data=values,follow_redirects=False).status_code==303
        assert config.load_settings().ocr_cpu_threads==11
        values['ocr_cpu_threads']='-1'
        assert client.post('/settings',data=values,follow_redirects=False).status_code==422
        assert config.load_settings().ocr_cpu_threads==11
