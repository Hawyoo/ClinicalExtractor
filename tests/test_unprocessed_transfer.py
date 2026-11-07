from clinical_extractor import config
from pathlib import Path
import pytest

from clinical_extractor import db,transfer


@pytest.mark.parametrize('status',['未处理','OCR排队中','OCR处理中'])
def test_images_without_ocr_are_exported_appended_and_not_reimported(tmp_path,monkeypatch,status):
    source=tmp_path/'source';source.mkdir()
    monkeypatch.setattr(config, 'DB_PATH',source/'reports.sqlite3')
    monkeypatch.setattr(config, 'UPLOAD_DIR',source)
    image=source/'only-image.png';image.write_bytes(b'original image data')
    db.init_db()
    with db.connect() as con:
        con.execute('''INSERT INTO reports(patient_id,filename,file_path,profile,status,transfer_key,created_at)
                       VALUES(?,?,?,?,?,?,?)''',('patient1','only-image.png',str(image),'表格式报告',status,'image-only-key',db.now_iso()))
    package=tmp_path/'images.ceocr'
    assert transfer.create_transfer(package)==1
    target=tmp_path/'target';target.mkdir()
    monkeypatch.setattr(config, 'DB_PATH',target/'reports.sqlite3')
    monkeypatch.setattr(config, 'UPLOAD_DIR',target)
    db.init_db()
    with db.connect() as con:
        existing=con.execute('INSERT INTO reports(filename,file_path,status,created_at) VALUES(?,?,?,?)',
                             ('existing.png','existing.png','已审核',db.now_iso())).lastrowid
    imported=transfer.import_transfer(package)
    assert (imported.imported,imported.replaced,imported.skipped)==(1,0,0)
    with db.connect() as con:
        row=con.execute("SELECT * FROM reports WHERE transfer_key='image-only-key'").fetchone()
        assert row['status']=='未处理' and row['raw_text']=='' and row['patient_id']=='patient1'
        assert Path(row['file_path']).read_bytes()==image.read_bytes()
        assert con.execute('SELECT status FROM reports WHERE id=?',(existing,)).fetchone()[0]=='已审核'
    repeated=transfer.import_transfer(package)
    assert (repeated.imported,repeated.replaced,repeated.skipped)==(0,0,1)
