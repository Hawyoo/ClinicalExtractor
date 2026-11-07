"""Project folders and an atomic registry; models/settings stay shared."""
from __future__ import annotations

import json
import shutil
import sqlite3
import uuid
from pathlib import Path


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class ProjectManager:
    def __init__(self, data_root: Path):
        self.root = Path(data_root).resolve()
        self.registry = self.root / 'projects.json'
        self.state = {'active_id': '', 'projects': []}

    def initialize(self):
        if self.registry.exists():
            self.state = json.loads(self.registry.read_text(encoding='utf-8'))
        self.refresh()
        if not self.registry.exists():
            self._save()

    def refresh(self):
        missing = [p for p in self.state['projects'] if not self._available(p)]
        valid_ids = {p['id'] for p in self.state['projects'] if p not in missing}
        invalid_active = bool(self.state['active_id'] and self.state['active_id'] not in valid_ids)
        if not missing and not invalid_active:
            return False
        self.state.setdefault('missing_projects', []).extend(missing)
        missing_ids = {p['id'] for p in missing}
        self.state['projects'] = [p for p in self.state['projects'] if p['id'] not in missing_ids]
        if invalid_active:
            self.state['active_id'] = ''
        self._save()
        return True

    @staticmethod
    def _available(entry):
        path = Path(entry['path'])
        return (path / 'project.json').is_file() and (path / 'clinical_extractor.sqlite3').is_file()

    def legacy_available(self):
        return (self.root / 'clinical_extractor.sqlite3').is_file() and not (self.root / 'project-migration.json').exists()

    def _save(self):
        _write_json(self.registry, self.state)

    def active(self):
        entry = next((p for p in self.state['projects'] if p['id'] == self.state['active_id']), None)
        return dict(entry) if entry and self._available(entry) else None

    def create(self, name, import_legacy=False):
        name = str(name).strip()
        if not name or len(name) > 80:
            raise ValueError('请填写 1–80 个字符的项目名称')
        project_id = uuid.uuid4().hex
        path = self.root / 'projects' / project_id
        path.mkdir(parents=True)
        if import_legacy:
            if not self.legacy_available():
                raise ValueError('没有可导入的旧版数据')
            with sqlite3.connect(self.root / 'clinical_extractor.sqlite3') as source, sqlite3.connect(path / 'clinical_extractor.sqlite3') as target:
                source.backup(target)
            for folder in ('uploads', 'exports', 'transfer-staging'):
                source = self.root / folder
                if source.is_dir():
                    shutil.copytree(source, path / folder, dirs_exist_ok=True)
        entry = {'id':project_id, 'name':name, 'path':str(path)}
        _write_json(path / 'project.json', {'format':'clinical-extractor-project', 'version':1, **entry})
        self.state['projects'].append(entry)
        self._save()
        return entry

    def finish_legacy_import(self, entry):
        _write_json(self.root / 'project-migration.json', {
            'original_database':str(self.root / 'clinical_extractor.sqlite3'),
            'project_folder':entry['path'], 'note':'由用户选择导入；旧文件保留为备份。'})

    def delete(self, project_id):
        entry = next((p for p in self.state['projects'] if p['id'] == project_id), None)
        if entry is None:
            raise ValueError('项目不存在')
        path = Path(entry['path']).resolve()
        if path.exists():
            metadata = json.loads((path / 'project.json').read_text(encoding='utf-8'))
            archive = self.root.parent / 'DELETE' / ('project-' + uuid.uuid4().hex)
            if (metadata.get('id') != project_id or path == self.root or path in self.root.parents
                    or archive.resolve().is_relative_to(path) or Path(entry['path']).is_symlink()
                    or Path(entry['path']).is_junction()):
                raise ValueError('项目文件夹位置或标识异常，未删除任何文件')
            archive.mkdir(parents=True)
            _write_json(archive / 'manifest.json', {'action':'delete-project', 'project':entry,
                                                  'restore':'将 project 文件夹移回原位置，再打开已有项目。'})
            shutil.move(str(path), str(archive / 'project'))
        self.state['projects'] = [p for p in self.state['projects'] if p['id'] != project_id]
        if self.state['active_id'] == project_id:
            self.state['active_id'] = ''
        self._save()

    def open(self, folder):
        path = Path(str(folder).strip().strip('"')).expanduser().resolve()
        if path.name == 'project.json':
            path = path.parent
        metadata = json.loads((path / 'project.json').read_text(encoding='utf-8'))
        if metadata.get('format') != 'clinical-extractor-project' or metadata.get('version') != 1:
            raise ValueError('请选择包含 project.json 的 ClinicalExtractor 项目文件夹')
        project_id = str(metadata.get('id', ''))
        name = str(metadata.get('name', '')).strip()
        if not project_id or len(project_id) > 80 or not name:
            raise ValueError('项目说明文件不完整')
        database = path / 'clinical_extractor.sqlite3'
        if not database.is_file():
            raise ValueError('项目文件夹缺少数据库')
        with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as con:
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {'reports', 'extractions'} <= tables:
                raise ValueError('项目数据库不完整')
        existing = next((p for p in self.state['projects'] if p['id'] == project_id), None)
        if existing and Path(existing['path']).resolve() != path and Path(existing['path']).exists():
            raise ValueError('此项目已有另一份文件夹，请通过数据包合并，避免打开两个同名副本')
        entry = {'id':project_id, 'name':name, 'path':str(path)}
        self.state['projects'] = [p for p in self.state['projects'] if p['id'] != project_id] + [entry]
        self.state['missing_projects'] = [p for p in self.state.get('missing_projects', []) if p['id'] != project_id]
        self._save()
        return entry

    def select(self, project_id):
        entry = next((p for p in self.state['projects'] if p['id'] == project_id), None)
        if entry is None or not (Path(entry['path']) / 'project.json').is_file():
            raise ValueError('项目不存在或文件夹已移动，请重新打开项目文件夹')
        self.state['active_id'] = project_id
        self._save()
        return dict(entry)
