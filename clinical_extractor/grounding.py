"""A model may interpret names; a value must be copied from source evidence."""
import json
import re
import unicodedata


def _plain(text):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(text or '')))


def value_is_grounded(value, evidence, item='', unit=''):
    value = _plain(value).strip('↑↓')
    evidence = _plain(evidence)
    if not value or not evidence:
        return False
    # Digits in an analyte name (Ki-67, HER2) or unit are not results.
    for metadata in (item, unit):
        if metadata:
            evidence = evidence.replace(_plain(metadata), '')
    evidence = re.split(r'参考(?:值|范围)|历史结果', evidence)[0]
    if re.search(r'\d', value):
        return bool(re.search(r'(?<![A-Za-z0-9_.^])' + re.escape(value) + r'(?![A-Za-z0-9_.])', evidence))
    return value in evidence


def ungrounded_legacy_ai(record):
    payload = record.get('payload_json') or {}
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (ValueError, TypeError):
            return False
    if payload.get('manual_value_verified'):
        return False
    if record.get('source_kind') != 'text' or 'char_start' not in payload:
        return False
    if record.get('profile') == '表格式报告':
        # Old free-text AI table results have no verified source-cell binding.
        return True
    return not value_is_grounded(record.get('value'), record.get('evidence'),
                                 payload.get('item_ocr_original') or record.get('item_original'), record.get('unit'))
