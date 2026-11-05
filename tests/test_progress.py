import json
import time
from types import SimpleNamespace
from threading import Event


def test_streaming_ollama_retains_content_and_actual_token_stats():
    from clinical_extractor.text_extractor import _progress_model
    from clinical_extractor.config import Settings
    events = []
    chunks = [dict(response='hello ', done=False), dict(response='world', done=False),
              dict(response='', done=True, eval_count=20, eval_duration=2_000_000_000)]
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def raise_for_status(self): pass
        def iter_lines(self): return (json.dumps(c).encode() for c in chunks)
    def post(url, **kwargs):
        assert kwargs['stream'] and kwargs['json']['stream']
        assert 'context' not in kwargs['json'] and 'history' not in kwargs['json']
        return Response()
    model = _progress_model(Settings()).set_progress(lambda message, **metrics: events.append((message, metrics)))
    model._requests = SimpleNamespace(post=post)
    result = model._post_ollama_json('http://localhost/api/generate', {'context':[1,2],'history':['old report']}, 60, None, 'test')
    assert result['response'] == 'hello world'
    assert events[-1][1]['tokens_per_second'] == 10
    assert events[-1][1]['tokens'] == 20


def test_job_queue_returns_immediately_and_blocks_duplicate(monkeypatch):
    from clinical_extractor import jobs, service
    entered, release = Event(), Event()
    calls = []
    def work(report_id, stage):
        calls.append(report_id)
        jobs.emit('正在识别第1页')
        entered.set()
        release.wait(3)
        return 2
    monkeypatch.setattr(service, 'process_report', work)
    report_id = 999999
    jobs.start_job(report_id, 'ocr')
    try:
        assert entered.wait(2)
        jobs.start_job(report_id, 'ocr')
        job = next(j for j in jobs.snapshots() if j['report_id'] == report_id)
        assert job['state'] == 'running'
        assert job['message'] == '正在识别第1页'
        assert calls == [report_id]
    finally:
        release.set()
    for _ in range(100):
        if not jobs.is_busy(report_id): break
        time.sleep(.01)
    assert not jobs.is_busy(report_id)


def test_report_ui_shows_patient_type_buttons_and_progress(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from clinical_extractor import main, db
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'reports.sqlite3')
    db.init_db()
    with db.connect() as con:
        rid = con.execute('''INSERT INTO reports(patient_id,profile,filename,file_path,created_at,template_id,status)
                             VALUES(?,?,?,?,?,?,?)''',
                          ('patient-test', '表格式报告', 'sample.png', 'sample.png', db.now_iso(), 'cbc', '已审核')).lastrowid
    with TestClient(main.app) as client:
        html = client.get(f'/report/{rid}').text
        assert 'patient-test · sample.png' in html
        assert 'patient-test · 表格式报告' not in html
        assert '报告 #' not in html
        assert 'name="report_date"' not in html
        assert f'/report/{rid}/ocr' in html and f'/report/{rid}/llm' in html
        assert 'processing-progress' in html
        home = client.get('/').text
        assert '<th>ID</th>' not in home
        assert '<th>日期</th>' not in home
        assert client.get('/jobs').status_code == 200
