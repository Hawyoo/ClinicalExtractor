from __future__ import annotations
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from bs4 import BeautifulSoup
from .config import load_settings

@dataclass
class TableBlock:
    page: int | None
    html: str
    rows: list[list[str]] = field(default_factory=list)
    bbox: Any = None

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

class PPStructureParser:
    def __init__(self):
        self._pipeline = None

    def _get_pipeline(self):
        settings = load_settings()
        if settings.mock_mode:
            return None
        if self._pipeline is None:
            try:
                from paddleocr import PPStructureV3
            except Exception as e:
                raise RuntimeError(
                    "未安装 PP-StructureV3 依赖。请运行 scripts/install-windows.ps1，"
                    "或安装 PaddlePaddle 与 paddleocr[doc-parser]。"
                ) from e
            kwargs = dict(
                use_doc_orientation_classify=settings.use_doc_orientation_classify,
                use_doc_unwarping=settings.use_doc_unwarping,
                use_textline_orientation=settings.use_textline_orientation,
                use_formula_recognition=settings.use_formula_recognition,
            )
            if settings.pp_device:
                kwargs["device"] = settings.pp_device
            self._pipeline = PPStructureV3(**kwargs)
        return self._pipeline

    def parse(self, file_path: str | Path) -> ParsedDocument:
        path = Path(file_path)
        settings = load_settings()
        if settings.mock_mode or path.suffix.lower() in {".txt", ".md"}:
            text = path.read_text(encoding="utf-8", errors="ignore")
            return ParsedDocument(raw_text=text, tables=[], texts=[TextBlock(page=0, text=text)], parser_json=[])

        pipeline = self._get_pipeline()
        pages = list(pipeline.predict(input=str(path)))
        page_jsons: list[dict] = []
        texts: list[TextBlock] = []
        tables: list[TableBlock] = []
        raw_parts: list[str] = []

        for page_no, res in enumerate(pages):
            data = getattr(res, "json", {}) or {}
            if not isinstance(data, dict):
                try:
                    data = dict(data)
                except Exception:
                    data = {}
            page_jsons.append(data)
            actual_page = data.get("page_index", page_no)

            table_res = data.get("table_res_list") or []
            for t in table_res:
                html = t.get("pred_html", "") or ""
                tables.append(TableBlock(page=actual_page, html=html, rows=html_to_rows(html), bbox=t.get("cell_box_list")))

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
                if fallback:
                    raw_parts.append(fallback)
                    texts.append(TextBlock(page=actual_page, text=fallback, label="ocr"))

        return ParsedDocument(raw_text="\n".join(raw_parts), tables=tables, texts=texts, parser_json=page_jsons)
