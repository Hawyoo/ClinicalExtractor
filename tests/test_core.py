from clinical_extractor.table_extractor import extract_table_rows
from clinical_extractor.parser import TableBlock
from clinical_extractor.normalizer import normalize_item
from clinical_extractor.date_extractor import extract_report_date
from clinical_extractor import db, transfer
from pathlib import Path
import pytest

def test_table_extractor():
    b = TableBlock(page=0, html="", rows=[["项目","结果","单位","参考范围"],["ALT","58↑","U/L","7-40"],["AST","32","U/L","13-35"]])
    out = extract_table_rows(b)
    assert len(out) == 2
    assert out[0]["item_original"] == "ALT"
    assert out[0]["value_num"] == 58
    assert out[0]["abnormal_flag"] == "高"
    assert out[0]["reference_low"] == "7"
    assert out[0]["reference_high"] == "40"

def test_normalize():
    assert normalize_item("白细胞计数") == "WBC"
    assert normalize_item("Ki-67") == "Ki-67"

def test_report_date_extraction():
    assert extract_report_date("报告日期：2026年9月21日") == "2026-09-21"
    assert extract_report_date("检查日期 2026/09/03") == "2026-09-03"
    assert extract_report_date("no report date") == ""


def test_ocr_transfer_round_trip_and_duplicate_guard(tmp_path, monkeypatch):
    source_data = tmp_path / "source"
    source_uploads = source_data / "uploads"
    source_uploads.mkdir(parents=True)
    source_file = source_uploads / "a_report.txt"
    source_file.write_text("OCR text", encoding="utf-8")
    monkeypatch.setattr(db, "DB_PATH", source_data / "clinical_extractor.sqlite3")
    monkeypatch.setattr(transfer, "UPLOAD_DIR", source_uploads)
    db.init_db()
    with db.connect() as con:
        con.execute("""INSERT INTO reports(patient_id,report_date,report_type,profile,filename,file_path,status,raw_text,parser_json,error,transfer_key,created_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    ("P1", "2026-09-22", "", "长文本报告", "report.txt", str(source_file), "OCR已完成", "OCR text", "[]", "", "report-stable-key", db.now_iso()))
    package = tmp_path / "batch.ceocr"
    assert transfer.create_ocr_transfer(package) == 1

    target_data = tmp_path / "target"
    target_uploads = target_data / "uploads"
    target_uploads.mkdir(parents=True)
    monkeypatch.setattr(db, "DB_PATH", target_data / "clinical_extractor.sqlite3")
    monkeypatch.setattr(transfer, "UPLOAD_DIR", target_uploads)
    db.init_db()
    result = transfer.import_ocr_transfer(package)
    assert (result.imported, result.replaced, result.skipped) == (1, 0, 0)
    with db.connect() as con:
        report = con.execute("SELECT * FROM reports").fetchone()
    assert report["status"] == "OCR已完成"
    assert report["raw_text"] == "OCR text"
    assert (target_uploads / Path(report["file_path"]).name).exists()
    assert len(transfer.inspect_ocr_transfer(package)["conflicts"]) == 1
    result = transfer.import_ocr_transfer(package)
    assert (result.imported, result.replaced, result.skipped) == (0, 0, 1)
    result = transfer.import_ocr_transfer(package, {"report-stable-key"})
    assert (result.imported, result.replaced, result.skipped) == (0, 1, 0)
