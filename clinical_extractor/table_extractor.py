from __future__ import annotations
import re
from typing import Iterable
from .parser import TableBlock

HEADER_ALIASES = {
    "item": ["项目", "项目名称", "检验项目", "检测项目", "名称", "指标", "item", "test"],
    "value": ["结果", "检测结果", "检验结果", "数值", "value", "result"],
    "unit": ["单位", "unit"],
    "reference": ["参考范围", "参考值", "正常范围", "reference", "range"],
    "flag": ["提示", "异常", "标志", "flag"],
}

def _norm(s: str) -> str:
    return re.sub(r"[\s:：()（）\[\]]+", "", (s or "").lower())

def _find_col(headers: list[str], aliases: Iterable[str]):
    hnorm = [_norm(x) for x in headers]
    for i, h in enumerate(hnorm):
        for a in aliases:
            an = _norm(a)
            if h == an or an in h:
                return i
    return None

def _split_reference(ref: str):
    if not ref:
        return "", ""
    m = re.search(r"(-?\d+(?:\.\d+)?)\s*[-~—–至]\s*(-?\d+(?:\.\d+)?)", ref)
    return (m.group(1), m.group(2)) if m else ("", "")

def _value_num(value: str):
    m = re.search(r"-?\d+(?:\.\d+)?", value or "")
    return float(m.group()) if m else None

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
    headers = rows[header_index]
    item_col = _find_col(headers, HEADER_ALIASES["item"])
    value_col = _find_col(headers, HEADER_ALIASES["value"])
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
        if not item or not value:
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
    return out
