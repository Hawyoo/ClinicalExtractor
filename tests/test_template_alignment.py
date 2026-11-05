from copy import deepcopy
from clinical_extractor.report_templates import apply_table_template


def test_fixed_fields_identify_unknown_names_and_normalize_units():
    rows = [
        dict(item_original='乱码一', reference_low='39', reference_high='53.6', unit='f', value='36.9'),
        dict(item_original='乱码二', reference_low='11.9', reference_high='15.0', unit='%6', value='12.2'),
        dict(item_original='乱码三', reference_low='0.4', reference_high='8.0', unit='%6', value='2.20'),
        dict(item_original='白细胞计数', reference_low='3.5', reference_high='9.5', unit='10^9/L', value='200'),
    ]
    output = apply_table_template(deepcopy(rows), 'cbc')
    assert [r['item_standard'] for r in output] == ['RDW-SD','RDW-CV','EOS%','WBC']
    assert [r['unit'] for r in output] == ['fL','%','%','10^9/L']
    assert [r['value'] for r in output] == ['36.9','12.2','2.20','200']
    assert all(r['payload_json']['template_match']['reference_match'] for r in output)
    reversed_output = apply_table_template(deepcopy(rows[::-1]), 'cbc')
    assert [r['item_standard'] for r in reversed_output] == ['WBC','EOS%','RDW-CV','RDW-SD']
    rows[0]['value'] = '9999'
    assert apply_table_template(rows, 'cbc')[0]['item_standard'] == 'RDW-SD'


def test_duplicate_and_conflicting_rows_are_not_forced():
    duplicate = dict(item_original='白细胞计数', reference_low='3.5', reference_high='9.5',unit='10^9/L',value='5')
    result = apply_table_template([deepcopy(duplicate),deepcopy(duplicate)], 'cbc')
    assert all('template_warning' in r['payload_json'] for r in result)
    conflict = dict(item_original='白细胞计数',reference_low='130',reference_high='175',unit='10^9/L',value='5')
    result = apply_table_template([conflict], 'cbc')
    assert 'template_warning' in result[0]['payload_json']


def test_missing_row_does_not_shift_other_results():
    rows = [dict(item_original='WBC',unit='10^9/L',value='5'),
            dict(item_original='PLT',unit='10^9/L',value='200')]
    result = apply_table_template(rows,'cbc')
    assert [(r['item_standard'],r['value']) for r in result] == [('WBC','5'),('PLT','200')]
