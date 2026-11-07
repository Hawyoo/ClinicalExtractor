from clinical_extractor import config
from clinical_extractor.report_templates import apply_table_template, fill_missing_template_unit, ascii_unit, refresh_reference_warning
from clinical_extractor.review import attention_for
from clinical_extractor.table_extractor import _split_reference


def test_missing_square_and_m_n_unit_errors_do_not_require_a_reference_match():
    for name,code,raw,expected,value in [
        ('20 eGFR-EPI(eGFR-EPI)','eGFR-EPI','ml/min/1.73m','mL/min/1.73m^2','92.19'),
        ('eGFR','eGFR','ml/min/1.73m"2','mL/min/1.73m^2','73.14'),
        ('21尿酸（URIC）','UA','unol/L','umol/L','373'),
        ('总胆固醇','TC','mnol/1','mmol/L','3.65')]:
        row=dict(item_original=name,value=value,unit=raw,payload_json={})
        result=apply_table_template([row],'all')[0]
        assert (result['item_standard'],result['value'],result['unit'])==(code,value,expected)
        assert not attention_for(result)['visible']
        result['unit']=raw
        result['payload_json']['unit_warning']='old warning'
        fill_missing_template_unit(result,'all')
        assert result['unit']==expected
        assert not result['payload_json'].get('unit_warning')


def test_combined_reference_is_not_misread_as_only_the_next_rows_interval():
    row=dict(item_original='20 eGFR-EPI(eGFR-EPI)',value='92.19',unit='ml/min/1.73m',
             payload_json={'reference_raw':'>90 208-428'})
    result=apply_table_template([row],'all')[0]
    assert _split_reference('>90 208-428')==('','')
    assert result['item_standard']=='eGFR-EPI' and result['value']=='92.19'
    assert result['unit']=='mL/min/1.73m^2'
    assert 'unit_warning' not in result['payload_json']
    assert 'template_warning' not in result['payload_json']
    assert result['payload_json']['reference_warning']


def test_unit_tolerance_does_not_change_concentration_prefix_or_damaged_area_value():
    for name,raw in [('总胆固醇','unol/L'),('eGFR','ml/min/1.7m')]:
        result=apply_table_template([dict(item_original=name,value='5',unit=raw)],'all')[0]
        assert result['unit']==raw
        assert result['payload_json']['unit_warning']


def test_exponents_use_ascii_carets_in_current_and_previously_saved_units():
    for raw, expected in [('10⁹/L','10^9/L'), ('10¹²/L','10^12/L'),
                          ('mL/min/1.73m²','mL/min/1.73m^2'),
                          ('10^12/L','10^12/L')]:
        assert ascii_unit(raw) == expected
    for name in ('eGFR', 'eGFR-EPI'):
        for raw in ('mL/min/1.73m²','ml/min/1.73m2','ml/min/1.73m^2',
                    'ml/min/1.73m','ml/min/1.73m"2',''):
            record = apply_table_template([dict(item_original=name, value='92.19', unit=raw)], 'all')[0]
            assert record['unit'] == 'mL/min/1.73m^2'
            assert record['value'] == '92.19'
            record['unit'] = raw
            fill_missing_template_unit(record, 'all')
            assert record['unit'] == 'mL/min/1.73m^2'
    for name, raw, expected in [('白细胞计数','10⁹/L','10^9/L'), ('红细胞计数','10¹²/L','10^12/L')]:
        record = apply_table_template([dict(item_original=name, value='5', unit=raw)], 'all')[0]
        assert record['unit'] == expected


def test_stored_unit_migration_preserves_every_other_field_and_is_idempotent(tmp_path, monkeypatch):
    from clinical_extractor import db
    monkeypatch.setattr(config, 'DB_PATH', tmp_path/'units.sqlite3')
    db.init_db()
    with db.connect() as con:
        rid = con.execute("INSERT INTO reports(filename,file_path,status,created_at) VALUES('x','x','已审核',?)",
                          (db.now_iso(),)).lastrowid
        for code, unit, reviewed in [('eGFR','mL/min/1.73m²',1), ('eGFR-EPI','ml/min/1.73m2',0),
                                     ('RBC','10¹²/L',1), ('WBC','10⁹/L',0)]:
            con.execute('''INSERT INTO extractions(report_id,item_standard,value,unit,reviewed,evidence,payload_json)
                           VALUES(?,?,?,?,?,?,?)''', (rid,code,'1.11',unit,reviewed,'original evidence','{"note":"unchanged"}'))
        before = [dict(r) for r in con.execute('SELECT * FROM extractions ORDER BY id')]
        report_before = dict(con.execute('SELECT * FROM reports WHERE id=?',(rid,)).fetchone())
        assert db.normalize_stored_unit_powers(con) == 4
        after = [dict(r) for r in con.execute('SELECT * FROM extractions ORDER BY id')]
        assert [r['unit'] for r in after] == ['mL/min/1.73m^2','mL/min/1.73m^2','10^12/L','10^9/L']
        assert [{k:v for k,v in r.items() if k!='unit'} for r in before] == [
            {k:v for k,v in r.items() if k!='unit'} for r in after]
        assert dict(con.execute('SELECT * FROM reports WHERE id=?',(rid,)).fetchone()) == report_before
        assert db.normalize_stored_unit_powers(con) == 0


def test_successful_ratio_rematch_removes_stale_unmatched_warning_only():
    row = dict(item_original='白/球', value='1.18', unit='', reviewed=1,
               payload_json={'reference_raw':'1.2-2.4',
                             'template_warning':'模板外项目，或名称、参考范围与单位未能唯一对齐；保留原报告内容，请核对',
                             'ai_review_warning':'原文配对仍需核对'})
    record = apply_table_template([row], 'all')[0]
    assert record['item_standard'] == 'A/G'
    assert 'template_warning' not in record['payload_json']
    assert record['payload_json']['ai_review_warning'] == '原文配对仍需核对'
    assert record['value'] == '1.18' and record['reviewed'] == 1


def test_view_refreshes_old_alias_warning_without_reprocessing_or_changing_review():
    record = dict(item_original='白/球', item_standard='白/球', value='1.18', unit='', reviewed=1,
                  payload_json={'reference_raw':'1.2-2.4',
                                'template_warning':'模板外项目，或名称、参考范围与单位未能唯一对齐；保留原报告内容，请核对'})
    refresh_reference_warning(record, 'all')
    assert record['item_standard'] == 'A/G'
    assert not attention_for(record)['warnings']
    assert record['reviewed'] == 1 and record['value'] == '1.18'
