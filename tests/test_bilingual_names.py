from copy import deepcopy

from clinical_extractor.report_templates import apply_table_template


def test_bilingual_names_missing_brackets_and_row_numbers_preserve_source_values():
    cases = [
        ('白蛋白（ALB）', 'ALB', 'g/L', '35-55'),
        ('球蛋白（G1b）', 'GLB', 'g/L', '20-40'),
        ('11谷酰转肽酶（R-GT）', 'GGT', 'U/L', '10-60'),
        ('14前白蛋白（P-ALB）', 'PA', 'mg/L', '200-400'),
        ('20 eGFR-EPI(eGFR-EPI)', 'eGFR-EPI', 'mL/min/1.73m²', '>90'),
        ('22胱抑素C(CysC)', 'CysC', 'mg/L', '0.50-1.03'),
        ('23补体C1q(C1q)', 'C1q', 'mg/dL', '15.7-23.7'),
        ('26高密度脂蛋白（HDLC', 'HDL-C', 'mmol/L', '1.04-1.55'),
        ('白蛋白ALB）', 'ALB', 'g/L', '35-55'),
        ('40钾（K)', 'K', 'mmol/L', '3.5-5.3'),
        ('45糖化白蛋白（GA-L）', 'GA', '%', '11-16'),
        ('2 直接胆红素（贝克曼）（BIL）', 'DBIL', 'umol/L', '<4'),
    ]
    for name, code, unit, reference in cases:
        source = dict(item_original=name, value='11.40', unit=unit,
                      evidence=f'{name} | 11.40 | {reference} | {unit}',
                      payload_json={'reference_raw': reference})
        result = apply_table_template([deepcopy(source)], 'all')[0]
        assert result['item_standard'] == code
        assert result['value'] == source['value']
        assert result['evidence'] == source['evidence']
        assert result['payload_json']['reference_raw'] == reference
        assert 'template_warning' not in result['payload_json']
        assert 'item_correction' not in result['payload_json']


def test_actual_name_damage_still_requires_correction_attention():
    for name, code, reference in [('15胆碱酷酶（CHE）', 'CHE', '5000-12000'),
                                  ('37一氧化氨（NO）', 'NO', '30-60')]:
        row = dict(item_original=name, value='39', unit='', payload_json={'reference_raw': reference})
        result = apply_table_template([row], 'all')[0]
        assert result['item_standard'] == code
        assert result['value'] == '39'
        assert result['payload_json']['item_correction']


def test_distinct_analytes_remain_distinct_in_bilingual_partial_report():
    names = [('18尿素（UREA）', 'UREA', '3.1-9.5'),
             ('尿素氮（BUN）', 'BUN', '3.1-9.5'),
             ('42碳酸氢根（C02）', 'HCO3', '20-31'),
             ('二氧化碳结合力（CO2CP', 'CO2CP', '20-31')]
    rows = [dict(item_original=name, value=str(i + 1), unit='mmol/L',
                 payload_json={'reference_raw': reference}) for i, (name, _, reference) in enumerate(names)]
    result = apply_table_template(rows, 'all')
    assert [row['item_standard'] for row in result] == [code for _, code, _ in names]
    assert [row['value'] for row in result] == ['1', '2', '3', '4']


def test_egfr_and_epi_remain_independent_with_identical_ranges_units_and_values():
    from clinical_extractor.normalizer import chinese_item_name
    for names in [('19 eGFR(eGFR)', '20 eGFR-EPI(eGFR-EPI)'),
                  ('eGFR（eGFR', 'eGFR-EPI（eGFR-EPI'),
                  ('估算肾小球滤过率', '估算肾小球滤过率（EPI）')]:
        rows=[dict(item_original=name,value='73.14',unit='ml/min/1.73m"2',
                   payload_json={'reference_raw':'>90'}) for name in names]
        result=apply_table_template(rows,'all')
        assert [r['item_standard'] for r in result]==['eGFR','eGFR-EPI']
        assert [chinese_item_name(r) for r in result]==['eGFR','eGFR-EPI']
        assert [r['value'] for r in result]==['73.14','73.14']
        for row in result:
            assert not row['payload_json'].get('template_warning')
            assert not row['payload_json'].get('unit_warning')
        # A partial report or an incorrect model hint must not select the other method.
        for row,expected,wrong in zip(rows,['eGFR','eGFR-EPI'],['eGFR-EPI','eGFR']):
            row['payload_json']['ai_template_code']=wrong
            assert apply_table_template([row],'all')[0]['item_standard']==expected
