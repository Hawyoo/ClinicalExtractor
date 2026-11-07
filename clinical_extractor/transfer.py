"""Portable OCR batch export/import without copying SQLite database files."""
from __future__ import annotations

import json
import shutil
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import config
from .db import connect, now_iso

MANIFEST_NAME = "clinical-extractor-ocr-transfer.json"
TRANSFER_SUFFIX = ".ceocr"
REPORT_FIELDS = (
    "patient_id", "report_type", "profile", "filename",
    "status", "raw_text", "parser_json", "error", "transfer_key", "created_at", "template_id",
    "ocr_text_original", "ocr_text_edited",
)
EXTRACTION_FIELDS = (
    "source_kind", "category", "item_original", "item_standard", "value",
    "value_num", "unit", "reference_low", "reference_high", "abnormal_flag",
    "evidence", "page", "bbox_json", "confidence", "reviewed", "payload_json",
)


def _stored_path(file_path: str) -> Path:
    return config.UPLOAD_DIR / Path(file_path).name


@dataclass(frozen=True)
class ImportResult:
    imported: int
    replaced: int
    skipped: int


def _read_manifest(source: Path) -> dict:
    with zipfile.ZipFile(source) as archive:
        if MANIFEST_NAME not in archive.namelist():
            raise ValueError("这不是 ClinicalExtractor OCR 数据包")
        manifest = json.loads(archive.read(MANIFEST_NAME).decode("utf-8"))
    if manifest.get("format") != "clinical-extractor-ocr-transfer" or manifest.get("version") != 1:
        raise ValueError("OCR 数据包版本不受支持")
    if not str(manifest.get("batch_id", "")).strip() or not isinstance(manifest.get("reports"), list):
        raise ValueError("OCR 数据包内容不完整")
    return manifest


def create_transfer(destination: Path) -> int:
    """Export all reports, including untouched originals and processed results."""
    with connect() as con:
        con.execute('BEGIN')
        reports = con.execute("SELECT * FROM reports ORDER BY id").fetchall()
        extractions = {
            row["id"]: [dict(x) for x in con.execute(
                "SELECT * FROM extractions WHERE report_id=? ORDER BY sort_order,id", (row["id"],)
            ).fetchall()]
            for row in reports
        }
    if not reports:
        raise ValueError("没有可导出的报告")
    for report in reports:
        if not report['raw_text'].strip() and not _stored_path(report['file_path']).is_file():
            raise ValueError(f"原始文件缺失，无法打包未处理的报告：{report['filename']}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "format": "clinical-extractor-ocr-transfer",
        "version": 1,
        "batch_id": str(uuid.uuid4()),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "reports": [],
    }
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for report in reports:
            archive_file = ""
            source = _stored_path(report["file_path"])
            if source.is_file():
                archive_file = f"uploads/{report['id']}_{source.name}"
                archive.write(source, archive_file)
            manifest["reports"].append({
                "report": {field: report[field] for field in REPORT_FIELDS},
                "archive_file": archive_file,
                "extractions": [
                    {field: item[field] for field in EXTRACTION_FIELDS}
                    for item in extractions[report["id"]]
                ],
            })
        archive.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2))
    return len(reports)


def inspect_transfer(source: Path) -> dict:
    """Preview conflicts using stable report keys, without changing local data."""
    manifest = _read_manifest(source)
    conflicts = []
    with connect() as con:
        for entry in manifest["reports"]:
            record = entry.get("report") or {}
            if not isinstance(record, dict):
                raise ValueError("OCR 数据包中的报告记录无效")
            key = str(record.get("transfer_key") or "")
            existing = con.execute("SELECT id,patient_id,filename,status FROM reports WHERE transfer_key=?", (key,)).fetchone() if key else None
            if existing:
                conflicts.append({
                    "transfer_key": key,
                    "patient_id": record.get("patient_id") or existing["patient_id"] or "未填写患者 ID",
                    "filename": record.get("filename") or existing["filename"],
                    "incoming_status": record.get("status") or "OCR已完成",
                    "existing_status": existing["status"],
                })
    return {"report_count": len(manifest["reports"]), "conflicts": conflicts}


def _copy_source_file(archive: zipfile.ZipFile, archive_file: str) -> str:
    if not archive_file:
        return ""
    if archive_file not in archive.namelist() or not archive_file.startswith("uploads/"):
        raise ValueError("OCR 数据包包含无效的原始文件路径")
    stored_name = f"{uuid.uuid4().hex[:10]}_{Path(archive_file).name}"
    with archive.open(archive_file) as reader, (config.UPLOAD_DIR / stored_name).open("wb") as writer:
        shutil.copyfileobj(reader, writer)
    return str(config.UPLOAD_DIR / stored_name)


def import_transfer(source: Path, replace_keys: set[str] | None = None) -> ImportResult:
    """Import new reports and replace only explicitly selected existing reports."""
    replace_keys = replace_keys or set()
    manifest = _read_manifest(source)
    imported = replaced = skipped = 0
    with zipfile.ZipFile(source) as archive:
        with connect() as con:
            for entry in manifest["reports"]:
                record = entry.get("report") or {}
                if not isinstance(record, dict):
                    raise ValueError("OCR 数据包中的报告记录无效")
                key = str(record.get("transfer_key") or uuid.uuid4())
                existing = con.execute("SELECT id FROM reports WHERE transfer_key=?", (key,)).fetchone()
                if existing and key not in replace_keys:
                    skipped += 1
                    continue
                if existing:
                    con.execute("DELETE FROM reports WHERE id=?", (existing["id"],))
                    replaced += 1
                else:
                    imported += 1
                file_path = _copy_source_file(archive, str(entry.get("archive_file") or ""))
                raw_text = str(record.get('raw_text') or '')
                status = str(record.get('status') or ('OCR已完成' if raw_text.strip() else '未处理'))
                if status in {'OCR排队中','OCR处理中','AI排队中','AI处理中'}:
                    status = 'OCR已完成' if raw_text.strip() else '未处理'
                con.execute("""
                    INSERT INTO reports(patient_id,report_type,profile,filename,file_path,status,raw_text,parser_json,error,transfer_key,created_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    str(record.get("patient_id", "")),
                    str(record.get("report_type", "")), str(record.get("profile", "长文本报告")),
                    str(record.get("filename", "导入报告")), file_path,
                    status, raw_text,
                    str(record.get("parser_json", "")), str(record.get("error", "")), key,
                    str(record.get("created_at", now_iso())),
                ))
                report_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
                con.execute("UPDATE reports SET template_id=? WHERE id=?", ('all' if record.get('profile')=='表格式报告' else '', report_id))
                con.execute('UPDATE reports SET ocr_text_original=?,ocr_text_edited=? WHERE id=?',
                            (str(record.get('ocr_text_original') or ''),int(record.get('ocr_text_edited',0) in (1,True,'1')),report_id))
                for position,item in enumerate(entry.get("extractions", []),1):
                    if not isinstance(item, dict):
                        continue
                    con.execute("""
                        INSERT INTO extractions(report_id,source_kind,category,item_original,item_standard,value,value_num,unit,
                        reference_low,reference_high,abnormal_flag,evidence,page,bbox_json,confidence,reviewed,payload_json)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """, (report_id, *(item.get(field) for field in EXTRACTION_FIELDS)))
                    con.execute('UPDATE extractions SET sort_order=? WHERE id=last_insert_rowid()',(position,))
            con.execute("""INSERT INTO transfer_imports(batch_id,imported_at,report_count) VALUES(?,?,?)
                           ON CONFLICT(batch_id) DO UPDATE SET imported_at=excluded.imported_at, report_count=excluded.report_count""",
                        (str(manifest["batch_id"]), now_iso(), len(manifest["reports"])))
    return ImportResult(imported=imported, replaced=replaced, skipped=skipped)
