"""Repair vertically merged OCR boxes using source result-row coordinates.

No analyte names or template result values are used to split a box.
"""
import re
from collections import Counter
from statistics import median


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


def repair_cross_row_boxes(ocr, image, pipeline, recognizer=None):
    """Re-OCR only boxes spanning several independently observed result rows."""
    import numpy as np
    from .parser import result_data
    rows = result_rows(ocr)
    if len(rows) < 2:
        return []
    typical_height = median(b[3]-b[1] for _, _, b in rows)
    centers = [(b[1]+b[3])/2 for _, _, b in rows]
    heights = [b[3]-b[1] for b in ocr['rec_boxes'] if b[3] > b[1]]
    ordinary_height = median(heights)
    repairs = []
    replacements = {}
    for index, (text, source_box) in enumerate(zip(ocr['rec_texts'], ocr['rec_boxes'])):
        if not str(text).strip():
            continue
        box = [float(v) for v in source_box]
        if box[3]-box[1] < max(typical_height,ordinary_height)*1.8:
            continue
        affected = [j for j, y in enumerate(centers) if box[1]-typical_height*.2 <= y <= box[3]+typical_height*.2]
        if len(affected) < 2:
            continue
        pending = []
        for j in affected:
            y = centers[j]
            top = (centers[j-1]+y)/2 if j else y-typical_height*.75
            bottom = (centers[j+1]+y)/2 if j+1 < len(centers) else y+typical_height*.75
            x1, x2 = max(0,int(box[0]-typical_height*.3)), min(image.shape[1],int(box[2]+typical_height*.3))
            y1, y2 = max(0,int(top)), min(image.shape[0],int(bottom))
            crop = image[y1:y2,x1:x2]
            if not crop.size:
                break
            pieces = []
            # The row/cell is already located. Direct recognition avoids a
            # second detector splitting a single Chinese glyph into strokes.
            if recognizer is not None:
                tight_x1, tight_x2 = max(0,int(box[0])), min(image.shape[1],int(box[2]))
                for prediction in recognizer([image[y1:y2,tight_x1:tight_x2]]):
                    candidate = str(prediction.get('rec_text','')).strip()
                    score = float(prediction.get('rec_score',0))
                    if candidate and score >= .7:
                        pieces.append((candidate,[tight_x1,y1,tight_x2,y2],score))
            for prediction in ([] if pieces else pipeline.predict(input=crop,text_det_limit_side_len=256,text_det_limit_type='min')):
                data = result_data(prediction)
                for candidate, local_box, score in zip(data.get('rec_texts',[]),data.get('rec_boxes',[]),data.get('rec_scores',[])):
                    global_box = [local_box[0]+x1,local_box[1]+y1,local_box[2]+x1,local_box[3]+y1]
                    if float(score) >= .65 and str(candidate).strip() and box[0] <= (global_box[0]+global_box[2])/2 <= box[2]:
                        pieces.append((str(candidate),global_box,float(score)))
            if not pieces:
                break
            pieces.sort(key=lambda p:p[1][0])
            pending.append((' '.join(p[0] for p in pieces),
                            [min(p[1][0] for p in pieces),min(p[1][1] for p in pieces),
                             max(p[1][2] for p in pieces),max(p[1][3] for p in pieces)],
                            min(p[2] for p in pieces)))
        if len(pending) == len(affected):
            replacements[index] = pending
            repairs.append(dict(original_text=str(text),original_box=box,
                                replacements=[dict(text=t,box=b) for t,b,_ in pending]))
    if replacements:
        updated = []
        for index, (text, box) in enumerate(zip(ocr['rec_texts'],ocr['rec_boxes'])):
            updated.extend(replacements.get(index, [(str(text),list(box),float(ocr['rec_scores'][index]))]))
        ocr['rec_texts'] = [t for t,_,_ in updated]
        ocr['rec_boxes'] = np.asarray([b for _,b,_ in updated],dtype=np.float32)
        ocr['rec_scores'] = [s for _,_,s in updated]
        ocr['rec_polys'] = np.asarray([[[b[0],b[1]],[b[2],b[1]],[b[2],b[3]],[b[0],b[3]]] for _,b,_ in updated],dtype=np.float32)
    ocr['row_repairs'] = repairs
    return repairs


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
