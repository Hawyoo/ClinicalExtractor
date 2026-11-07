from threading import Event
import time
from clinical_extractor import jobs, service


def wait_done(*ids):
    for _ in range(300):
        if all(not jobs.is_busy(rid) for rid in ids):
            return
        time.sleep(.01)
    raise AssertionError('Workers did not complete')


def test_ocr_and_ai_overlap_but_each_lane_is_serial(monkeypatch):
    ocr_running, ai_running = Event(), Event()
    release_ocr, release_ai = Event(), Event()
    next_ocr, next_ai = Event(), Event()
    def work(rid, stage):
        if rid == 81001:
            ocr_running.set(); release_ocr.wait(4)
        elif rid == 81002:
            ai_running.set(); release_ai.wait(4)
        elif rid == 81003:
            next_ocr.set()
        elif rid == 81004:
            next_ai.set()
        return 1
    monkeypatch.setattr(service, 'process_report', work)
    jobs.start_job(81001,'ocr'); jobs.start_job(81002,'llm')
    try:
        assert ocr_running.wait(2) and ai_running.wait(2)
        jobs.start_job(81003,'ocr'); jobs.start_job(81004,'llm')
        assert not next_ocr.is_set() and not next_ai.is_set()
        release_ocr.set()
        assert next_ocr.wait(2)
        assert not next_ai.is_set()
    finally:
        release_ocr.set(); release_ai.set()
        wait_done(81001,81002,81003,81004)


def test_same_report_ai_waits_for_ocr(monkeypatch):
    entered, release, ai_entered = Event(), Event(), Event()
    def work(rid, stage):
        if stage == 'ocr':
            entered.set(); release.wait(4)
        else:
            assert release.is_set()
            ai_entered.set()
        return 1
    monkeypatch.setattr(service, 'process_report', work)
    jobs.start_job(82001,'ocr')
    try:
        assert entered.wait(2)
        jobs.start_job(82001,'llm')
        assert not ai_entered.wait(.1)
        release.set()
        assert ai_entered.wait(2)
    finally:
        release.set(); wait_done(82001)


def test_pipeline_hands_off_while_next_ocr_runs(monkeypatch):
    ai_first, ocr_second, ai_second, release = Event(), Event(), Event(), Event()
    def work(rid, stage):
        if stage == 'llm' and rid == 83001:
            ai_first.set(); release.wait(4)
        elif stage == 'ocr' and rid == 83002:
            assert ai_first.wait(2)
            ocr_second.set()
        elif stage == 'llm' and rid == 83002:
            ai_second.set()
        return 1
    monkeypatch.setattr(service, 'process_report', work)
    jobs.start_job(83001,'ocr',then_ai=True); jobs.start_job(83002,'ocr',then_ai=True)
    try:
        assert ai_first.wait(2) and ocr_second.wait(2)
        assert not ai_second.is_set()
    finally:
        release.set()
        assert ai_second.wait(2)
        wait_done(83001,83002)


def test_failed_ocr_does_not_enter_ai_pipeline(monkeypatch):
    calls = []
    def work(rid, stage):
        calls.append(stage)
        raise RuntimeError('test OCR failed')
    monkeypatch.setattr(service, 'process_report', work)
    jobs.start_job(84001,'ocr',then_ai=True)
    wait_done(84001)
    assert calls == ['ocr']
