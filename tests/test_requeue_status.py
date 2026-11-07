from clinical_extractor import config
from threading import Event
import time

import pytest
from fastapi.testclient import TestClient


@pytest.mark.parametrize('stage', ['ocr', 'llm'])
def test_completed_report_requeues_and_status_is_polled(tmp_path, monkeypatch, stage):
    from clinical_extractor import db, jobs, service, main
    monkeypatch.setattr(config, 'DB_PATH', tmp_path / 'reports.sqlite3')
    db.init_db()
    with db.connect() as con:
        ids = [con.execute('''INSERT INTO reports(filename,file_path,status,raw_text,created_at)
                              VALUES(?,?,?,?,?)''',
                           (f'{i}.png', f'{i}.png', '已审核', 'saved OCR', db.now_iso())).lastrowid
               for i in range(2)]
        con.execute('INSERT INTO extractions(report_id,value,reviewed) VALUES(?,?,?)', (ids[1], '5.1', 1))
    entered, release, target_entered, target_release = Event(), Event(), Event(), Event()
    calls = []

    def work(rid, requested_stage):
        assert requested_stage == stage
        if rid == ids[0]:
            entered.set()
            release.wait(5)
        else:
            calls.append(rid)
            with db.connect() as con:
                con.execute('UPDATE reports SET status=? WHERE id=?',
                            ('OCR处理中' if stage == 'ocr' else 'AI处理中', rid))
            target_entered.set()
            target_release.wait(5)
            with db.connect() as con:
                con.execute("UPDATE reports SET status='待审核' WHERE id=?", (rid,))
        return 1

    def wait_done():
        for _ in range(300):
            if all(not jobs.is_busy(rid) for rid in ids):
                return
            time.sleep(.01)
        raise AssertionError('Queue did not finish')

    monkeypatch.setattr(service, 'process_report', work)
    try:
        with TestClient(main.app) as client:
            jobs.start_job(ids[0], stage)
            assert entered.wait(2)
            url = f'/report/{ids[1]}/{stage}'
            response = client.post(url, headers={'Accept': 'application/json'})
            assert response.status_code == 202 and response.json()['accepted']
            queued = next(j for j in client.get('/jobs').json()['jobs']
                          if j['report_id'] == ids[1] and j['stage'] == stage)
            assert queued['state'] == 'queued'
            assert queued['report_status'] == ('OCR排队中' if stage == 'ocr' else 'AI排队中')
            with db.connect() as con:
                assert con.execute('SELECT value,reviewed FROM extractions WHERE report_id=?', (ids[1],)).fetchone()['reviewed'] == 1
            client.post(url, headers={'Accept': 'application/json'})
            release.set()
            assert target_entered.wait(2)
            running = next(j for j in client.get('/jobs').json()['jobs']
                           if j['report_id'] == ids[1] and j['stage'] == stage)
            assert running['report_status'] == ('OCR处理中' if stage == 'ocr' else 'AI处理中')
            target_release.set()
            wait_done()
            assert len(calls) == 1
            assert client.post(url, headers={'Accept': 'application/json'}).status_code == 202
            wait_done()
            assert len(calls) == 2
            final = next(j for j in client.get('/jobs').json()['jobs']
                         if j['report_id'] == ids[1] and j['stage'] == stage)
            assert final['state'] == 'completed' and final['report_status'] == '待审核'
    finally:
        release.set()
        target_release.set()
        wait_done()
