from clinical_extractor.report_templates import apply_table_template, table_templates
from clinical_extractor.normalizer import chinese_item_name, item_abbreviation


def test_liver_subset_and_extra_item_are_preserved():
    rows = [
        dict(item_original='谷丙转氨酶', value='18', unit='IU/L', reference_low='7',reference_high='40'),
        dict(item_original='血肌酐', value='68', unit='umol/L',reference_low='41',reference_high='81'),
        dict(item_original='C反应蛋白', item_standard='C反应蛋白',value='2',unit='mg/L',reference_low='0',reference_high='10'),
    ]
    result = apply_table_template(rows, 'all')
    assert len(result) == 3
    assert [r['value'] for r in result] == ['18','68','2']
    assert [r['item_standard'] for r in result] == ['ALT','CREA','C反应蛋白']
    assert chinese_item_name(result[0]) == '谷丙转氨酶'
    assert item_abbreviation(result[1]) == 'CREA'
    assert result[2]['item_original'] == 'C反应蛋白'


def test_ui_names_use_template_wording_not_english_codes():
    assert chinese_item_name({'item_standard':'ALT'}) == '谷丙转氨酶'
    assert chinese_item_name({'item_standard':'DBIL'}) == '直接胆红素'
    assert chinese_item_name({'item_standard':'MCH'}) == '平均RBC血红蛋白含量'
    assert item_abbreviation({'item_standard':'ALT'}) == 'ALT'


def test_single_sided_ranges_and_unitless_ratio():
    rows = [
        dict(item_original='总胆红素',value='10',unit='umol/L',payload_json={'reference_raw':'<23'}),
        dict(item_original='白/球比值',value='1.6',unit='',reference_low='1.2',reference_high='2.4'),
    ]
    result = apply_table_template(rows,'all')
    assert result[0]['payload_json']['template_match']['reference_match']
    assert result[0]['unit'] == 'umol/L'
    assert result[1]['item_standard'] == 'A/G'
    assert 'unit_warning' not in result[1]['payload_json']


def test_partial_templates_accept_range_variation_without_overwriting():
    rows = [dict(item_original='血肌酐',value='80',unit='umol/L',reference_low='50',reference_high='100')]
    result = apply_table_template(rows,'all')
    assert result[0]['item_standard'] == 'CREA'
    assert (result[0]['reference_low'],result[0]['reference_high']) == ('50','100')
    assert 'template_warning' in result[0]['payload_json']
    assert all(t.get('coverage') == 'partial' for t in table_templates().values())
    assert 'source' not in table_templates()['all']
    catalog = table_templates()
    assert set(catalog)=={'all'}
    assert item_abbreviation({'item_standard':'CK-ISO'}) == ''
def test_template_micro_units_are_ascii_and_ocr_variants_remain_accepted():
    from clinical_extractor.report_templates import table_templates, apply_table_template
    from clinical_extractor.config import PROFILE_DIR
    catalog = table_templates()
    for path in PROFILE_DIR.rglob('*.yaml'):
        content = path.read_text(encoding='utf-8')
        assert '\u03bc' not in content and '\u00b5' not in content
    units = {item['code']:item.get('expected_unit') for item in catalog['all']['items']}
    assert units['HCY'] == 'umol/L'
    assert units['TC'] == 'mmol/L'
    for unit in ('umol/L', '\u03bcmol/L', '\u00b5mol/l'):
        record = apply_table_template([dict(item_original='同型半胱氨酸',value='8.2',unit=unit)], 'all')[0]
        assert record['unit'] == 'umol/L'
        assert record['value'] == '8.2'


def test_cbc_reference_variants_preserve_report_bounds_and_retire_old_warning():
    import json
    from clinical_extractor.report_templates import refresh_reference_warning
    from clinical_extractor.review import attention_for
    for code,name,value,unit,ranges in [
        ('RBC','红细胞计数','3.64','10^12/L',['4.3-5.8','3.8-5.1','3.80-5.10']),
        ('HGB','血红蛋白浓度','119','g/L',['130-175','115-150']),
        ('HCT','红细胞比容','34.1','%',['40-50','35.0-45.0','35-45']),
    ]:
        for reference in ranges:
            low,high = reference.split('-')
            record = dict(item_original=name,value=value,unit=unit,reference_low=low,reference_high=high)
            result = apply_table_template([record],'all')[0]
            assert result['item_standard'] == code
            assert result['value'] == value
            assert (result['reference_low'],result['reference_high']) == (low,high)
            assert result['payload_json']['template_match']['reference_match']
            assert 'template_warning' not in result['payload_json']
        legacy = dict(item_standard=code,reference_low=low,reference_high=high,
                      payload_json=json.dumps({'template_warning':'项目名称明确，但报告参考范围与参考模板不同；保留报告原范围，请核对'}))
        refresh_reference_warning(legacy,'all')
        assert not attention_for(legacy)['visible']


def test_reapplying_cbc_template_clears_obsolete_warning_without_touching_result():
    import json
    from clinical_extractor.report_templates import refresh_reference_warning
    warning='项目名称明确，但报告参考范围与参考模板不同；保留报告原范围，请核对'
    for name,code,value,reference,unit in [('红细胞计数','RBC','3.77','3.80-5.10','10^12/L'),
                                         ('血红蛋白浓度','HGB','113','115-150','g/L'),
                                         ('红细胞比容','HCT','36.4','35-45','%')]:
        record=dict(item_original=name,item_standard=code,value=value,unit=unit,
                    payload_json={'reference_raw':reference,'template_warning':warning})
        result=apply_table_template([record],'all')[0]
        assert result['value']==value and result['item_standard']==code
        assert 'template_warning' not in result['payload_json']
        legacy=dict(item_standard=code,value=value,payload_json=json.dumps({'reference_raw':reference,'template_warning':warning}))
        refresh_reference_warning(legacy,'all')
        assert 'template_warning' not in legacy['payload_json']


def test_liver_added_names_and_reference_variants_match_without_changing_values():
    definitions = [
        ('白球','1.74','','1.2-2.4','A/G'),
        ('谷酰转移酶','53.00','U/L','10-60','GGT'),
        ('尿素氮','5.20','mmol/L','3.1-9.5','BUN'),
        ('二氧化碳结合力','24.4','mmol/L','20.0-31.0','CO2CP'),
        ('直接胆红素','3.10','umol/L','<8','DBIL'),
        ('间接胆红素','6.30','umol/L','<15','IBIL'),
        ('谷丙转氨酶','28.30','','9-50','ALT'),
        ('谷草转氨酶','19.20','','15-40','AST'),
        ('碱性磷酸酶','65','','45-125','ALP'),
        ('肌酐','80.00','umol/L','57-111','CREA'),
    ]
    records = [dict(item_original=name,value=value,unit=unit,payload_json={'reference_raw':reference})
               for name,value,unit,reference,code in definitions]
    result = apply_table_template(records,'all')
    assert [r['item_standard'] for r in result] == [d[4] for d in definitions]
    assert [r['value'] for r in result] == [d[1] for d in definitions]
    assert all('template_warning' not in r['payload_json'] for r in result)
    assert all(r['payload_json']['template_match']['reference_match'] for r in result)
    assert chinese_item_name(result[0]) == '白/球比值'
    assert chinese_item_name(result[2]) == '尿素氮'
    assert chinese_item_name(result[3]) == '二氧化碳结合力'


def test_related_liver_items_remain_separate_template_entries():
    definitions = [('尿素','2.6-8.8','UREA'),('尿素氮','3.1-9.5','BUN'),
                   ('碳酸氢根','20-31','HCO3'),('二氧化碳结合力','20.0-31.0','CO2CP')]
    result = apply_table_template([dict(item_original=name,value='5.20',unit='mmol/L',
                                      payload_json={'reference_raw':reference})
                                   for name,reference,code in definitions],'all')
    assert [r['item_standard'] for r in result] == [d[2] for d in definitions]
    assert len(result)==4

