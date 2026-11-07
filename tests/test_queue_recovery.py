from clinical_extractor import config
def test_restart_restores_pending_stages_once_and_preserves_completed_results(tmp_path,monkeypatch):
    from clinical_extractor import db,jobs
    monkeypatch.setattr(config, 'DB_PATH',tmp_path/'reports.sqlite3')
    db.init_db()
    states=['OCR排队中','OCR处理中','AI排队中','AI处理中','已审核']
    with db.connect() as con:
        ids=[con.execute('INSERT INTO reports(filename,file_path,status,created_at) VALUES(?,?,?,?)',
                         (f'{i}.png',f'{i}.png',state,db.now_iso())).lastrowid for i,state in enumerate(states)]
        con.execute('INSERT INTO extractions(report_id,value,reviewed) VALUES(?,?,?)',(ids[-1],'5.1',1))
    active=set()
    calls=[]
    def start(report_id,stage):
        active.add(report_id)
        calls.append((report_id,stage))
    monkeypatch.setattr(jobs,'start_job',start)
    monkeypatch.setattr(jobs,'is_busy',lambda report_id:report_id in active)
    jobs.resume_pending_jobs()
    jobs.resume_pending_jobs()
    assert calls==[(ids[0],'ocr'),(ids[1],'ocr'),(ids[2],'llm'),(ids[3],'llm')]
    with db.connect() as con:
        assert con.execute('SELECT status FROM reports WHERE id=?',(ids[-1],)).fetchone()[0]=='已审核'
        assert tuple(con.execute('SELECT value,reviewed FROM extractions WHERE report_id=?',(ids[-1],)).fetchone())==('5.1',1)
