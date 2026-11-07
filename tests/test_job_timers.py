from threading import Event
from types import SimpleNamespace
import time


def test_queue_time_is_excluded_and_total_survives_ocr_ai_handoff(monkeypatch):
    from clinical_extractor import jobs, service
    monkeypatch.setattr(jobs,'_jobs',{})
    monkeypatch.setattr(jobs,'_batch_timer',{'started':None,'ended':None})
    clock=SimpleNamespace(value=100)
    monkeypatch.setattr(jobs,'time',SimpleNamespace(time=lambda:clock.value,strftime=time.strftime))
    ocr_entered, ai_entered, release_ocr, release_ai = Event(), Event(), Event(), Event()
    def work(rid,stage):
        if stage=='ocr':
            ocr_entered.set();release_ocr.wait(4)
        else:
            ai_entered.set();release_ai.wait(4)
        return 1
    monkeypatch.setattr(service,'process_report',work)
    try:
        jobs.start_job(87001,'ocr',then_ai=True)
        assert ocr_entered.wait(2)
        jobs.start_job(87002,'ocr')
        clock.value=110
        queued=next(j for j in jobs.snapshots() if j['report_id']==87002)
        assert queued['state']=='queued' and queued['elapsed']==0
        assert jobs.total_timer()['elapsed']==10
        release_ocr.set()
        assert ai_entered.wait(2)
        clock.value=120
        ai=next(j for j in jobs.snapshots() if j['report_id']==87001 and j['stage']=='llm')
        assert ai['elapsed']==10
        assert jobs.total_timer()['elapsed']==20
        release_ai.set()
        for _ in range(300):
            if not jobs._has_pending_work():
                break
            time.sleep(.01)
        assert not jobs.total_timer()['running']
        clock.value=200
        assert jobs.total_timer()['elapsed']==20
        jobs.start_job(87003,'ocr')
        for _ in range(300):
            if not jobs.is_busy(87003):
                break
            time.sleep(.01)
        assert jobs.total_timer()['elapsed']==0
    finally:
        release_ocr.set();release_ai.set()
        for _ in range(300):
            if not jobs._has_pending_work():
                break
            time.sleep(.01)
