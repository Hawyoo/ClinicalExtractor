from __future__ import annotations
import json
from pathlib import Path
from .db import connect
from .ocr_process import OCR_PARSER
from .table_extractor import extract_table_rows
from .text_extractor import extract_text
from .normalizer import normalize_record
from .validator import validate_record
from .report_templates import apply_table_template, ALL_TEMPLATE_ID
from .jobs import emit
from .result_rules import is_header_record
from .grounding import ungrounded_legacy_ai

PARSER = OCR_PARSER

def _store_extractions(con, report_id: int, records: list[dict]) -> int:
    manual=con.execute("SELECT id,item_standard,sort_order FROM extractions WHERE report_id=? AND source_kind='manual' ORDER BY sort_order,id",(report_id,)).fetchall()
    manual_codes={str(row['item_standard']).casefold() for row in manual}
    con.execute("DELETE FROM extractions WHERE report_id=? AND source_kind<>'manual'", (report_id,))
    ordered=[]
    for r in records:
        if is_header_record(r) or ungrounded_legacy_ai(r):
            continue
        if str(r.get('item_standard','')).casefold() in manual_codes:
            continue
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
        ordered.append(con.execute('SELECT last_insert_rowid()').fetchone()[0])
    for row in manual:
        ordered.insert(min(max(row['sort_order']-1,0),len(ordered)),row['id'])
    con.executemany('UPDATE extractions SET sort_order=? WHERE id=?',[(i,eid) for i,eid in enumerate(ordered,1)])
    return len(ordered)


def _page_texts(parsed) -> list[tuple[int | None, str]]:
    pages: dict[int | None, list[str]] = {}
    for block in parsed.texts:
        if block.label in {"page_header", "page_footer", "header", "footer"}:
            continue
        if len(block.text.strip()) >= 4:
            pages.setdefault(block.page, []).append(block.text.strip())
    return [(page, "\n".join(parts).strip()) for page, parts in pages.items()]


def _text_records(page_texts: list[tuple[int | None, str]], template_id: str = '') -> list[dict]:
    records: list[dict] = []
    for page, merged in page_texts:
        if len(merged) >= 8:
            emit(f'AI 正在抽取第 {page + 1 if page is not None else 1} 页文本（{len(merged)} 字符）')
            records.extend(extract_text(merged, "generic", page, template_id=template_id))
    return records


def process_report(report_id: int, stage: str = "full"):
    """Run a full report, OCR only, or deferred long-text extraction.

    OCR-only mode deliberately stores all OCR output in SQLite.  Therefore a
    portable application's data directory can be copied to another computer
    before the Ollama-dependent stage is run.
    """
    with connect() as con:
        report = con.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
        if not report:
            raise ValueError("报告不存在")
        report = dict(report)
        if report['profile']=='表格式报告':
            report['template_id'] = ALL_TEMPLATE_ID
            con.execute('UPDATE reports SET template_id=? WHERE id=?',(ALL_TEMPLATE_ID,report_id))
        con.execute("UPDATE reports SET status=?, error='' WHERE id=?", ('AI处理中' if stage == 'llm' else 'OCR处理中', report_id))
    try:
        mode = report["profile"]
        emit('正在读取报告与处理配置')
        if stage == "llm":
            if not report["raw_text"].strip():
                raise ValueError("尚未完成 OCR，请先执行“仅 OCR”")
            if mode == '表格式报告':
                from .parser import TableBlock, html_to_rows
                from .table_ai import correct_names
                records = []
                if report['ocr_text_edited']:
                    from .report_editing import edited_table
                    records=extract_table_rows(edited_table(report['raw_text']))
                    for record in records:
                        record['payload_json']['user_edited_ocr']=True
                else:
                    for page in json.loads(report['parser_json'] or '[]'):
                        for table in page.get('table_res_list',[]):
                            html = table.get('pred_html') or ''
                            records.extend(extract_table_rows(TableBlock(page=page.get('page_index'),html=html,rows=html_to_rows(html),row_repairs=page.get('row_repairs',[]))))
                if not records:
                    # Intact delimited OCR rows can survive a broken HTML table.
                    from .report_editing import edited_table
                    try:
                        records = extract_table_rows(edited_table(report['raw_text']))
                    except ValueError:
                        pass
                if not records:
                    raise ValueError('未恢复出可信的表格行或本次结果。已停止 AI：不能根据项目名单、乱序列或模板猜测数值，请重新识别表格或人工核对。')
                if not report['ocr_text_edited']:
                    from .table_pairing import repair_pairings
                    records = repair_pairings(records, json.loads(report['parser_json'] or '[]'), report['template_id'])
                records = correct_names(records,report['template_id'])
            else:
                records = _text_records([(None, report["raw_text"])], report['template_id'])
            if not records:
                raise ValueError('未找到带有可验证原文结果的指标，未写入 AI 数据。只有项目名时不能补出数值。')
            records = [normalize_record(r) for r in records]
            if mode == "表格式报告":
                records = apply_table_template(records, report["template_id"])
            emit('AI 抽取完成，正在保存结果')
            with connect() as con:
                count=_store_extractions(con, report_id, records)
                con.execute("UPDATE reports SET status='待审核', error='' WHERE id=?", (report_id,))
            return count

        if stage not in {"full", "ocr"}:
            raise ValueError("未知处理阶段")
        from .config import UPLOAD_DIR
        path = Path(report['file_path'])
        if not path.is_file():
            path = UPLOAD_DIR / path.name
        parsed = PARSER.parse(path, table_mode=(mode == '表格式报告'))
        emit(f'OCR 完成：{len(parsed.raw_text)} 字符、{len(parsed.tables)} 个表格')
        records: list[dict] = []
        if mode == "表格式报告":
            emit('正在匹配表格项目与所选模板')
            for table in parsed.tables:
                records.extend(extract_table_rows(table))
        if stage == "full" and mode == "长文本报告":
            records.extend(_text_records(_page_texts(parsed)))
        records = [normalize_record(r) for r in records]
        if mode == "表格式报告":
            records = apply_table_template(records, report["template_id"])
        with connect() as con:
            emit('正在保存 OCR 与结构化结果')
            count=_store_extractions(con, report_id, records)
            status = "OCR已完成" if stage == "ocr" else "待审核"
            if report['ocr_text_edited']:
                from .db import now_iso
                con.execute('INSERT INTO ocr_text_revisions(report_id,previous_text,new_text,created_at) VALUES(?,?,?,?)',
                            (report_id,report['raw_text'],parsed.raw_text,now_iso()))
            con.execute("UPDATE reports SET status=?, raw_text=?, ocr_text_original=?,ocr_text_edited=0,parser_json=?, error='' WHERE id=?", (
                status, parsed.raw_text, parsed.raw_text,
                json.dumps(parsed.parser_json, ensure_ascii=False, default=str), report_id,
            ))
        return count
    except Exception as e:
        with connect() as con:
            con.execute("UPDATE reports SET status='失败', error=? WHERE id=?", (str(e), report_id))
        raise
