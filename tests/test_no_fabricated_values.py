import json
from types import SimpleNamespace
import pytest
from clinical_extractor.grounding import value_is_grounded, ungrounded_legacy_ai
from clinical_extractor.parser import TableBlock
from clinical_extractor.table_extractor import extract_table_rows


def test_names_and_other_numeric_fields_are_not_results():
    assert not value_is_grounded('5.20','白细胞计数','白细胞计数','10^9/L')
    assert not value_is_grounded('67','Ki-67','Ki-67','')
    assert not value_is_grounded('9','WBC 10^9/L','WBC','10^9/L')
    assert not value_is_grounded('5','WBC 15','WBC','')
    assert not value_is_grounded('3.5','白细胞计数 参考范围3.5-9.5','白细胞计数','')
    assert value_is_grounded('13.5','HGB 13.5 g/L','HGB','g/L')


def test_current_result_column_never_uses_history_or_reference():
    block=TableBlock(page=0,html='',rows=[['项目名称','历史结果','结果','参考值','单位'],
                                         ['白细胞计数','7.8','','3.5-9.5','10^9/L'],
                                         ['红细胞计数','9.9','4.3','4.3-5.8','10^12/L']])
    rows=extract_table_rows(block)
    assert [(r['item_original'],r['value']) for r in rows] == [('红细胞计数','4.3')]
    assert not extract_table_rows(TableBlock(page=0,html='',rows=[['项目名称','历史结果'],['白细胞计数','8']]))


def test_table_ai_cannot_write_a_generated_value(monkeypatch):
    from clinical_extractor import table_ai,text_extractor
    fake=SimpleNamespace(infer=lambda prompts: iter([[SimpleNamespace(output=json.dumps({
        'matches':[{'row_id':'0','code':'WBC','reason':'name matches','value':'999'}]}))]]))
    monkeypatch.setattr(text_extractor,'_progress_model',lambda settings:fake)
    monkeypatch.setattr(table_ai,'load_settings',lambda:SimpleNamespace(mock_mode=False))
    rows=[dict(item_original='白细胞计数',value='5.1',unit='10^9/L',payload_json={})]
    result=table_ai.correct_names(rows,'cbc')
    assert result[0]['value']=='5.1'
    assert not result[0]['payload_json'].get('ai_template_code')
    assert rows[0]['value']=='5.1'


def test_table_with_only_names_stops_before_ai(tmp_path,monkeypatch):
    from clinical_extractor import db,service
    monkeypatch.setattr(db,'DB_PATH',tmp_path/'test.sqlite3')
    db.init_db()
    with db.connect() as con:
        rid=con.execute('''INSERT INTO reports(profile,filename,file_path,created_at,raw_text,parser_json,template_id)
                           VALUES(?,?,?,?,?,?,?)''',('表格式报告','a.png','a.png',db.now_iso(),
                                                    '白细胞计数\n红细胞计数','[{}]','cbc')).lastrowid
    with pytest.raises(ValueError,match='不能根据项目名单'):
        service.process_report(rid,'llm')
    with db.connect() as con:
        assert con.execute('SELECT COUNT(*) FROM extractions').fetchone()[0]==0


def test_old_unverified_ai_table_results_are_not_exportable():
    record=dict(profile='表格式报告',source_kind='text',value='5.2',evidence='白细胞计数',
                item_original='白细胞计数',unit='10^9/L',payload_json={'char_start':0})
    assert ungrounded_legacy_ai(record)
    record['payload_json']['manual_value_verified']=True
    assert not ungrounded_legacy_ai(record)
