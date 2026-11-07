from clinical_extractor import config
from fastapi.testclient import TestClient
from clinical_extractor import db, main, exporter
from clinical_extractor.result_rules import is_header_name, is_header_record
from clinical_extractor.service import _store_extractions


def test_headers_are_not_analytes_and_no_is_a_real_analyte():
    for name in ['项目名称',' 项 目 名 称：','项目名称（这一列不关注）','单位','参考值','Item Name']:
        assert is_header_name(name)
    assert not is_header_record({'item_original':'一氧化氮','item_standard':'NO'})
    assert not is_header_name('血小板体积分布宽度')


def test_storage_view_export_and_single_result_delete(tmp_path,monkeypatch):
    monkeypatch.setattr(config, 'DB_PATH',tmp_path/'data.sqlite3')
    db.init_db()
    original=tmp_path/'original.png';original.write_bytes(b'original image')
    with db.connect() as con:
        rid=con.execute('INSERT INTO reports(filename,file_path,created_at) VALUES(?,?,?)',
                        (original.name,str(original),db.now_iso())).lastrowid
        _store_extractions(con,rid,[dict(item_original='项目名称',item_standard='项目名称',value='结果'),
                                    dict(item_original='WBC',item_standard='WBC',value='5'),
                                    dict(item_original='误读项目',item_standard='误读项目',value='1')])
        assert con.execute('SELECT COUNT(*) FROM extractions').fetchone()[0]==2
        bad=con.execute('SELECT MAX(id) FROM extractions').fetchone()[0]
        # Legacy/package entries are excluded as well, not only newly parsed rows.
        con.execute('INSERT INTO extractions(report_id,item_original,item_standard,value) VALUES(?,?,?,?)',
                    (rid,'项目名称','项目名称','结果'))
    with TestClient(main.app) as client:
        html=client.get(f'/report/{rid}').text
        assert 'value="项目名称"' not in html
        assert '/static/review.js' in html
        assert f'/extraction/{bad}/delete' in html
        response=client.post(f'/extraction/{bad}/delete')
        assert response.status_code==200 and response.json()['deleted']
        assert not response.history
    assert original.exists()
    with db.connect() as con:
        assert con.execute('SELECT COUNT(*) FROM reports WHERE id=?',(rid,)).fetchone()[0]==1
        assert con.execute('SELECT COUNT(*) FROM extractions WHERE id=?',(bad,)).fetchone()[0]==0
    assert exporter.dataframe()['item_name'].tolist()==['白细胞计数']
