from pathlib import Path
import importlib.util
import plistlib

import pytest
from clinical_extractor import macos_entry


def test_macos_home_is_outside_app_bundle(tmp_path, monkeypatch):
    monkeypatch.delenv('CLINICAL_EXTRACTOR_MAC_HOME', raising=False)
    monkeypatch.setattr(Path, 'home', lambda:tmp_path)
    assert macos_entry.application_home() == tmp_path/'Library/Application Support/ClinicalExtractor'


def test_macos_models_use_writable_cache_and_recover_incomplete_copy(tmp_path, monkeypatch):
    resources = tmp_path/'signed-app-resources'
    model = resources/'models/paddlex-cache/official_models/PP-OCRv5_server_rec'
    model.mkdir(parents=True)
    for name in ('inference.pdiparams','inference.json','inference.yml'):
        (model/name).write_bytes(b'bundled-model-content')
    monkeypatch.setattr(macos_entry.sys, '_MEIPASS', str(resources), raising=False)
    monkeypatch.setattr(macos_entry.sys, 'frozen', True, raising=False)
    monkeypatch.setenv('CLINICAL_EXTRACTOR_MAC_HOME', str(tmp_path/'user-home'))
    for key in ('CLINICAL_EXTRACTOR_DATA','PADDLE_PDX_CACHE_HOME','PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK',
                'PADDLE_PDX_MODEL_SOURCE','FLAGS_use_mkldnn'):
        monkeypatch.setenv(key,'test-placeholder')
    home, logs = macos_entry.configure_environment()
    destination = home/'models/paddlex-cache/official_models/PP-OCRv5_server_rec'
    assert (destination/'inference.json').read_bytes() == b'bundled-model-content'
    assert logs == home/'logs'
    (destination/'inference.pdiparams').write_bytes(b'partial')
    macos_entry.configure_environment()
    assert (destination/'inference.pdiparams').read_bytes() == b'bundled-model-content'
    assert macos_entry.os.environ['CLINICAL_EXTRACTOR_DATA'] == str(home/'data')
    assert not (resources/'data').exists()


def test_browser_opens_once_after_service_becomes_ready(monkeypatch):
    answers = iter((False,False,True))
    opened = []
    monkeypatch.setattr(macos_entry,'healthy',lambda port:next(answers))
    monkeypatch.setattr(macos_entry.time,'sleep',lambda seconds:None)
    monkeypatch.setattr(macos_entry.webbrowser,'open',lambda url,**kwargs:opened.append(url))
    assert macos_entry.open_when_ready(18999)
    assert opened == ['http://127.0.0.1:18999/']


def test_macos_icon_and_entitlements_use_existing_brand(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location('mac_icon',root/'scripts/make-macos-icon.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    commands=[]
    monkeypatch.setattr(module.subprocess,'run',lambda command,**kwargs:commands.append(command))
    module.make_icon(root/'static/clinical-extractor.ico',tmp_path/'app.icns')
    assert len(list((tmp_path/'ClinicalExtractor.iconset').glob('*.png'))) == 10
    assert commands[0][0] == '/usr/bin/iconutil'
    assert plistlib.loads((root/'scripts/macos-entitlements.plist').read_bytes())['com.apple.security.cs.allow-jit']
