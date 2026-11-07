"""macOS .app entry: writable user data, one service, default browser."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser


def application_home():
    override = os.environ.get('CLINICAL_EXTRACTOR_MAC_HOME')
    return Path(override).expanduser() if override else Path.home() / 'Library' / 'Application Support' / 'ClinicalExtractor'


def configure_environment():
    home = application_home()
    data, logs = home / 'data', home / 'logs'
    for path in (home, data, logs):
        path.mkdir(parents=True, exist_ok=True)
    os.environ['CLINICAL_EXTRACTOR_DATA'] = str(data)
    cache = home / 'models' / 'paddlex-cache'
    os.environ['PADDLE_PDX_CACHE_HOME'] = str(cache)
    os.environ.setdefault('PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK', 'True')
    os.environ.setdefault('PADDLE_PDX_MODEL_SOURCE', 'BOS')
    os.environ.setdefault('FLAGS_use_mkldnn', '0')
    resources = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent))
    bundled = resources / 'models' / 'paddlex-cache' / 'official_models'
    if bundled.is_dir():
        # The signed application and mounted DMG stay immutable. PaddleX can
        # create its runtime files in the user's independent cache directory.
        for model in bundled.iterdir():
            if model.is_dir():
                destination = cache / 'official_models' / model.name
                complete = all((destination / name).is_file() and
                               (destination / name).stat().st_size == (model / name).stat().st_size
                               for name in ('inference.pdiparams', 'inference.json', 'inference.yml'))
                if not complete:
                    shutil.copytree(model, destination, dirs_exist_ok=True)
    elif getattr(sys, 'frozen', False):
        raise RuntimeError('应用内缺少离线 OCR 模型，请重新构建完整 DMG')
    return home, logs


def healthy(port):
    try:
        if not 1 <= int(port) <= 65535:
            return False
        with urllib.request.urlopen(f'http://127.0.0.1:{int(port)}/health', timeout=1) as response:
            return bool(json.load(response).get('ok'))
    except (OSError, ValueError, TypeError):
        return False


def open_when_ready(port, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if healthy(port):
            webbrowser.open(f'http://127.0.0.1:{port}/', new=2)
            return True
        time.sleep(.3)
    return False


def find_port():
    with socket.socket() as stream:
        try:
            stream.bind(('127.0.0.1', 8765))
        except OSError:
            stream.bind(('127.0.0.1', 0))
        return stream.getsockname()[1]


def show_error(message):
    # Pass text as an argument, never interpolate it into AppleScript code.
    script = ('on run argv\n display alert "ClinicalExtractor 启动失败" '
              'message (item 1 of argv) as critical\nend run')
    subprocess.run(['/usr/bin/osascript', '-e', script, message], check=False)


def main():
    home, logs = configure_environment()
    stream = (logs / 'launcher.log').open('a', encoding='utf-8', buffering=1)
    sys.stdout = sys.stderr = stream
    if '--self-check' in sys.argv:
        import paddle
        from clinical_extractor.parser import ReportParser
        paddle.utils.run_check()
        ReportParser()._get_pipeline(table_mode=True).prepare_fallback_model()
        print('Frozen macOS OCR/import self-check passed.')
        return 0
    import fcntl
    lock = (home / 'instance.lock').open('a+')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        # Reopening the app reuses the running service, never starts a second
        # copy or recursively launches another executable/browser.
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            try:
                port = json.loads((home / 'instance.json').read_text(encoding='utf-8'))['port']
                if healthy(port):
                    webbrowser.open(f'http://127.0.0.1:{port}/', new=2)
                    return 0
            except (OSError, ValueError, KeyError):
                pass
            time.sleep(.3)
        raise RuntimeError('已有实例尚未就绪，请查看用户数据目录中的 logs/launcher.log')
    try:
        from clinical_extractor.main import app
        import uvicorn
        port = find_port()
        temporary = home / 'instance.tmp'
        temporary.write_text(json.dumps({'pid':os.getpid(), 'port':port}), encoding='utf-8')
        temporary.replace(home / 'instance.json')
        threading.Thread(target=open_when_ready, args=(port,), daemon=True).start()
        uvicorn.run(app, host='127.0.0.1', port=port, log_level='info')
        return 0
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()


if __name__ == '__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    try:
        raise SystemExit(main())
    except Exception as exc:
        import traceback
        traceback.print_exc()
        show_error(str(exc) + '\n日志：' + str(application_home() / 'logs' / 'launcher.log'))
        raise SystemExit(1)
