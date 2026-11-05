from __future__ import annotations
import re
import json
from copy import deepcopy
from difflib import SequenceMatcher
import yaml
from .config import PROFILE_DIR

ALL_TEMPLATE_ID = 'all'


def merge_templates(templates: dict) -> dict:
    """Combine definitions by analyte code; similar names/ranges never merge codes."""
    merged = {}
    for template in templates.values():
        for definition in template.get('items',[]):
            code = definition['code']
            if code not in merged:
                merged[code] = deepcopy(definition)
                continue
            item = merged[code]
            item['aliases'] = list(dict.fromkeys([*item.get('aliases',[]),
                definition['name'], definition.get('display_name',definition['name']),
                *definition.get('aliases',[])]))
            references = [*item.get('alternative_reference_ranges',[]),
                          definition.get('reference_range',''),*definition.get('alternative_reference_ranges',[])]
            item['alternative_reference_ranges'] = list(dict.fromkeys(r for r in references if r and r!=item.get('reference_range')))
            units = [*item.get('alternative_units',[]),definition.get('expected_unit',''),*definition.get('alternative_units',[])]
            item['alternative_units'] = list(dict.fromkeys(ascii_unit(u) for u in units if u and u!=item.get('expected_unit')))
    return dict(id=ALL_TEMPLATE_ID,name='表格式报告',coverage='partial',
                missing_policy='只匹配当前图片实际出现的指标，不补项目或结果；存在多个候选时保留核对提示',
                items=list(merged.values()))


def table_templates() -> dict:
    templates = {}
    legacy_ids = []
    for path in sorted((PROFILE_DIR / 'table_templates').glob('*.yaml')):
        template = yaml.safe_load(path.read_text(encoding='utf-8'))
        # Keep canonical template units portable even for newly added templates.
        for item in template.get('items', []):
            if item.get('expected_unit'):
                item['expected_unit'] = ascii_unit(item['expected_unit'])
            if item.get('alternative_units'):
                item['alternative_units'] = list(dict.fromkeys(ascii_unit(u) for u in item['alternative_units']))
        templates[template['id']] = template
        legacy_ids.extend(template.get('legacy_ids', []))
    catalog = {**templates, ALL_TEMPLATE_ID:merge_templates(templates)}
    # Old report payloads and transfer packages can still carry these IDs.
    # They resolve to the same unified catalog, never a separate matching scope.
    for legacy_id in legacy_ids:
        if legacy_id not in catalog:
            catalog[legacy_id] = catalog[ALL_TEMPLATE_ID]
    return catalog


def _key(text: str) -> str:
    return re.sub(r'[\s*＊()（）_]+', '', text).casefold()


def ascii_unit(unit: str) -> str:
    return str(unit or '').replace('\u03bc', 'u').replace('\u00b5', 'u')


def template_order(item: dict, template_id: str, catalog=None) -> int:
    template = (catalog if catalog is not None else table_templates()).get(template_id)
    if not template:
        return 0
    name = _key(str(item.get('item_standard') or item.get('item_original') or ''))
    for index, definition in enumerate(template['items']):
        aliases = [definition['code'], definition['name'], definition.get('display_name', ''), *definition.get('aliases', [])]
        if name and any(name == _key(str(alias)) for alias in aliases if alias):
            return index
    return len(template['items'])




def _normalize_unit(record: dict, item: dict, payload: dict) -> None:
    raw = str(record.get('unit') or '')
    payload['unit_ocr_raw'] = raw
    if not raw.strip():
        if item.get('unitless'):
            return
        if item.get('expected_unit'):
            record['unit'] = ascii_unit(item['expected_unit'])
            payload.pop('unit_warning', None)
            payload['unit_correction'] = f"采用已匹配项目的模板单位：{record['unit']}"
            return
        payload['unit_warning'] = '原报告单位未识别，请核对；未从模板补填'
        return
    token = re.sub(r'\s+', '', ascii_unit(raw)).replace('／', '/').casefold()
    expected = item.get('expected_unit', '')
    allowed = [u for u in [expected, *item.get('alternative_units', [])] if u]
    canonical = next((u for u in allowed if u.casefold() == token), None)
    reason = '统一单位书写'
    mol = re.fullmatch(r'([um])[mn]ol/[l1i|]', token)
    if canonical is None and mol and expected.casefold() == mol[1]+'mol/l':
        canonical = expected
        reason = '按已匹配项目校正单位中的 m/n 和 L/1 字形混淆'
    if (canonical is None and expected == 'mL/min/1.73m²'
            and re.fullmatch(r'ml/min/1[.,]73m(?:\^?2|²|["”\x27]2)?', token)):
        canonical = expected
        reason = '补正体表面积单位缺失或误识别的平方标记'
    if canonical is None and item['code'] in {'HGB', 'MCHC'} and token == '9/l':
        canonical = 'g/L'
        reason = '按血红蛋白浓度项目校正 OCR 的 9/g 混淆，请对照图片确认'
    if canonical is None and expected == 'fL' and token in {'f', 'fi', 'f1', 'f|'}:
        canonical = 'fL'
        reason = '按体积项目补正 OCR 缺失或误识别的 L，请对照图片确认'
    if canonical is None and expected == '%' and re.fullmatch(r'[%％][06oO]?', token):
        canonical = '%'
        reason = '按百分比项目校正 OCR 的百分号尾部粘连，请对照图片确认'
    if canonical:
        payload.pop('unit_warning', None)
        record['unit'] = canonical
        if raw != canonical:
            payload['unit_correction'] = f'{raw} → {canonical}（{reason}）'
    else:
        payload['unit_warning'] = f'单位“{raw}”未匹配本项目的已知写法，保留原文，请核对'


def _ambiguous_reference(text):
    return len(re.findall(r'[<>≤≥]=?\s*\d+(?:\.\d+)?|\d+(?:\.\d+)?\s*[-~～—–至]\s*\d+(?:\.\d+)?', str(text))) > 1


def _reference(record: dict):
    payload = record.get('payload_json') or {}
    if isinstance(payload,str):
        try:
            payload = json.loads(payload)
        except (TypeError,ValueError):
            payload = {}
    if not isinstance(payload,dict):
        payload = {}
    if _ambiguous_reference(payload.get('reference_raw', '')):
        return None
    low, high = record.get('reference_low'), record.get('reference_high')
    if low not in (None, '') and high not in (None, ''):
        try:
            return float(low), float(high)
        except (ValueError, TypeError):
            return None
    text = payload.get('reference_raw', '')
    return _range_pair(text)


def _range_pair(text):
    single = re.fullmatch(r'\s*(<=|>=|<|>|≤|≥|＜|＞)\s*(\d+(?:\.\d+)?)\s*', str(text))
    if single:
        operator = {'≤':'<=','≥':'>=','＜':'<','＞':'>'}.get(single[1],single[1])
        return operator, float(single[2])
    match = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*[-~～—–至]\s*(\d+(?:\.\d+)?)\s*', str(text))
    return tuple(map(float, match.groups())) if match else None


def _name_parts(text: str) -> tuple[str, list[str]]:
    """Separate an optional row number and bilingual/method annotations.

    Splitting at an opening bracket also handles a missing closing bracket.
    Digits inside analyte names (C1q, ApoA1, etc.) remain significant.
    """
    text = str(text or '').strip()
    text = re.sub(r'^\d{1,3}\s*[、.．:：]?\s*(?=[\u4e00-\u9fffA-Za-z])', '', text)
    parts = re.split(r'[（(\[【）)\]】]', text)
    base = parts[0].strip()
    annotations = [part.strip() for part in parts[1:] if part.strip()]
    return base, annotations


def _candidate(record, item):
    original_name = _key(record.get('item_original', ''))
    # Template-defined identity terms distinguish methods sharing units/ranges.
    # Neither reference matches nor model hints may bypass these constraints.
    if any(_key(term) not in original_name for term in item.get('required_name_terms', [])):
        return None
    if any(_key(term) in original_name for term in item.get('excluded_name_terms', [])):
        return None
    base, annotations = _name_parts(record.get('item_original', ''))
    name = _key(base)
    aliases = [_key(a) for a in [item['name'], item['code'], *item.get('aliases', [])]]
    aliases.extend(_key(_name_parts(a)[0]) for a in
                   [item['name'], *item.get('aliases', [])])
    exact = bool(name) and name in aliases
    # With a missing opening bracket, retain a complete Chinese alias followed
    # only by an abbreviation. Do not split internal letters/digits in C1q etc.
    bilingual_exact = any(re.search('[\u4e00-\u9fff]$', alias) and name.startswith(alias)
                          and re.fullmatch(r'[a-z][a-z0-9/#%._-]{0,19}', name[len(alias):])
                          for alias in aliases)
    exact = exact or bilingual_exact
    similarity = max(SequenceMatcher(None, name, a).ratio() for a in aliases) if name else 0
    if exact:
        similarity = 1.0
    reference = _reference(record)
    expected_references = [_range_pair(r) for r in
                           [item.get('reference_range', ''), *item.get('alternative_reference_ranges', [])]]
    expected_references = [r for r in expected_references if r is not None]
    range_match = reference is not None and reference in expected_references
    range_conflict = reference is not None and bool(expected_references) and not range_match
    unit = _key(ascii_unit(record.get('unit') or '')).replace('／', '/').replace('％', '%')
    allowed = [_key(u) for u in [item.get('expected_unit', ''), *item.get('alternative_units', [])] if u]
    unit_similarity = max((SequenceMatcher(None, unit, u).ratio() for u in allowed), default=0) if unit else 0
    # These are mutually exclusive meanings, not typo substitutions.
    for discriminator in ['酸', '碱']:
        if discriminator in name and not any(discriminator in a for a in aliases):
            return None
    if ('计数' in name or '绝对值' in name) and item['code'].endswith('%'):
        return None
    if ('百分' in name or '比率' in name) and item['code'].endswith('#'):
        return None
    if range_conflict and not exact:
        return None
    # Multiple independent fixed fields may identify a badly damaged name.
    # A result value is deliberately never inspected here.
    supported = exact or (range_match and unit_similarity >= .60) or (
        similarity >= .70 and len(re.findall('[\u4e00-\u9fff]', name)) >= 4)
    if not supported:
        return None
    score = .65 * similarity + .25 * range_match + .10 * unit_similarity
    if exact:
        score += .35
    # A recognized abbreviation reinforces a damaged name, but cannot replace
    # a contradictory Chinese name or turn a real correction into an exact match.
    if similarity >= .5 and any(_key(part) in aliases for part in annotations):
        score += .10
    if ((record.get('payload_json') or {}).get('ai_template_code') == item['code']
            and (exact or similarity >= .5)):
        score += .20
    return dict(item=item, score=score, name_similarity=round(similarity,3),
                name_exact=exact, reference_match=range_match, reference_conflict=range_conflict,
                unit_similarity=round(unit_similarity,3))


def _align_rows(records, items):
    """Lock reliable anchors, then resolve remaining rows one-to-one.

    Every match still needs its own evidence. Neither the last remaining item
    nor the physical row order is sufficient to assign a result.
    """
    candidates = {i: [c for item in items if (c := _candidate(record, item))]
                  for i, record in enumerate(records)}
    for i, choices in candidates.items():
        ranked = sorted(choices, key=lambda c:c['score'], reverse=True)
        if len(ranked)>1 and ranked[0]['score']-ranked[1]['score'] < .10:
            # Another row claiming one code is not new evidence about this
            # row. Shared units/ranges must not force a leftover candidate.
            candidates[i] = []
    matches, used = {}, set()
    while True:
        proposals = []
        for i, choices in candidates.items():
            if i in matches:
                continue
            ranked = sorted((c for c in choices if c['item']['code'] not in used), key=lambda c:c['score'], reverse=True)
            if not ranked or (len(ranked)>1 and ranked[0]['score']-ranked[1]['score'] < .10):
                continue
            best = ranked[0]
            competitors = [c['score'] for j, cs in candidates.items() if j != i and j not in matches
                           for c in cs if c['item']['code'] == best['item']['code']]
            if competitors and best['score']-max(competitors) < .10:
                continue
            proposals.append((i,best))
        if not proposals:
            break
        for i, best in sorted(proposals, key=lambda p:p[1]['score'], reverse=True):
            if best['item']['code'] not in used:
                matches[i] = best
                used.add(best['item']['code'])
    return matches


def apply_table_template(records: list[dict], template_id: str) -> list[dict]:
    template = table_templates().get(template_id)
    if not template:
        return records
    matches = _align_rows(records, template['items'])
    for index, record in enumerate(records):
        payload = dict(record.get('payload_json') or {})
        if _ambiguous_reference(payload.get('reference_raw', '')):
            payload['reference_warning'] = '参考区间疑似混入相邻行内容，请核对原图；项目和结果未改动'
        payload['template_id'] = template_id
        match = matches.get(index)
        item = match['item'] if match else None
        if item:
            if match['reference_conflict']:
                payload['template_warning'] = '项目名称明确，但报告参考范围与参考模板不同；保留报告原范围，请核对'
            elif payload.get('template_warning') == '项目名称明确，但报告参考范围与参考模板不同；保留报告原范围，请核对':
                payload.pop('template_warning',None)
            payload['template_match'] = {k:v for k,v in match.items() if k != 'item'}
            supports = []
            if match['name_exact']:
                supports.append('名称/缩写明确匹配')
            elif match['name_similarity'] >= .7:
                supports.append('名称相似匹配')
            if match['reference_match']:
                supports.append('参考范围匹配')
            if match['unit_similarity'] >= .6:
                supports.append('单位相容')
            payload['template_alignment'] = '模板行已对应：' + '、'.join(supports)
            payload['item_ocr_original'] = payload.get('item_ocr_original') or record.get('item_original','')
            if not match['name_exact']:
                payload['item_correction'] = f"{record.get('item_original', '')} → {item.get('display_name', item['name'])}（整表模板联合匹配）"
            record['item_standard'] = item['code']
            record['category'] = template['name']
            payload['standard_name'] = item.get('display_name', item['name'])
            # A matched item's missing unit may come from the template.
            # Result values and reference intervals remain report evidence only.
            payload['template_expected_unit'] = item.get('expected_unit', '')
            _normalize_unit(record, item, payload)
            if match['reference_match'] and item.get('expected_unit'):
                payload.pop('unit_warning', None)
                expected = item['expected_unit']
                allowed_units = [expected, *item.get('alternative_units', [])]
                if record.get('unit') not in allowed_units:
                    payload['unit_correction'] = f"{payload['unit_ocr_raw']} → {expected}（项目与参考范围联合确认，采用模板单位）"
                    record['unit'] = expected
        else:
            payload['template_warning'] = '模板外项目，或名称、参考范围与单位未能唯一对齐；保留原报告内容，请核对'
        record['payload_json'] = payload
    return records


def fill_missing_template_unit(record: dict, template_id: str, catalog=None) -> None:
    """Fill or normalize units on already matched/confirmed display/export rows."""
    payload = record.get('payload_json') or {}
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (TypeError, ValueError):
            return
    if not isinstance(payload, dict) or not (payload.get('template_match') or record.get('reviewed')):
        return
    template = (catalog if catalog is not None else table_templates()).get(template_id, {})
    item = next((item for item in template.get('items', [])
                 if item['code'] == record.get('item_standard')), None)
    if item and item.get('expected_unit'):
        payload = dict(payload)
        _normalize_unit(record, item, payload)
        record['payload_json'] = payload


def refresh_reference_warning(record: dict, template_id: str, catalog=None) -> None:
    """Retire obsolete range-only warnings when an existing result matches a new variant."""
    payload = record.get('payload_json') or {}
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (TypeError,ValueError):
            return
    if not isinstance(payload,dict):
        return
    if _ambiguous_reference(payload.get('reference_raw', '')):
        payload = dict(payload)
        if payload.get('template_warning') == '项目名称明确，但报告参考范围与参考模板不同；保留报告原范围，请核对':
            payload.pop('template_warning')
        payload['reference_warning'] = '参考区间疑似混入相邻行内容，请核对原图；项目和结果未改动'
        record['payload_json'] = payload
        return
    if payload.get('template_warning') != '项目名称明确，但报告参考范围与参考模板不同；保留报告原范围，请核对':
        return
    template = (catalog if catalog is not None else table_templates()).get(template_id,{})
    item = next((item for item in template.get('items',[]) if item['code']==record.get('item_standard')),None)
    if item and _reference(record) is not None and _reference(record) in [
            _range_pair(r) for r in [item.get('reference_range',''),*item.get('alternative_reference_ranges',[])]]:
        payload = dict(payload)
        payload.pop('template_warning',None)
        if isinstance(payload.get('template_match'),dict):
            payload['template_match'] = {**payload['template_match'],'reference_match':True,'reference_conflict':False}
        record['payload_json'] = payload
