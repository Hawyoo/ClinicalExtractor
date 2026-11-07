from clinical_extractor import config
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient


@pytest.mark.parametrize('stage', ['ocr', 'llm'])
def test_queued_report_deletion_cancels_both_lanes_and_running_is_blocked(tmp_path, monkeypatch, stage):
    from clinical_extractor import db, jobs, main, service
    monkeypatch.setattr(config, 'DB_PATH', tmp_path / 'reports.sqlite3')
    monkeypatch.setattr(config, 'UPLOAD_DIR', tmp_path)
    monkeypatch.setattr(jobs, '_jobs', {})
    executors = {name:ThreadPoolExecutor(max_workers=1) for name in ('ocr','llm')}
    monkeypatch.setattr(jobs, '_executors', executors)
    db.init_db()
    with db.connect() as con:
        ids = [con.execute('INSERT INTO reports(filename,file_path,created_at) VALUES(?,?,?)',
                           (f'{i}.png',f'{i}.png',db.now_iso())).lastrowid for i in range(2)]
        con.execute('INSERT INTO extractions(report_id,value) VALUES(?,?)', (ids[1], '5.1'))
    (tmp_path / '1.png').write_bytes(b'test image')
    entered, release = Event(), Event()
    calls = []
    def process(rid, requested_stage):
        calls.append((rid,requested_stage))
        entered.set()
        release.wait(5)
        return 1
    monkeypatch.setattr(service, 'process_report', process)
    try:
        with TestClient(main.app) as client:
            jobs.start_job(ids[0], stage)
            assert entered.wait(2)
            jobs.start_job(ids[1], stage, then_ai=True)
            jobs.start_job(ids[1], 'llm' if stage=='ocr' else 'ocr')
            states={r['id']:r for r in client.get('/jobs').json()['report_states']}
            assert states[ids[0]]['running'] and not states[ids[1]]['running']
            blocked=client.post(f'/report/{ids[0]}/delete', headers={'Accept':'application/json'})
            assert blocked.status_code==409 and blocked.json()['running']
            assert not blocked.history
            response=client.post(f'/report/{ids[1]}/delete', headers={'Accept':'application/json'})
            assert response.status_code==200 and response.json()['deleted']
            assert not response.history
            assert not (tmp_path / '1.png').exists()
            assert all(j['report_id']!=ids[1] for j in jobs.snapshots())
            with db.connect() as con:
                assert con.execute('SELECT COUNT(*) FROM reports WHERE id=?',(ids[1],)).fetchone()[0]==0
                assert con.execute('SELECT COUNT(*) FROM extractions').fetchone()[0]==0
                assert con.execute('SELECT COUNT(*) FROM reports WHERE id=?',(ids[0],)).fetchone()[0]==1
            page=BeautifulSoup(client.get('/').text,'html.parser')
            form=page.select_one('[data-delete-report]')
            assert form and not form.has_attr('onsubmit')
    finally:
        release.set()
        for executor in executors.values():
            executor.shutdown(wait=True)
    assert calls==[(ids[0],stage)]
