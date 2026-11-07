"""Validate existing OCR result-row assignments without running recognition."""
import re
from collections import Counter


def result_rows(ocr):
    from .table_extractor import is_column_header
    entries = list(zip(ocr['rec_texts'], ocr['rec_boxes']))
    headers = [(str(t), [float(v) for v in b]) for t, b in entries
               if is_column_header(str(t), 'value')]
    item_headers = [(str(t), [float(v) for v in b]) for t, b in entries
                    if is_column_header(str(t), 'item')]
    if len(headers) != 1 or len(item_headers) != 1:
        return []
    _, header = headers[0]
    height = max(1, header[3]-header[1])
    right_headers = [float(b[0]) for t, b in entries if float(b[0]) > header[2]
                     and abs((float(b[1])+float(b[3])-header[1]-header[3])/2) < height*1.5]
    left = (item_headers[0][1][0]+header[0])/2
    right = (header[0]+min(right_headers))/2 if right_headers else header[2]+height*3
    numbers = []
    for index, (text, box) in enumerate(entries):
        box = [float(v) for v in box]
        if not left < (box[0]+box[2])/2 < right or (box[1]+box[3])/2 <= header[3]:
            continue
        if re.fullmatch(r'\s*[<>≤≥]?\s*[+-]?(?:\d+(?:\.\d+)?|\.\d+)\s*[↑↓]?\s*', str(text)):
            numbers.append((index, str(text), box))
    return sorted(numbers, key=lambda row:(row[2][1]+row[2][3])/2)




def assignment_warnings(ocr, tables):
    """Account for independently recognized current results, including repeats."""
    from .table_extractor import extract_table_rows
    def key(value):
        return re.sub(r'\s+', '',str(value)).replace('↑','').replace('↓','')
    source = result_rows(ocr)
    if not source:
        return [dict(message='本页未能独立定位结果列，无法完成数量核验；这不代表结果重复，请核对原图。',
                     kind='verification_unavailable')] if any(extract_table_rows(table) for table in tables) else []
    available = Counter(key(text) for _,text,_ in source)
    assigned = Counter(key(record['value']) for table in tables for record in extract_table_rows(table))
    warnings = []
    unassigned = available-assigned
    for _,text,box in source:
        token = key(text)
        if unassigned[token]:
            warnings.append(dict(message=f'结果 {text} 未能唯一对应项目，未补填或猜测，请核对原图。',
                                 value=text,box=box))
            unassigned[token] -= 1
    for value,count in (assigned-available).items():
        warnings.append(dict(message=f'结果 {value} 的表格配对数量超过原图独立结果数量，请核对。',value=value))
    return warnings


def saved_assignment_warnings(page, records=None):
    """Refresh old audits using retained OCR coordinates, without running OCR."""
    from .parser import TableBlock, html_to_rows
    ocr = page.get('overall_ocr_res') or {}
    if not ocr.get('rec_texts') or not ocr.get('rec_boxes'):
        return page.get('row_warnings', [])
    if records is None:
        tables = [TableBlock(page.get('page_index'), t.get('pred_html', ''), html_to_rows(t.get('pred_html', '')))
                  for t in page.get('table_res_list', [])]
    else:
        tables = [TableBlock(page.get('page_index'), '', [['项目名称','结果']]+
                            [[r['item_original'],str(r['value'])] for r in records])]
    return assignment_warnings(ocr, tables)
