from __future__ import annotations
import json
from pathlib import Path
from .db import connect
from .parser import PPStructureParser
from .table_extractor import extract_table_rows
from .text_extractor import extract_text
from .normalizer import normalize_record
from .validator import validate_record

PARSER = PPStructureParser()

def process_report(report_id: int):
    with connect() as con:
        report = con.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
        if not report:
            raise ValueError("报告不存在")
        con.execute("UPDATE reports SET status='处理中', error='' WHERE id=?", (report_id,))
    try:
        parsed = PARSER.parse(report["file_path"])
        records = []
        for table in parsed.tables:
            records.extend(extract_table_rows(table))
        # 同页非表格文本合并后一次送入 LangExtract，减少重复LLM调用。
        page_texts = {}
        for block in parsed.texts:
            if block.label in {"page_header", "page_footer", "header", "footer"}:
                continue
            if len(block.text.strip()) >= 4:
                page_texts.setdefault(block.page, []).append(block.text.strip())
        for page, parts in page_texts.items():
            merged = "\n".join(parts).strip()
            if len(merged) >= 8:
                records.extend(extract_text(merged, report["profile"], page))
        records = [normalize_record(r) for r in records]
        with connect() as con:
            con.execute("DELETE FROM extractions WHERE report_id=?", (report_id,))
            for r in records:
                warnings = validate_record(r)
                payload = dict(r.get("payload_json") or {})
                if warnings:
                    payload["warnings"] = warnings
                con.execute("""
                    INSERT INTO extractions(
                      report_id,source_kind,category,item_original,item_standard,value,value_num,unit,
                      reference_low,reference_high,abnormal_flag,evidence,page,bbox_json,confidence,reviewed,payload_json
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    report_id, r.get("source_kind",""), r.get("category",""), r.get("item_original",""),
                    r.get("item_standard",""), r.get("value",""), r.get("value_num"), r.get("unit",""),
                    r.get("reference_low",""), r.get("reference_high",""), r.get("abnormal_flag",""),
                    r.get("evidence",""), r.get("page"), r.get("bbox_json",""), r.get("confidence"), 0,
                    json.dumps(payload, ensure_ascii=False),
                ))
            con.execute("UPDATE reports SET status='待审核', raw_text=?, parser_json=?, error='' WHERE id=?", (
                parsed.raw_text, json.dumps(parsed.parser_json, ensure_ascii=False, default=str), report_id
            ))
        return len(records)
    except Exception as e:
        with connect() as con:
            con.execute("UPDATE reports SET status='失败', error=? WHERE id=?", (str(e), report_id))
        raise
