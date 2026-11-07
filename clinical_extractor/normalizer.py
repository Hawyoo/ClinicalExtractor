from __future__ import annotations
import re

ITEM_MAP = {
    "wbc": "WBC", "白细胞": "WBC", "白细胞计数": "WBC",
    "hgb": "HGB", "hb": "HGB", "血红蛋白": "HGB",
    "plt": "PLT", "血小板": "PLT", "血小板计数": "PLT",
    "alt": "ALT", "丙氨酸氨基转移酶": "ALT", "谷丙转氨酶": "ALT",
    "ast": "AST", "天门冬氨酸氨基转移酶": "AST", "谷草转氨酶": "AST",
    "cea": "CEA", "ca153": "CA15-3", "ca15-3": "CA15-3", "ca 15-3": "CA15-3",
    "er": "ER", "pr": "PR", "her2": "HER2", "ki67": "Ki-67", "ki-67": "Ki-67",
}

def normalize_item(name: str) -> str:
    key = re.sub(r"[\s_（）()]+", "", (name or "").strip().lower())
    return ITEM_MAP.get(key, (name or "").strip())


def chinese_item_name(item: dict, catalog=None) -> str:
    """Resolve display/export names without changing stored codes/evidence."""
    import json
    from .report_templates import table_templates
    try:
        payload = item.get('payload_json') or {}
        if isinstance(payload, str):
            payload = json.loads(payload)
    except (ValueError, TypeError):
        payload = {}
    standard = item.get('item_standard') or item.get('item_original') or ''
    catalog = table_templates() if catalog is None else catalog
    template_id = payload.get('template_id') or item.get('template_id')
    selected = [catalog[template_id]] if template_id in catalog else catalog.values()
    for template in selected:
        for definition in template['items']:
            if str(standard).casefold() == definition['code'].casefold():
                # Template wording is authoritative in both UI and exports.
                return definition.get('display_name', definition['name'])
    if payload.get('display_name'):
        return payload['display_name']
    common = {'ALT': '丙氨酸氨基转移酶', 'AST': '天门冬氨酸氨基转移酶',
              'CEA': '癌胚抗原', 'CA15-3': '糖类抗原15-3', 'ER': '雌激素受体',
              'PR': '孕激素受体', 'HER2': '人表皮生长因子受体2', 'Ki-67': '细胞增殖指数'}
    if standard in common:
        return common[standard]
    if payload.get('standard_name'):
        return payload['standard_name']
    original = item.get('item_original') or ''
    return original if re.search('[\u4e00-\u9fff]', original) else standard


def item_abbreviation(item: dict, catalog=None) -> str:
    """Use documented template codes/known aliases; never invent a code."""
    from .report_templates import table_templates
    standard = str(item.get('item_standard') or '').strip()
    for template in (table_templates() if catalog is None else catalog).values():
        for definition in template['items']:
            if any(standard.casefold() == str(alias).casefold()
                   for alias in [definition['code'], definition['name'], definition.get('display_name',''),
                                 definition.get('abbreviation',''), *definition.get('aliases', [])]):
                return definition.get('abbreviation', definition['code'])
    normalized = normalize_item(standard)
    known = set(ITEM_MAP.values())
    if normalized in known:
        return normalized
    # Preserve an existing English analyte code, but do not derive one from
    # arbitrary Chinese names or OCR garbage.
    if re.fullmatch(r'[A-Za-z][A-Za-z0-9%#.+/-]{0,19}', standard):
        return standard
    return ''

def normalize_record(r: dict) -> dict:
    r = dict(r)
    r["item_standard"] = normalize_item(r.get("item_standard") or r.get("item_original") or "")
    flag = str(r.get("abnormal_flag") or "").strip().lower()
    if flag in {"h", "high", "↑", "偏高"}: r["abnormal_flag"] = "高"
    elif flag in {"l", "low", "↓", "偏低"}: r["abnormal_flag"] = "低"
    elif flag in {"positive", "+", "阳性"}: r["abnormal_flag"] = "阳性"
    elif flag in {"negative", "-", "阴性"}: r["abnormal_flag"] = "阴性"
    return r
