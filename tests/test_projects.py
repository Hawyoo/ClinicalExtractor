import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from clinical_extractor import config, db, jobs, main
from clinical_extractor.projects import ProjectManager


@pytest.fixture
def project_data(tmp_path, monkeypatch):
    data = tmp_path / 'data'
    data.mkdir()
    for name, value in {'DATA_DIR':data, 'PROJECT_DIR':data,
                        'DB_PATH':data/'clinical_extractor.sqlite3',
                        'UPLOAD_DIR':data/'uploads', 'EXPORT_DIR':data/'exports',
                        'PROJECT_MANAGER':None}.items():
        monkeypatch.setattr(config, name, value)
    config.UPLOAD_DIR.mkdir()
    config.EXPORT_DIR.mkdir()
    monkeypatch.setattr(jobs, '_jobs', {})
    monkeypatch.setattr(jobs, '_batch_timer', {'started':None,'ended':None})
    db.init_db()
    (config.UPLOAD_DIR/'original.png').write_bytes(b'report-image')
    with db.connect() as con:
        rid = con.execute('''INSERT INTO reports(patient_id,filename,file_path,status,created_at)
                             VALUES(?,?,?,?,?)''', ('patient-old','original.png',str(config.UPLOAD_DIR/'original.png'),
                                                    '已审核',db.now_iso())).lastrowid
        con.execute('''INSERT INTO extractions(report_id,item_original,item_standard,value,unit,reviewed)
                       VALUES(?,?,?,?,?,?)''', (rid,'红细胞计数','RBC','3.77','10^12/L',1))
    return data


def test_first_launch_waits_for_user_then_imports_legacy_only_when_selected(project_data):
    with TestClient(main.app) as client:
        assert config.PROJECT_MANAGER.active() is None
        assert config.DB_PATH is None
        page = client.get('/').text
        assert '创建或打开项目' in page
        assert not (project_data/'projects/default').exists()
        assert (project_data/'clinical_extractor.sqlite3').exists()
        assert client.post('/upload', files={'files':('x.png',b'x')},follow_redirects=False).status_code == 303
        assert config.PROJECT_MANAGER.active() is None
        client.post('/projects/create', data={'name':'原项目','import_legacy':'true'})
        entry = config.PROJECT_MANAGER.active()
        assert entry['name'] == '原项目'
        assert config.DB_PATH.parent == Path(entry['path'])
        assert (config.UPLOAD_DIR/'original.png').read_bytes() == b'report-image'
        with db.connect() as con:
            assert con.execute('SELECT status FROM reports').fetchone()[0] == '已审核'
            assert con.execute('SELECT value,reviewed FROM extractions').fetchone()[:] == ('3.77',1)
        assert 'id="current-project"' in client.get('/').text


def test_switch_isolates_uploads_csv_jobs_and_rejects_old_tabs(project_data):
    with TestClient(main.app) as client:
        client.post('/projects/create', data={'name':'原项目','import_legacy':'true'})
        default_id = config.PROJECT_MANAGER.active()['id']
        result = client.post('/projects/create', data={'name':'研究 B'}, follow_redirects=False)
        assert result.status_code == 303
        second = config.PROJECT_MANAGER.active()['id']
        assert second != default_id
        restored = ProjectManager(project_data)
        restored.initialize()
        assert restored.active()['id'] == second
        assert 'patient-old' not in client.get('/').text
        export = client.get('/export/csv')
        assert re.search(r'clinical_extractor-\d{8}-\d{6}\.csv',export.headers['content-disposition'])
        assert 'patient-old' not in export.text
        assert client.post('/upload', data={'patient_id':'patient-new'},
                           files={'files':('new.png',b'new-report','image/png')}).status_code == 200
        assert 'patient-new' in client.get('/').text
        old_tab = client.post('/report/1/delete', headers={'X-Clinical-Project':default_id})
        assert old_tab.status_code == 409
        assert 'patient-new' in client.get('/').text
        client.post('/projects/switch', data={'project_id':default_id})
        assert 'patient-old' in client.get('/').text
        assert 'patient-new' not in client.get('/').text
        assert client.get('/report/1/file').content == b'report-image'
        assert 'patient-old' in client.get('/export/csv').text
        assert 'patient-new' not in client.get('/export/csv').text
        assert client.get('/jobs').json()['jobs'] == []
    # A newly constructed manager restores the last selection.
    manager = ProjectManager(project_data)
    manager.initialize()
    assert manager.active()['id'] == default_id
    assert len(manager.state['projects']) == 2


def test_switch_is_blocked_for_queue_and_running_stage(project_data, monkeypatch):
    with TestClient(main.app) as client:
        client.post('/projects/create', data={'name':'原项目','import_legacy':'true'})
        for state in ('queued','running'):
            monkeypatch.setattr(jobs, '_jobs', {(1,'ocr'):{'state':state,'ended':None}})
            response = client.post('/projects/create', data={'name':'blocked'}, follow_redirects=False)
            assert response.status_code == 303
            assert config.PROJECT_MANAGER.active()['name'] == '原项目'
            assert len(config.PROJECT_MANAGER.state['projects']) == 1
            entry = config.PROJECT_MANAGER.active()
            client.post('/projects/delete', data={'project_id':entry['id']}, follow_redirects=False)
            assert config.PROJECT_MANAGER.active()['id'] == entry['id']
            assert Path(entry['path']).exists()
        monkeypatch.setattr(jobs, '_jobs', {})


def test_transfer_from_one_project_appends_to_another(project_data):
    from clinical_extractor import transfer
    with TestClient(main.app) as client:
        client.post('/projects/create', data={'name':'原项目','import_legacy':'true'})
        default_id = config.PROJECT_MANAGER.active()['id']
        packet = project_data/'source.ceocr'
        transfer.create_transfer(packet)
        client.post('/projects/create', data={'name':'target'})
        transfer.import_transfer(packet)
        with db.connect() as con:
            assert con.execute('SELECT COUNT(*) FROM reports').fetchone()[0] == 1
            assert con.execute('SELECT reviewed FROM extractions').fetchone()[0] == 1
        assert (config.UPLOAD_DIR/'original.png').exists() or any(config.UPLOAD_DIR.iterdir())
        transfer.import_transfer(packet)
        with db.connect() as con:
            assert con.execute('SELECT COUNT(*) FROM reports').fetchone()[0] == 1
        client.post('/projects/switch', data={'project_id':default_id})
        with db.connect() as con:
            assert con.execute('SELECT COUNT(*) FROM reports').fetchone()[0] == 1


def test_open_moved_folder_registers_path_on_other_install(project_data, tmp_path):
    import shutil
    with TestClient(main.app) as client:
        client.post('/projects/create', data={'name':'原项目','import_legacy':'true'})
        original = config.PROJECT_MANAGER.active()
        moved = tmp_path/'moved-project'
        shutil.copytree(original['path'], moved)
        # Old absolute file paths must not be needed on another computer.
        with db.connect() as con:
            con.execute("UPDATE reports SET file_path='Z:/unavailable/original.png'")
        other = ProjectManager(tmp_path/'other-install/data')
        other.initialize()
        entry = other.open(moved)
        other.select(entry['id'])
        assert Path(other.active()['path']) == moved


def test_fresh_install_has_no_automatic_default_project(tmp_path):
    manager = ProjectManager(tmp_path/'data')
    manager.initialize()
    assert manager.active() is None
    assert manager.state['projects'] == []
    assert not (tmp_path/'data/projects').exists()


def test_externally_removed_project_disappears_without_recreating_folder(project_data, tmp_path):
    import shutil
    with TestClient(main.app) as client:
        client.post('/projects/create', data={'name':'to-remove'})
        entry = config.PROJECT_MANAGER.active()
        shutil.move(entry['path'], str(tmp_path/'removed-by-user'))
        page = client.get('/').text
        assert '创建或打开项目' in page
        assert 'to-remove' not in page
        assert config.PROJECT_MANAGER.active() is None
        assert config.DB_PATH is None
        assert not Path(entry['path']).exists()
        assert entry['id'] not in [p['id'] for p in config.PROJECT_MANAGER.state['projects']]
        response = client.post('/projects/create', data={'name':'replacement'})
        assert response.status_code == 200
        assert config.PROJECT_MANAGER.active()['name'] == 'replacement'
    manager = ProjectManager(project_data)
    manager.initialize()
    assert manager.active()['name'] == 'replacement'


def test_delete_project_archives_data_and_does_not_switch_to_other_project(project_data):
    with TestClient(main.app) as client:
        client.post('/projects/create', data={'name':'reviewed-data','import_legacy':'true'})
        deleted = config.PROJECT_MANAGER.active()
        client.post('/projects/create', data={'name':'other'})
        other = config.PROJECT_MANAGER.active()
        client.post('/projects/switch',data={'project_id':deleted['id']})
        page = client.get('/').text
        assert '确认删除项目' in page
        response = client.post('/projects/delete', data={'project_id':deleted['id']})
        assert response.status_code == 200
        assert '创建或打开项目' in response.text
        assert config.PROJECT_MANAGER.active() is None
        assert Path(other['path']).exists()
        assert not Path(deleted['path']).exists()
        archived = list((project_data.parent/'DELETE').glob('project-*/project'))
        assert len(archived) == 1
        import sqlite3
        with sqlite3.connect(archived[0]/'clinical_extractor.sqlite3') as con:
            assert con.execute('SELECT value,reviewed FROM extractions').fetchone() == ('3.77',1)
        client.post('/projects/open', data={'folder':str(archived[0])})
        assert config.PROJECT_MANAGER.active()['id'] == deleted['id']


def test_restart_with_missing_active_folder_shows_project_setup(project_data, tmp_path):
    import shutil
    with TestClient(main.app) as client:
        client.post('/projects/create', data={'name':'missing-on-restart'})
        entry = config.PROJECT_MANAGER.active()
    shutil.move(entry['path'], str(tmp_path/'detached-project'))
    with TestClient(main.app) as client:
        assert '创建或打开项目' in client.get('/').text
        assert config.PROJECT_MANAGER.active() is None
        assert not Path(entry['path']).exists()
