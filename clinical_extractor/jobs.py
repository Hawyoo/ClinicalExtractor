"""Independent serial OCR/AI lanes with per-report write dependencies."""
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from contextlib import contextmanager
from copy import deepcopy
from threading import RLock, Event
import time

_callback = ContextVar('processing_callback', default=None)
_lock = RLock()
_executors = {
    'ocr': ThreadPoolExecutor(max_workers=1, thread_name_prefix='ocr-worker'),
    'llm': ThreadPoolExecutor(max_workers=1, thread_name_prefix='ai-worker'),
}
_jobs = {}
_batch_timer = {'started': None, 'ended': None}


@contextmanager
def project_transition():
    """A project cannot change while either queue can still write data."""
    with _lock:
        if _has_pending_work():
            yield False
            return
        yield True
        _jobs.clear()
        _batch_timer.update(started=None, ended=None)


def _has_pending_work():
    return any(j['state'] in {'queued','running'} or j.get('_handoff_pending')
               or j['ended'] is None for j in _jobs.values())


def _stop_timer_if_idle():
    if _batch_timer['started'] is not None and _batch_timer['ended'] is None and not _has_pending_work():
        _batch_timer['ended'] = time.time()


def total_timer():
    with _lock:
        started, ended = _batch_timer['started'], _batch_timer['ended']
        return dict(elapsed=round(max(0,(ended if ended is not None else time.time())-started),1)
                    if started is not None else 0,
                    started=started is not None, running=started is not None and ended is None)


def emit(message, **metrics):
    callback = _callback.get()
    if callback:
        callback(message, **metrics)


def progress_callback():
    return _callback.get() or (lambda *args, **kwargs: None)


def resume_pending_jobs():
    """Restore interrupted/queued stages instead of leaving database-only queue labels."""
    from .db import connect
    with connect() as con:
        pending = con.execute("""SELECT id,status FROM reports
            WHERE status IN ('OCR排队中','OCR处理中','AI排队中','AI处理中') ORDER BY id""").fetchall()
    for report in pending:
        if not is_busy(report['id']):
            start_job(report['id'], 'llm' if report['status'].startswith('AI') else 'ocr')


def start_job(report_id, stage, then_ai=False):
    if stage not in _executors:
        raise ValueError('未知处理阶段')
    with _lock:
        key = (report_id, stage)
        previous = _jobs.get(key)
        if previous and previous['state'] in {'queued', 'running'}:
            if then_ai:
                previous['then_ai'] = True
            return
        if not _has_pending_work():
            _batch_timer.update(started=None, ended=None)
        dependencies = [j for j in _jobs.values() if j['report_id'] == report_id
                        and j['state'] in {'queued', 'running'}]
        job = dict(report_id=report_id, stage=stage, state='queued', message='等待处理',
                   created=time.time(), started=None, ended=None, logs=[], metrics={},
                   then_ai=then_ai, _done=Event())
        _jobs[key] = job

    # Persist before submitting so even a report waiting behind a long task
    # immediately stops displaying its previous completed/reviewed state.
    from .db import connect
    if not dependencies:
        try:
            with connect() as con:
                con.execute("UPDATE reports SET status=?, error='' WHERE id=?",
                            ('AI排队中' if stage == 'llm' else 'OCR排队中', report_id))
        except Exception:
            with _lock:
                job.update(state='failed', ended=time.time())
                job['_done'].set()
                _stop_timer_if_idle()
            raise

    def update(message, **metrics):
        with _lock:
            job['message'] = message
            job['metrics'].update(metrics)
            if not job['logs'] or job['logs'][-1]['message'] != message:
                job['logs'].append(dict(time=time.strftime('%H:%M:%S'), message=message))
                job['logs'][:] = job['logs'][-80:]

    def work():
        from .service import process_report
        token = _callback.set(update)
        try:
            for dependency in dependencies:
                update('等待同一报告的前一道工序完成')
                dependency['_done'].wait()
                if stage == 'llm' and dependency['stage'] == 'ocr' and dependency['state'] == 'failed':
                    raise RuntimeError('前置 OCR 失败，请修复后重新处理')
            with _lock:
                if job['state'] != 'queued':
                    return
                job.update(state='running', started=time.time())
                if _batch_timer['started'] is None:
                    _batch_timer['started'] = job['started']
            count = process_report(report_id, stage)
            update(f'完成，共保存 {count} 条结果')
            with _lock:
                job['state'] = 'completed'
                job['_handoff_pending'] = stage == 'ocr' and job['then_ai']
        except Exception as exc:
            update(f'处理失败：{exc}')
            with _lock:
                job['state'] = 'failed'
        finally:
            with _lock:
                job['ended'] = time.time()
                job['_done'].set()
                _stop_timer_if_idle()
            _callback.reset(token)
        with _lock:
            if stage == 'ocr' and job['state'] == 'completed' and job['then_ai']:
                try:
                    start_job(report_id, 'llm')
                finally:
                    job['_handoff_pending'] = False
                    _stop_timer_if_idle()

    _executors[stage].submit(work)


def snapshots():
    with _lock:
        output = deepcopy([{k:v for k,v in j.items() if not k.startswith('_')} for j in _jobs.values()])
    for job in output:
        job['elapsed'] = (round(max(0,(job['ended'] if job['ended'] is not None else time.time())-job['started']),1)
                          if job['started'] is not None else 0)
    return output


def is_busy(report_id):
    return any(j['report_id'] == report_id and j['state'] in {'queued', 'running'} for j in snapshots())


@contextmanager
def report_deletion(report_id):
    """Keep deletion atomic with a worker starting or handing off to AI."""
    with _lock:
        owned = [(key, job) for key, job in _jobs.items() if job['report_id'] == report_id]
        if any(job['state'] == 'running' for _, job in owned):
            yield False
            return
        for key, job in owned:
            job['then_ai'] = False
            job['_handoff_pending'] = False
            if job['state'] == 'queued':
                job.update(state='cancelled', ended=time.time())
                job['_done'].set()
            _jobs.pop(key, None)
        _stop_timer_if_idle()
        yield True
