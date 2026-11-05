import os
import pytest


def simulated_native_worker(connection, log_path):
    from clinical_extractor.parser import ParsedDocument
    from clinical_extractor.ocr_process import _encode_document
    while True:
        try:
            path = connection.recv()
        except EOFError:
            return
        if path == 'crash':
            os._exit(17)
        connection.send(('result', _encode_document(ParsedDocument('ok', [], [], []))))


def test_native_exit_is_reported_and_next_ocr_restarts(tmp_path, monkeypatch):
    from clinical_extractor import ocr_process, config
    monkeypatch.setattr(config, 'DATA_DIR', tmp_path / 'data')
    monkeypatch.setattr(ocr_process, '_worker', simulated_native_worker)
    parser = ocr_process.IsolatedOCRParser()
    try:
        assert parser.parse('ok').raw_text == 'ok'
        with pytest.raises(RuntimeError, match='0x00000011'):
            parser.parse('crash')
        assert parser.parse('ok').raw_text == 'ok'
    finally:
        parser.close()
