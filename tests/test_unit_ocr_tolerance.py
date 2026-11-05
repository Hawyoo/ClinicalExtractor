from clinical_extractor.report_templates import apply_table_template, fill_missing_template_unit
from clinical_extractor.review import attention_for
from clinical_extractor.table_extractor import _split_reference


def test_missing_square_and_m_n_unit_errors_do_not_require_a_reference_match():
    for name,code,raw,expected,value in [
        ('20 eGFR-EPI(eGFR-EPI)','eGFR-EPI','ml/min/1.73m','mL/min/1.73m²','92.19'),
        ('eGFR','eGFR','ml/min/1.73m"2','mL/min/1.73m²','73.14'),
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
    assert result['unit']=='mL/min/1.73m²'
    assert 'unit_warning' not in result['payload_json']
    assert 'template_warning' not in result['payload_json']
    assert result['payload_json']['reference_warning']


def test_unit_tolerance_does_not_change_concentration_prefix_or_damaged_area_value():
    for name,raw in [('总胆固醇','unol/L'),('eGFR','ml/min/1.7m')]:
        result=apply_table_template([dict(item_original=name,value='5',unit=raw)],'all')[0]
        assert result['unit']==raw
        assert result['payload_json']['unit_warning']
