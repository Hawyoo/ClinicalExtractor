from __future__ import annotations
import re
from collections import Counter
from typing import Iterable
from .parser import TableBlock
from .result_rules import is_header_name

HEADER_ALIASES = {
    "item": ["项目", "项目名称", "检验项目", "检测项目", "名称", "指标", "item", "test"],
    "value": ["结果", "检测结果", "检验结果", "数值", "value", "result"],
    "unit": ["单位", "unit"],
    "reference": ["参考范围", "参考区间", "参考值", "正常范围", "reference", "range"],
    "flag": ["提示", "异常", "标志", "flag"],
}

def _norm(s: str) -> str:
    return re.sub(r"[\s:：()（）\[\]]+", "", (s or "").lower())


def is_column_header(text: str, role: str) -> bool:
    name = _norm(text)
    if role == 'item':
        name = re.sub(r'^(?:no\.?|序号|\d+)[.、-]*', '', name)
    return name in {_norm(alias) for alias in HEADER_ALIASES[role]}

def _find_col(headers: list[str], aliases: Iterable[str]):
    hnorm = [_norm(x) for x in headers]
    for i, h in enumerate(hnorm):
        for a in aliases:
            an = _norm(a)
            if h == an or an in h:
                return i
    return None


def _result_col(headers):
    eligible = [(i,_norm(h)) for i,h in enumerate(headers)
                if not any(word in _norm(h) for word in ('历史','既往','上次','参考','history','previous','reference'))]
    aliases = [_norm(a) for a in HEADER_ALIASES['value']] + ['本次结果']
    for i,header in eligible:
        if header in aliases:
            return i
    return next((i for i,header in eligible if any(alias in header for alias in aliases)),None)

def _split_reference(ref: str):
    if not ref:
        return "", ""
    m = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*[-~—–至]\s*(-?\d+(?:\.\d+)?)\s*", ref)
    return (m.group(1), m.group(2)) if m else ("", "")

def _value_num(value: str):
    m = re.search(r"-?\d+(?:\.\d+)?", value or "")
    return float(m.group()) if m else None

def _align_padded_header(headers, body):
    """Recover padded headers from stable source columns, without moving cells."""
    item_col = _find_col(headers, HEADER_ALIASES['item'])
    value_col = _result_col(headers)
    if item_col is None or value_col is None or not any(not c.strip() for c in headers):
        return headers
    if any(any(word in _norm(c) for word in ('历史', '既往', '上次', 'history', 'previous')) for c in headers):
        return headers
    numeric = r'[<>≤≥]?\s*[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\s*[↑↓HLhl]?'
    reference = r'(?:[<>≤≥]=?\s*\d+(?:\.\d+)?|\d+(?:\.\d+)?\s*[-~～—–至]\s*\d+(?:\.\d+)?)'
    votes = []
    eligible = 0
    for row in body:
        if item_col >= len(row) or not row[item_col].strip() or is_header_name(row[item_col]):
            continue
        eligible += 1
        refs = [i for i in range(item_col + 1, len(row)) if re.fullmatch(reference, row[i].strip())]
        if len(refs) != 1:
            continue
        ref = refs[0]
        values = [i for i in range(item_col + 1, ref) if re.fullmatch(numeric, row[i].strip())]
        if values:
            votes.append((values[0], ref))
    if not votes:
        return headers
    (value, ref), count = Counter(votes).most_common(1)[0]
    if count < 3 or count < .8 * eligible:
        return headers
    old_ref = _find_col(headers, HEADER_ALIASES['reference'])
    if value == value_col and ref == old_ref:
        return headers
    aligned = [''] * max(len(headers), max(map(len, body), default=0))
    aligned[item_col], aligned[value], aligned[ref] = '项目名称', '结果', '参考区间'
    if _find_col(headers, HEADER_ALIASES['unit']) is not None and ref + 1 < len(aligned):
        aligned[ref + 1] = '单位'
    if ref == value + 2:
        aligned[value + 1] = '标志'
    return aligned


def extract_table_rows(block: TableBlock):
    rows = [r for r in block.rows if any(c.strip() for c in r)]
    if len(rows) < 2:
        return []
    header_index = 0
    best_score = -1
    for idx, row in enumerate(rows[:5]):
        score = sum(any(_norm(a) in _norm(c) for a in sum(HEADER_ALIASES.values(), [])) for c in row)
        if score > best_score:
            best_score, header_index = score, idx
    original_headers = rows[header_index]
    headers = _align_padded_header(original_headers, rows[header_index + 1:])
    item_col = _find_col(headers, HEADER_ALIASES["item"])
    value_col = _result_col(headers)
    unit_col = _find_col(headers, HEADER_ALIASES["unit"])
    ref_col = _find_col(headers, HEADER_ALIASES["reference"])
    flag_col = _find_col(headers, HEADER_ALIASES["flag"])
    if item_col is None or value_col is None:
        return []
    out = []
    for row in rows[header_index + 1:]:
        if max(item_col, value_col) >= len(row):
            continue
        item = row[item_col].strip()
        value = row[value_col].strip()
        if not item or not value or is_header_name(item):
            continue
        # A merged cell containing two numbers cannot represent one lab result.
        # Never silently take its first number as the patient's result.
        if len(re.findall(r'\d+(?:\.\d+)?', value)) > 1:
            continue
        unit = row[unit_col].strip() if unit_col is not None and unit_col < len(row) else ""
        ref = row[ref_col].strip() if ref_col is not None and ref_col < len(row) else ""
        flag = row[flag_col].strip() if flag_col is not None and flag_col < len(row) else ""
        if not flag:
            flag = "高" if "↑" in value else ("低" if "↓" in value else "")
        low, high = _split_reference(ref)
        out.append({
            "source_kind": "table",
            "category": "检验/检查表格",
            "item_original": item,
            "item_standard": item,
            "value": value.replace("↑", "").replace("↓", "").strip(),
            "value_num": _value_num(value),
            "unit": unit,
            "reference_low": low,
            "reference_high": high,
            "abnormal_flag": flag,
            "evidence": " | ".join(row),
            "page": block.page,
            "bbox_json": "",
            "confidence": None,
            "payload_json": {"headers": headers, "row": row, "reference_raw": ref},
        })
        if headers != original_headers:
            out[-1]['payload_json']['headers_original'] = original_headers
            out[-1]['payload_json']['header_alignment'] = '按多行原文结果及参考区间位置校正空列表头'
        repaired = [repair for repair in block.row_repairs if
                    any(part['text'] == item for part in repair['replacements'])]
        if repaired:
            out[-1]['payload_json']['item_correction'] = f"{'；'.join(r['original_text'] for r in repaired)} → {item}（按原图分行重识别）"
    return out
