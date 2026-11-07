"""Shared, durable template edits; report values/reviews are never written here."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import re
import shutil
from threading import RLock
import uuid

import yaml
from . import config

_lock = RLock()


def custom_path():
    return config.DATA_DIR / 'table_templates' / 'custom.yaml'


def _base_text():
    return (config.PROFILE_DIR / 'table_templates' / 'lab_test_template.yaml').read_text(encoding='utf-8')


def revision():
    path = custom_path()
    return hashlib.sha256(_base_text().encode() + b'\0' + (path.read_bytes() if path.exists() else b'')).hexdigest()


def merge_custom(template, source):
    """Keep base updates available and preserve the original section meanings."""
    section = '其他'
    sections = {}
    for line in source.splitlines():
        heading = re.search(r'#\s*=+\s*(.*?)\s*=+\s*$', line)
        if heading:
            section = heading[1].split(' / ', 1)[0].strip()
        code = re.match(r'\s*-\s*\{code:\s*([^,]+),', line)
        if code:
            sections[code[1].strip().strip('\"\x27')] = section
    for item in template['items']:
        item.setdefault('section', sections.get(item['code'], '其他'))
    custom = _read_custom()
    overrides = {item['code']:item for item in (custom or {}).get('items', [])}
    items = []
    for item in template['items']:
        items.append({**item, **overrides.pop(item['code'], {})})
    items.extend(overrides.values())
    template['items'] = items
    return template


def catalog_data():
    from .report_templates import table_templates
    with _lock:
        items = table_templates()['all']['items']
        sections = list(dict.fromkeys([*(item.get('section', '其他') for item in items), *_read_custom().get('sections', [])]))
        return {'items':items, 'sections':sections, 'revision':revision()}


def _lines(value):
    return list(dict.fromkeys(line.strip() for line in str(value or '').splitlines() if line.strip()))


def save_item(*, target_code, display_name, aliases, abbreviation,
              reference_ranges, unit, alternative_units, section, expected_revision):
    from .report_templates import ascii_unit, _range_pair
    from .result_rules import is_header_name
    with _lock:
        if expected_revision != revision():
            raise ValueError('模板已在其他页面更新，请重新打开模板编辑器后再保存')
        data = catalog_data()
        old = next((item for item in data['items'] if item['code'] == target_code), None)
        if target_code and old is None:
            raise ValueError('要修改的指标不存在，请重新选择')
        display_name, abbreviation, section = display_name.strip(), abbreviation.strip(), section.strip()
        if not display_name or len(display_name) > 120 or is_header_name(display_name):
            raise ValueError('请填写真实的项目展示名称，不能使用表头')
        if not section or len(section) > 80:
            raise ValueError('请填写所属分区，最多 80 个字符')
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_%#.+/-]{0,39}', abbreviation):
            raise ValueError('英文缩写须以英文字母开头，只能包含字母、数字及 _ % # . + / -')
        code = old['code'] if old else abbreviation
        if old is None and any(x['code'].casefold() == code.casefold() for x in data['items']):
            raise ValueError('该指标已存在，请选择已有指标修改')
        for item in data['items']:
            if item['code'] != code and abbreviation.casefold() in {
                    item['code'].casefold(), item.get('abbreviation', item['code']).casefold()}:
                raise ValueError('英文缩写已被其他指标使用，请选择已有指标修改或使用其他缩写')
        ranges = _lines(reference_ranges)
        for text in ranges:
            pair = _range_pair(text)
            if pair is None or (isinstance(pair[0], (int,float)) and pair[0] > pair[1]):
                raise ValueError('参考范围格式无效：'+text+'；请每行填写一个范围，如 3.5-9.5、<23 或 >90')
        item = deepcopy(old) if old else {'code':code, 'name':display_name}
        item.update(display_name=display_name, aliases=_lines(aliases), abbreviation=abbreviation,
                    section=section, expected_unit=ascii_unit(unit.strip()),
                    alternative_units=[ascii_unit(x) for x in _lines(alternative_units)],
                    reference_range=ranges[0] if ranges else '', alternative_reference_ranges=ranges[1:])
        if item['expected_unit'] or item['alternative_units']:
            item.pop('unitless', None)
        else:
            item['unitless'] = True
        content = _read_custom()
        content['items'] = [x for x in content['items'] if x['code'] != code] + [item]
        _write_custom(content)
        return {'saved':True, 'item':item, **catalog_data()}


def _read_custom():
    path = custom_path()
    content = yaml.safe_load(path.read_text(encoding='utf-8')) if path.exists() else None
    content = content or {'version':1, 'items':[]}
    for item in content.get('items', []):
        english = item.pop('english_name', '')
        if english:
            item['aliases'] = list(dict.fromkeys([*item.get('aliases', []), english]))
    return content


def _write_custom(content):
    path = custom_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        history = path.parent / 'history'
        history.mkdir(exist_ok=True)
        shutil.copy2(path, history / (uuid.uuid4().hex + '.yaml'))
    temporary = path.with_name('.custom-' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_text(yaml.safe_dump(content, allow_unicode=True, sort_keys=False), encoding='utf-8')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def save_section(section, expected_revision):
    with _lock:
        if expected_revision != revision():
            raise ValueError('模板已在其他页面更新，请重新加载模板后重试')
        section = section.strip()
        if not section or len(section) > 80 or any(ord(c) < 32 for c in section):
            raise ValueError('请填写 1–80 个字符的分类名称')
        if section in catalog_data()['sections']:
            raise ValueError('该分类已存在，请直接从下拉框选择')
        content = _read_custom()
        content['sections'] = [*content.get('sections', []), section]
        _write_custom(content)
        return {'saved':True, 'section':section, **catalog_data()}
