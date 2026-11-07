from clinical_extractor import config
from clinical_extractor.table_extractor import extract_table_rows
from clinical_extractor.parser import TableBlock
from clinical_extractor.normalizer import normalize_item
from clinical_extractor import db, transfer
from pathlib import Path
import pytest

def test_cbc_contextual_units_keep_ocr_evidence():
    from clinical_extractor.report_templates import apply_table_template
    rows = [{'item_original': item, 'unit': unit, 'value': '130', 'evidence': 'raw evidence'}
            for item, unit in [('HGB', '9/l'), ('MCHC', 'g/l'), ('MCV', 'fl'),
                               ('WBC', '9/l'), ('PDW', '%'), ('HGB', '')]]
    out = [apply_table_template([row], 'all')[0] for row in rows]
    assert [r['unit'] for r in out] == ['g/L', 'g/L', 'fL', '9/l', '%', 'g/L']
    assert out[0]['payload_json']['unit_ocr_raw'] == '9/l'
    assert 'unit_correction' in out[0]['payload_json']
    assert 'unit_warning' in out[3]['payload_json']
    assert all(r['value'] == '130' and r['evidence'] == 'raw evidence' for r in out)


def test_cbc_fuzzy_names_preserve_original_and_cell_type():
    from clinical_extractor.report_templates import apply_table_template
    rows = [{'item_original': name, 'unit': unit} for name, unit in [
        ('哈碱拉细胞计数', '10^9/L'), ('嗜酸粒细胞计数', '10^9/L'),
        ('嗜碱粒细胞百分比', '%'), ('粒细胞计数', '10^9/L'), ('BAS', '')]]
    result = apply_table_template(rows, 'all')
    assert result[0]['item_standard'] == 'BASO#'
    assert result[0]['item_original'] == '哈碱拉细胞计数'
    assert 'item_correction' in result[0]['payload_json']
    assert result[1]['item_standard'] == 'EOS#'
    assert result[2]['item_standard'] == 'BASO%'
    assert 'item_standard' not in result[3]
    assert 'item_standard' not in result[4]


def test_cbc_unit_ocr_truncation_and_percent_suffix():
    from clinical_extractor.report_templates import apply_table_template
    rows = [{'item_original': name, 'unit': unit, 'value': '12.2'} for name, unit in [
        ('红细胞体积分布宽度SD', 'f'), ('红细胞体积分布宽度CV', '%6'),
        ('嗜酸粒细胞百分比', '%6'), ('平均红细胞体积', 'f1'),
        ('红细胞计数', 'f'), ('血红蛋白', '%6'), ('红细胞体积分布宽度SD', 'pg')]]
    result = [apply_table_template([row], 'all')[0] for row in rows]
    assert [r['unit'] for r in result] == ['fL', '%', '%', 'fL', 'f', '%6', 'pg']
    assert result[0]['payload_json']['unit_ocr_raw'] == 'f'
    assert result[1]['payload_json']['unit_ocr_raw'] == '%6'
    assert all(r['value'] == '12.2' for r in result)

def test_delete_report_removes_uploaded_copy_and_results(tmp_path, monkeypatch):
    from clinical_extractor import main
    monkeypatch.setattr(config, 'DB_PATH', tmp_path / "test.sqlite3")
    monkeypatch.setattr(config, 'UPLOAD_DIR', tmp_path)
    db.init_db()
    image = tmp_path / "report.jpg"
    image.write_bytes(b"test image")
    with db.connect() as con:
        rid = con.execute("INSERT INTO reports(filename,file_path,created_at) VALUES(?,?,?)",
                          (image.name, str(image), db.now_iso())).lastrowid
        con.execute("INSERT INTO extractions(report_id) VALUES(?)", (rid,))
    from starlette.requests import Request
    main.delete_report(rid, Request({'type':'http','headers':[]}))
    assert not image.exists()
    with db.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM reports").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM extractions").fetchone()[0] == 0

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



def test_ocr_transfer_round_trip_and_duplicate_guard(tmp_path, monkeypatch):
    source_data = tmp_path / "source"
    source_uploads = source_data / "uploads"
    source_uploads.mkdir(parents=True)
    source_file = source_uploads / "a_report.txt"
    source_file.write_text("OCR text", encoding="utf-8")
    monkeypatch.setattr(config, 'DB_PATH', source_data / "clinical_extractor.sqlite3")
    monkeypatch.setattr(config, 'UPLOAD_DIR', source_uploads)
    db.init_db()
    with db.connect() as con:
        con.execute("""INSERT INTO reports(patient_id,report_type,profile,filename,file_path,status,raw_text,parser_json,error,transfer_key,created_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    ("P1", "", "长文本报告", "report.txt", str(source_file), "OCR已完成", "OCR text", "[]", "", "report-stable-key", db.now_iso()))
    package = tmp_path / "batch.ceocr"
    assert transfer.create_transfer(package) == 1

    target_data = tmp_path / "target"
    target_uploads = target_data / "uploads"
    target_uploads.mkdir(parents=True)
    monkeypatch.setattr(config, 'DB_PATH', target_data / "clinical_extractor.sqlite3")
    monkeypatch.setattr(config, 'UPLOAD_DIR', target_uploads)
    db.init_db()
    result = transfer.import_transfer(package)
    assert (result.imported, result.replaced, result.skipped) == (1, 0, 0)
    with db.connect() as con:
        report = con.execute("SELECT * FROM reports").fetchone()
    assert report["status"] == "OCR已完成"
    assert report["raw_text"] == "OCR text"
    assert (target_uploads / Path(report["file_path"]).name).exists()
    assert len(transfer.inspect_transfer(package)["conflicts"]) == 1
    result = transfer.import_transfer(package)
    assert (result.imported, result.replaced, result.skipped) == (0, 0, 1)
    result = transfer.import_transfer(package, {"report-stable-key"})
    assert (result.imported, result.replaced, result.skipped) == (0, 1, 0)
