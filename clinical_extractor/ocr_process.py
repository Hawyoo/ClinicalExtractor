"""Isolate native Paddle faults from the web server and AI worker."""
import atexit
import faulthandler
import multiprocessing as mp
import os
import json
from pathlib import Path
import threading
import time


def _encode_document(document):
    # PaddleX result dictionaries can retain bound-method/weakref helpers.
    # Transfer only a JSON snapshot, just like the existing database format.
    payload = dict(raw_text=document.raw_text,
                   tables=[dict(page=t.page, html=t.html, rows=t.rows, bbox=t.bbox, row_repairs=t.row_repairs) for t in document.tables],
                   texts=[dict(page=t.page, text=t.text, label=t.label, bbox=t.bbox) for t in document.texts],
                   parser_json=document.parser_json)
    return json.dumps(payload, ensure_ascii=False, default=str)


def _decode_document(payload):
    from .parser import ParsedDocument, TableBlock, TextBlock
    data = json.loads(payload)
    return ParsedDocument(raw_text=data['raw_text'], parser_json=data['parser_json'],
                          tables=[TableBlock(**t) for t in data['tables']],
                          texts=[TextBlock(**t) for t in data['texts']])


def _worker(connection, log_path):
    # Native aborts bypass Python exception handlers. Keep the stack in a file.
    log = open(log_path, 'a', encoding='utf-8', buffering=1)
    import sys
    sys.stdout = log
    sys.stderr = log
    faulthandler.enable(file=log, all_threads=True)
    print(f'\n[{time.strftime("%Y-%m-%d %H:%M:%S")}] OCR worker PID={os.getpid()}')

    def watch_parent():
        parent = mp.parent_process()
        while parent and parent.is_alive():
            time.sleep(1)
        os._exit(0)
    threading.Thread(target=watch_parent, daemon=True).start()
    from .parser import PPStructureParser
    from .jobs import _callback
    parser = PPStructureParser()
    _callback.set(lambda message, **metrics: connection.send(('progress', message, metrics)))
    while True:
        try:
            path = connection.recv()
        except EOFError:
            return
        if path is None:
            return
        try:
            result = parser.parse(path['path'], table_mode=path['table_mode']) if isinstance(path, dict) else parser.parse(path)
            connection.send(('result', _encode_document(result)))
            # Release the previous image's result objects before reading the
            # next command; retain only the reusable model weights.
            del result
        except Exception as exc:
            import traceback
            traceback.print_exc(file=log)
            connection.send(('error', str(exc)))


class IsolatedOCRParser:
    def __init__(self):
        self._process = None
        self._connection = None
        self._lock = threading.RLock()

    def _start(self):
        from .config import DATA_DIR
        logs = DATA_DIR.parent / 'logs'
        logs.mkdir(parents=True, exist_ok=True)
        parent, child = mp.get_context('spawn').Pipe()
        process = mp.get_context('spawn').Process(
            target=_worker, args=(child, str(logs / 'ocr-worker.log')), daemon=True)
        process.start()
        child.close()
        self._process, self._connection = process, parent

    def close(self):
        with self._lock:
            if self._connection:
                self._connection.close()
            if self._process:
                if self._process.is_alive():
                    self._process.terminate()
                self._process.join(timeout=3)
                self._process.close()
            self._process = self._connection = None

    def parse(self, path, table_mode=True):
        from .jobs import emit
        with self._lock:
            if not self._process or not self._process.is_alive():
                self.close()
                self._start()
            try:
                self._connection.send(str(path) if table_mode else {'path': str(path), 'table_mode': False})
                while True:
                    if self._connection.poll(.25):
                        message = self._connection.recv()
                        if message[0] == 'progress':
                            emit(message[1], **message[2])
                        elif message[0] == 'result':
                            return _decode_document(message[1])
                        else:
                            raise RuntimeError(message[1])
                    elif not self._process.is_alive():
                        raise EOFError('OCR process exited')
            except (EOFError, BrokenPipeError, OSError) as exc:
                self._process.join(timeout=1)
                code = self._process.exitcode
                label = f'0x{code & 0xffffffff:08X}' if code is not None else '未知'
                self.close()
                raise RuntimeError(f'OCR 底层进程异常退出（{label}）。网页与 AI 队列仍可使用；'
                                   '下份任务将重启 OCR。详情见 logs/ocr-worker.log。') from exc


OCR_PARSER = IsolatedOCRParser()
atexit.register(OCR_PARSER.close)
