from bs4 import BeautifulSoup
from fastapi.testclient import TestClient


def test_default_order_and_live_states_include_reports_without_jobs(tmp_path,monkeypatch):
    from clinical_extractor import db,main
    monkeypatch.setattr(db,'DB_PATH',tmp_path/'reports.sqlite3')
    db.init_db()
    with db.connect() as con:
        ids=[con.execute('INSERT INTO reports(filename,file_path,created_at) VALUES(?,?,?)',
                         (f'{i}.png',f'{i}.png',db.now_iso())).lastrowid for i in range(3)]
    with TestClient(main.app) as client:
        page=BeautifulSoup(client.get('/').text,'html.parser')
        assert [int(row['data-report-row']) for row in page.select('#report-list-body [data-report-row]')]==ids
        assert page.select_one('#report-sort option')['value']=='status'
        with db.connect() as con:
            con.execute('UPDATE reports SET status=?,error=? WHERE id=?',('失败','识别失败',ids[1]))
            con.execute('INSERT INTO extractions(report_id,value) VALUES(?,?)',(ids[2],'5.1'))
            con.execute('UPDATE reports SET status=? WHERE id=?',('已审核',ids[2]))
        states={r['id']:r for r in client.get('/jobs').json()['report_states']}
        assert states[ids[1]]['status']=='失败' and states[ids[1]]['error']=='识别失败'
        assert states[ids[2]]['status']=='已审核' and states[ids[2]]['n']==1
