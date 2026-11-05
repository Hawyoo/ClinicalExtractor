from __future__ import annotations
import json
import re
from html import escape
from statistics import median
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Any
from bs4 import BeautifulSoup
from .config import load_settings, ocr_thread_count
from .jobs import emit

@dataclass
class TableBlock:
    page: int | None
    html: str
    rows: list[list[str]] = field(default_factory=list)
    bbox: Any = None
    row_repairs: list[dict] = field(default_factory=list)

@dataclass
class TextBlock:
    page: int | None
    text: str
    label: str = "text"
    bbox: Any = None

@dataclass
class ParsedDocument:
    raw_text: str
    tables: list[TableBlock]
    texts: list[TextBlock]
    parser_json: list[dict]


def html_to_rows(html: str) -> list[list[str]]:
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for tr in soup.find_all("tr"):
        cells = [re.sub(r"\s+", " ", c.get_text(" ", strip=True)).strip() for c in tr.find_all(["th", "td"])]
        if cells:
            rows.append(cells)
    return rows

def lightweight_pipeline_config(table_mode: bool = True) -> dict:
    """BCE-style OCR plus the official SLANet+ matching pipeline, no layout models."""
    ocr = {
        'pipeline_name': 'OCR', 'text_type': 'general',
        'use_doc_preprocessor': False, 'use_textline_orientation': False,
        'SubModules': {
            'TextDetection': {'module_name': 'text_detection',
                              'model_name': 'PP-OCRv5_server_det', 'model_dir': None,
                              'limit_side_len': 1920, 'limit_type': 'max',
                              'max_side_limit': 4000, 'thresh': .3,
                              'box_thresh': .6, 'unclip_ratio': 1.5},
            'TextRecognition': {'module_name': 'text_recognition',
                                'model_name': 'PP-OCRv5_server_rec', 'model_dir': None,
                                'batch_size': 6, 'score_thresh': 0},
        },
    }
    if not table_mode:
        return ocr
    return {
        'pipeline_name': 'table_recognition',
        'use_doc_preprocessor': False, 'use_layout_detection': False,
        'use_ocr_model': True,
        'SubModules': {'TableStructureRecognition': {
            'module_name': 'table_structure_recognition',
            'model_name': 'SLANet_plus', 'model_dir': None}},
        'SubPipelines': {'GeneralOCR': ocr},
    }


def result_data(result) -> dict:
    """Use JSON serialization, not printable `.str` (which loses numpy coordinates)."""
    payload = getattr(result, 'json', result)
    if callable(payload):
        payload = payload()
    if isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, dict):
        raise RuntimeError('OCR 返回了无法读取的结果')
    data = payload.get('res', payload)
    if 'error' in data:
        raise RuntimeError(str(data['error']))
    # Nested OCR sub-results in some PaddleX versions still contain ndarrays.
    # Convert their numeric contents, rather than saving printable strings.
    def safe(value):
        if isinstance(value, dict):
            return {k: safe(v) for k, v in value.items() if k not in {'input_img', 'output_img'}}
        if isinstance(value, (list, tuple)):
            return [safe(v) for v in value]
        if hasattr(value, 'tolist'):
            return value.tolist()
        return value
    return safe(data)


def coordinate_table_rows(ocr):
    """Resolve lab rows using real headers and OCR coordinates, never numeric plausibility.

    SLANet may merge adjacent rows. A header-anchored coordinate reconstruction
    provides a conservative alternative for standard lab tables.
    """
    from .table_extractor import HEADER_ALIASES, _norm, is_column_header
    entries = [(str(t).strip(), [float(v) for v in b])
               for t, b in zip(ocr['rec_texts'], ocr['rec_boxes']) if str(t).strip()]
    header_groups = []
    for text, box in entries:
        if not is_column_header(text, 'item'):
            continue
        height = box[3]-box[1]
        candidates = [(t, b) for t, b in entries
                      if abs((b[1]+b[3]-box[1]-box[3])/2) < height*1.5]
        group = {}
        for role in ('item', 'value', 'unit', 'reference'):
            hits = [(t, b) for t, b in candidates if is_column_header(t, role)]
            if len(hits) == 1:
                group[role] = hits[0]
        if {'item', 'value'}.issubset(group) and len(group) >= 3:
            header_groups.append(group)
    # Multiple panels need independent column boundaries; fail closed for now.
    if len(header_groups) != 1:
        return []
    group = header_groups[0]
    # Include history/flag columns as boundaries, but never extract their values.
    columns = [(role, t, b) for role, (t, b) in group.items()]
    for text, box in entries:
        if abs((box[1]+box[3]-group['item'][1][1]-group['item'][1][3])/2) < (group['item'][1][3]-group['item'][1][1])*1.5:
            if any(w in text for w in ('历史', '既往', '上次', '异常', '标志')):
                columns.append(('ignore', text, box))
    columns.sort(key=lambda c: (c[2][0]+c[2][2])/2)
    # Headers are often centered while data are left-aligned. Use header left
    # edges to avoid assigning long reference ranges to the history column.
    centers = [b[0] for _, _, b in columns]
    boundaries = [(a+b)/2 for a, b in zip(centers, centers[1:])]
    top = max(b[3] for _, _, b in columns)
    bottom = min((b[1] for t, b in entries if b[1] > top and
                  any(w in t for w in ('条记录', '诊断及建议', '审核医师', '报告医师'))), default=float('inf'))
    buckets = {i: [] for i in range(len(columns))}
    for text, box in entries:
        center = (box[0]+box[2])/2
        index = sum(center > boundary for boundary in boundaries)
        # A photographed header slopes across columns. The first item can
        # start above the unit header's bottom while already being below its
        # own header. Compare box centers to the header in the same column.
        if (box[1]+box[3])/2 <= columns[index][2][3] or box[3] >= bottom:
            continue
        buckets[index].append((text, box))
    item_index = next(i for i, c in enumerate(columns) if c[0] == 'item')
    typical_height = median(b[3]-b[1] for _,b in entries if b[3]>b[1])
    repaired_boxes = {tuple(part['box']) for repair in ocr.get('row_repairs',[]) for part in repair['replacements']}
    def unresolved_box(box):
        return box[3]-box[1] >= typical_height*1.8 and tuple(box) not in repaired_boxes
    fragments = sorted([(t, b) for t, b in buckets[item_index] if re.search(r'[A-Za-z\u4e00-\u9fff]', t)
                        and not unresolved_box(b)],
                     key=lambda e: (e[1][1]+e[1][3])/2)
    anchors = []
    for text, box in fragments:
        if anchors and abs((box[1]+box[3]-anchors[-1][1][1]-anchors[-1][1][3])/2) < min(box[3]-box[1], anchors[-1][1][3]-anchors[-1][1][1])*.5:
            old_text, old_box = anchors[-1]
            anchors[-1] = (old_text+' '+text, [min(old_box[0],box[0]), min(old_box[1],box[1]), max(old_box[2],box[2]), max(old_box[3],box[3])])
        else:
            anchors.append((text, box))
    if len(anchors) < 2:
        return []
    anchor_y = [(b[1]+b[3])/2 for _, b in anchors]
    gaps = [b-a for a, b in zip(anchor_y, anchor_y[1:]) if b > a]
    typical_gap = sorted(gaps)[len(gaps)//2]
    assigned = [[[] for _ in columns] for _ in anchors]
    item_header = columns[item_index][2]
    item_header_y = (item_header[1]+item_header[3])/2
    for i, (_, _, header_box) in enumerate(columns):
        # Map this column's vertical axis to the item column. Header positions
        # provide the tilt offset; repeated line spacing estimates perspective
        # scale. Missing cells are not filled or shifted by array position.
        column_y = sorted((b[1]+b[3])/2 for _,b in buckets[i] if not unresolved_box(b))
        line_centers = []
        for center in column_y:
            if not line_centers or center-line_centers[-1] > typical_height*.6:
                line_centers.append(center)
        column_gaps = [b-a for a,b in zip(line_centers,line_centers[1:])
                       if typical_gap*.7 <= b-a <= typical_gap*1.3]
        scale = typical_gap/median(column_gaps) if len(column_gaps)>=2 else 1
        if not .85 <= scale <= 1.15:
            scale = 1
        header_y = (header_box[1]+header_box[3])/2
        for text, box in buckets[i]:
            if unresolved_box(box):
                continue
            if i == item_index and not re.search(r'[A-Za-z\u4e00-\u9fff]', text):
                continue
            y = item_header_y + ((box[1]+box[3])/2-header_y)*scale
            distances = sorted((abs(y-a), j) for j, a in enumerate(anchor_y))
            distance, j = distances[0]
            if distance > typical_gap*.48 or (len(distances)>1 and distances[1][0]-distance < typical_gap*.15):
                continue
            assigned[j][i].append((text, box))
    rows = [[text for _, text, _ in columns]]
    value_index = next(i for i, c in enumerate(columns) if c[0] == 'value')
    for cells in assigned:
        values = [t for t, _ in cells[value_index] if re.search(r'\d', t)]
        # Separate numeric tokens are ambiguous; never concatenate two results.
        if len(values) != 1 or len(re.findall(r'\d+(?:\.\d+)?', values[0])) != 1:
            continue
        rows.append([' '.join(t for t, _ in sorted(cell, key=lambda e:e[1][0])) for cell in cells])
    return rows if len(rows) > 1 else []


def table_region(ocr, image_shape):
    """Locate a lab table by its actual headers; never use template values."""
    from .table_extractor import HEADER_ALIASES, _norm, is_column_header
    texts, boxes = ocr['rec_texts'], ocr['rec_boxes']
    headers = []
    for text, box in zip(texts, boxes):
        name = _norm(text)
        roles = {role for role in ('item', 'value', 'unit', 'reference')
                 if is_column_header(text, role)}
        if roles:
            headers.append((roles, [float(v) for v in box]))
    for roles, anchor in headers:
        if 'item' not in roles:
            continue
        height = max(anchor[3] - anchor[1], 1)
        group = [(r, b) for r, b in headers if abs((b[1]+b[3]-anchor[1]-anchor[3])/2) < height*1.5]
        found = set().union(*(r for r, _ in group))
        if not {'item', 'value'}.issubset(found) or not found.intersection({'unit', 'reference'}):
            continue
        top = max(0, min(b[1] for _, b in group) - height*.25)
        bottom = image_shape[0]-1
        for text, box in zip(texts, boxes):
            if float(box[1]) > anchor[3] and any(w in text for w in ('诊断及建议', '审核医师', '条记录', '报告医师')):
                bottom = min(bottom, float(box[1])-height*.15)
        return [0, int(top), image_shape[1]-1, int(bottom)]
    return None


class LightweightPipeline:
    """Recover reliable coordinate rows first; load SLANet+ only as a fallback."""
    def __init__(self, create_pipeline, kwargs, table_mode):
        started = perf_counter()
        self.ocr = create_pipeline(config=lightweight_pipeline_config(False), **kwargs)
        self._ocr_load_seconds = perf_counter() - started
        self._create_pipeline, self._kwargs = create_pipeline, kwargs
        self._table_mode = table_mode
        self.table = None

    def prepare_fallback_model(self):
        """Explicitly prepare SLANet+ for offline packaging or first fallback."""
        if self.table is None:
            config = lightweight_pipeline_config(True)
            config['use_ocr_model'] = False
            self.table = self._create_pipeline(config=config, **self._kwargs)

    def _coordinate_result(self, ocr, repairs):
        from .ocr_row_repair import assignment_warnings
        rows = coordinate_table_rows(ocr)
        if not rows:
            return None
        block = TableBlock(page=ocr.get('page_index'), html='', rows=rows)
        if assignment_warnings(ocr, [block]):
            return None
        html = '<table>' + ''.join('<tr>'+''.join('<td>'+escape(c)+'</td>' for c in row)+'</tr>' for row in rows) + '</table>'
        return result_data(dict(input_path=ocr.get('input_path'), page_index=ocr.get('page_index'),
                                overall_ocr_res=ocr, table_res_list=[dict(pred_html=html,
                                    structure_source='ocr_header_coordinates')],
                                row_repairs=repairs, row_warnings=[], ocr_pipeline='PP-OCRv5+coordinates'))

    def predict(self, input):
        predictions = iter(self.ocr.predict(input=input))
        while True:
            started = perf_counter()
            try:
                ocr = next(predictions)
            except StopIteration:
                break
            timings = dict(ocr_seconds=perf_counter()-started, ocr_model_load_seconds=self._ocr_load_seconds,
                           coordinate_seconds=0, local_reocr_seconds=0, table_seconds=0, table_model_load_seconds=0)
            self._ocr_load_seconds = 0
            if not self._table_mode:
                yield ocr
                continue
            emit('文字识别完成，正在按坐标恢复行列')
            started = perf_counter()
            data = self._coordinate_result(ocr, [])
            timings['coordinate_seconds'] += perf_counter()-started
            if data is not None:
                data['stage_timings'] = timings
                yield data
                continue
            image = ocr['doc_preprocessor_res']['output_img']
            from .ocr_row_repair import assignment_warnings
            # Keep the first OCR's text/coordinates. No crop or second OCR pass.
            repairs = []
            emit('坐标恢复未通过核验，正在使用表格模型')
            if self.table is None:
                started = perf_counter()
                self.prepare_fallback_model()
                timings['table_model_load_seconds'] = perf_counter()-started
            box = table_region(ocr, image.shape)
            layout = {'boxes': [{'cls_id': 0, 'label': 'table', 'coordinate': box}]} if box else None
            started = perf_counter()
            for result in self.table.predict(input=image, overall_ocr_res=ocr,
                                             layout_det_res=layout,
                                             cell_sort_by_y_projection=True):
                # The second pipeline takes a numpy image; retain original PDF page metadata.
                result['page_index'] = ocr.get('page_index')
                result['input_path'] = ocr.get('input_path')
                data = result_data(result)
                data['row_repairs'] = repairs
                timings['table_seconds'] = perf_counter()-started
                data['stage_timings'] = timings.copy()
                data['ocr_pipeline'] = 'PP-OCRv5+SLANet_plus'
                for table in data.get('table_res_list', []):
                    table['structure_source'] = 'SLANet_plus'
                table_blocks = [TableBlock(page=data.get('page_index'),html=t['pred_html'],rows=html_to_rows(t['pred_html'])) for t in data.get('table_res_list',[])]
                data['row_warnings'] = assignment_warnings(ocr, table_blocks)
                yield data


class PPStructureParser:
    # Keep the old class name for callers and existing scripts.
    def __init__(self, cpu_threads=None, enable_mkldnn=False):
        self._pipeline = None
        self._table_mode = None
        self._cpu_threads = cpu_threads
        self._enable_mkldnn = enable_mkldnn
        self._pipeline_key = None

    def _get_pipeline(self, table_mode: bool = True):
        settings = load_settings()
        if settings.mock_mode:
            return None
        threads = ocr_thread_count(self._cpu_threads if self._cpu_threads is not None else settings.ocr_cpu_threads)
        key = (table_mode,settings.pp_device,threads,self._enable_mkldnn)
        if self._pipeline is None or self._pipeline_key != key:
            self._pipeline = None
            emit('正在加载 OCR 模型（首次加载需要等待）')
            try:
                import paddle
                from paddlex import create_pipeline
            except Exception as e:
                raise RuntimeError(
                    "未安装 OCR 依赖。请运行 scripts/install-windows.ps1，"
                    "或安装 PaddlePaddle 与 paddleocr[doc-parser]。"
                ) from e
            try:
                paddle.set_flags({"FLAGS_use_mkldnn": bool(self._enable_mkldnn)})
            except Exception:
                # Per-predictor run_mode below also controls oneDNN when a
                # Paddle build does not expose the global flag API.
                pass
            self._pipeline = LightweightPipeline(create_pipeline, dict(
                device=settings.pp_device or 'cpu', engine='paddle',
                engine_config={'paddle_static': {'run_mode': 'mkldnn' if self._enable_mkldnn else 'paddle',
                                                'cpu_threads': threads}},
            ), table_mode)
            self._table_mode = table_mode
            self._pipeline_key = key
        return self._pipeline

    def parse(self, file_path: str | Path, table_mode: bool = True) -> ParsedDocument:
        path = Path(file_path)
        settings = load_settings()
        if settings.mock_mode or path.suffix.lower() in {".txt", ".md"}:
            text = path.read_text(encoding="utf-8", errors="ignore")
            return ParsedDocument(raw_text=text, tables=[], texts=[TextBlock(page=0, text=text)], parser_json=[])

        pipeline = self._get_pipeline(table_mode)
        emit('正在进行文字识别与行列恢复' if table_mode else '正在进行文字识别')
        pages = []
        for result in pipeline.predict(input=str(path)):
            pages.append(result)
            emit(f'已完成第 {len(pages)} 页 OCR，正在整理结果', pages_done=len(pages))
        page_jsons: list[dict] = []
        texts: list[TextBlock] = []
        tables: list[TableBlock] = []
        raw_parts: list[str] = []

        for page_no, res in enumerate(pages):
            data = result_data(res)
            if not table_mode:
                data = {'page_index': data.get('page_index', page_no),
                        'overall_ocr_res': data, 'table_res_list': []}
            data.setdefault('ocr_pipeline', 'PP-OCRv5+SLANet_plus' if table_mode else 'PP-OCRv5')
            page_jsons.append(data)
            actual_page = data.get("page_index")
            if actual_page is None:
                actual_page = page_no
            data['page_index'] = actual_page

            table_res = data.get("table_res_list") or []
            for t in table_res:
                html = t.get("pred_html", "") or ""
                tables.append(TableBlock(page=actual_page, html=html, rows=html_to_rows(html), bbox=t.get("cell_box_list"), row_repairs=data.get('row_repairs',[])))

            parsing = data.get("parsing_res_list") or []
            for b in parsing:
                label = str(b.get("block_label", "text") or "text").lower()
                content = str(b.get("block_content", "") or "").strip()
                if not content:
                    continue
                raw_parts.append(content)
                if label != "table":
                    texts.append(TextBlock(page=actual_page, text=content, label=label, bbox=b.get("block_bbox")))

            if not parsing:
                ocr = data.get("overall_ocr_res") or {}
                fallback = "\n".join(str(x) for x in (ocr.get("rec_texts") or []) if str(x).strip())
                if tables:
                    # Preserve row/column separators in the text sent downstream.
                    fallback = '\n'.join('\t'.join(row) for table in tables
                                         if table.page == actual_page for row in table.rows) or fallback
                if fallback:
                    raw_parts.append(fallback)
                    texts.append(TextBlock(page=actual_page, text=fallback, label="ocr"))

        return ParsedDocument(raw_text="\n".join(raw_parts), tables=tables, texts=texts, parser_json=page_jsons)
