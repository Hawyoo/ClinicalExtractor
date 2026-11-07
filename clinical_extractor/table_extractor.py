from __future__ import annotations
import re
import unicodedata
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


ROW_UNIT = r'(?:[A-Za-zµμ0-9^²]+(?:/[A-Za-zµμ0-9^².,]+)+|[%％][06]?|fL|pg)'


def _layout_noise(cell, flag):
    """Standalone layout marks, never fragments containing a number or unit."""
    reserved = '<>≤≥+−-/%％^'
    return bool(cell.strip()) and all(
        char.isspace() or re.fullmatch(flag, char) or
        (char not in reserved and unicodedata.category(char).startswith('P'))
        for char in cell)


def _row_fragments(cells, number, interval, flag):
    """Split a cell only when every character has a known row role.

    Original strings remain in evidence. Token offsets stay ordered so a
    missing Tab never moves a result across rows or creates a new number.
    """
    token = re.compile(rf'\s*(?:{ROW_UNIT}|{interval}|{number}|{flag})')
    fragments = []
    splits = []
    for _, cell in cells:
        position = 0
        parts = []
        while position < len(cell):
            match = token.match(cell, position)
            if not match or match.end() == position:
                parts = [cell]  # Unknown text/numbers must not be discarded.
                break
            part = match[0].strip()
            if part:
                parts.append(part)
            position = match.end()
        if len(parts) > 1:
            splits.append({'original':cell, 'fragments':parts})
        fragments.extend(parts)
    return list(enumerate(fragments)), splits


def _headerless_rows(block: TableBlock, rows):
    """Bind only same-line cells; never choose between competing numbers."""
    # A partial header is still authoritative (especially a history column).
    if any(is_column_header(cell, role) or any(word in cell.casefold() for word in
           ('历史结果', '既往结果', 'previous', 'history'))
           for row in rows for cell in row for role in HEADER_ALIASES):
        return []
    number = r'(?:[<>≤≥]=?)?\s*[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?'
    interval = r'[+-]?\d+(?:\.\d+)?\s*[-~～—–至]\s*[+-]?\d+(?:\.\d+)?'
    flag = r'[↑↓↗↘→←↔=＝+\-—~\sHLhlKkVW区以一]*'
    out = []
    for row in rows:
        cells = [(i, str(cell).strip()) for i, cell in enumerate(row) if str(cell).strip()]
        names = [(i, cell) for i, cell in cells
                 if (re.search(r'[\u4e00-\u9fff]', cell) or
                     re.fullmatch(r'[A-Za-z][A-Za-z0-9.()（）_-]*(?:/[A-Za-z]+)?', cell))
                 and not re.fullmatch(flag, cell)
                 and not re.fullmatch(rf'{flag}(?:{interval}|{number}){flag}', cell)
                 and not re.search(r'[/％%]|^(?:fL|pg)$', cell, re.I)]
        # Ratios contain a slash in their name, not a concentration unit.
        names += [(i, cell) for i, cell in cells if re.search(r'[\u4e00-\u9fff]', cell)
                  and '/' in cell and not re.search(r'[A-Za-z]', cell)]
        if len(names) != 1:
            continue
        item_i, item = names[0]
        if is_header_name(item):
            continue
        tail = [(i, cell) for i, cell in cells if i > item_i]
        tail, splits = _row_fragments(tail, number, interval, flag)
        # Serial numbers before the name are excluded by position.
        ranges = [(i, cell) for i, cell in tail if re.fullmatch(interval, cell)]
        numeric = [(i, cell) for i, cell in tail
                   if re.fullmatch(number + r'\s*[↑↓HLhl]?', cell)]
        # A comparator after a result can be a reference bound; before it the
        # role is ambiguous. Do not infer a result from a reference alone.
        bounds = [(i, cell) for i, cell in numeric if re.match(r'[<>≤≥]', cell)]
        if len(numeric) >= 2 and bounds and bounds[0][0] > numeric[0][0]:
            ranges += bounds
            numeric = [(i, cell) for i, cell in numeric if (i, cell) not in bounds]
        if not numeric and not ranges and not any(re.search(r'\d', cell)
                and not re.fullmatch(ROW_UNIT, cell) for _, cell in tail):
            continue
        units = [(i, cell) for i, cell in tail if re.fullmatch(ROW_UNIT, cell)]
        value = numeric[0][1] if len(numeric) == 1 else ''
        ref = ranges[0][1] if len(ranges) == 1 else ''
        warning = ''
        if (len(numeric) != 1 or len(ranges) > 1 or (bounds and not ranges) or
                (ranges and numeric and numeric[0][0] >= ranges[0][0])):
            value = ''
            warning = '本行结果与参考区间未能唯一对应；结果留空，请对照原图填写'
        # Unknown fragments may contain a merged result/history pair.
        accounted = {i for i, _ in numeric + ranges + units}
        noise = []
        if value and len(ranges) == 1:
            # A punctuation-only cell after an independent result does not
            # invalidate a uniquely identified result/reference pair. Keep
            # these original marks in the audit; do not strip inside numbers.
            noise = [(i, cell) for i, cell in tail if i not in accounted
                     and i > numeric[0][0] and _layout_noise(cell, flag)
                     and not re.fullmatch(flag, cell)]
            accounted.update(i for i, _ in noise)
        if any(i not in accounted and not re.fullmatch(flag, cell) for i, cell in tail):
            value = ''
            warning = '本行含有未能区分的内容；结果留空，请对照原图填写'
        low, high = _split_reference(ref)
        payload = {'row': row, 'headers': [], 'reference_raw': ref,
                   'headerless_recovery': True}
        if splits:
            payload['cell_fragments'] = splits
        if noise:
            payload['layout_noise'] = [cell for _, cell in noise]
        if warning:
            payload['ai_review_warning'] = warning
        out.append(dict(source_kind='table', category='检验/检查表格',
                        item_original=item, item_standard=item,
                        value=value.replace('↑', '').replace('↓', '').strip(),
                        value_num=_value_num(value), unit=units[0][1] if len(units) == 1 else '',
                        reference_low=low, reference_high=high,
                        abnormal_flag='低' if any('↓' in c for _, c in tail) else
                                      '高' if any('↑' in c for _, c in tail) else '',
                        evidence=' | '.join(row), page=block.page, bbox_json='',
                        confidence=None, payload_json=payload))
    return out


def extract_table_rows(block: TableBlock):
    rows = [r for r in block.rows if any(c.strip() for c in r)]
    if not rows:
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
        return _headerless_rows(block, rows)
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
