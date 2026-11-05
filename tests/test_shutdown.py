import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request


def test_explicit_json_quit_format(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from clinical_extractor import db, main
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'quit.sqlite3')
    callbacks = []
    monkeypatch.setattr(main, '_exit_after_response', lambda: callbacks.append('exit'))
    with TestClient(main.app) as client:
        response = client.post('/quit?format=json', headers={'Accept':'text/html'})
    assert response.json() == {'status':'shutting_down'}
    assert response.headers['content-type'].startswith('application/json')
    assert callbacks == ['exit']


def test_shutdown_acknowledges_then_stops_service(tmp_path):
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    env = {**os.environ, 'CLINICAL_EXTRACTOR_PORT': str(port),
           'CLINICAL_EXTRACTOR_DATA': str(tmp_path / 'data')}
    process = subprocess.Popen([sys.executable, '-m', 'clinical_extractor.main'],
                               cwd=Path(__file__).resolve().parents[1], env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        url = f'http://127.0.0.1:{port}'
        for _ in range(100):
            if process.poll() is not None:
                raise AssertionError('Test service exited before startup')
            try:
                with urllib.request.urlopen(url+'/health', timeout=.2) as response:
                    assert response.status == 200
                break
            except OSError:
                time.sleep(.1)
        request = urllib.request.Request(url+'/quit', method='POST', headers={'Accept':'application/json'})
        with urllib.request.urlopen(request, timeout=5) as response:
            assert json.load(response) == {'status':'shutting_down'}
        assert process.wait(timeout=10) == 0
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
