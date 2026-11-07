
import pytest
from fastapi.testclient import TestClient

from clinical_extractor import config, db, main, exporter
from clinical_extractor.report_templates import table_templates, apply_table_template
from clinical_extractor.template_editor import catalog_data, custom_path


@pytest.fixture
def template_client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DATA_DIR', tmp_path/'shared-data')
    monkeypatch.setattr(config, 'DB_PATH', tmp_path/'report.sqlite3')
    db.init_db()
    with db.connect() as con:
        rid = con.execute('''INSERT INTO reports(filename,file_path,status,created_at,template_id)
                             VALUES(?,?,?,?,?)''', ('sample.png','sample.png','已审核',db.now_iso(),'all')).lastrowid
        con.execute('''INSERT INTO extractions(report_id,item_original,item_standard,value,unit,reviewed,payload_json)
                       VALUES(?,?,?,?,?,?,?)''', (rid,'胱抑素C','CysC','0.60','mg/L',1,'{"template_match":{}}'))
    with TestClient(main.app) as client:
        yield client, rid


def form(client, **patch):
    value = dict(target_code='CysC',display_name='胱抑素C（新展示）', aliases='胱抑素c\n新兼容名称\nCystatin C',
                 abbreviation='CYSNEW', reference_ranges='0.50-1.03\n0.60-1.10',
                 unit='mg/L',alternative_units='MG/L',section='自定义分区',
                 expected_revision=client.get('/templates/catalog').json()['revision'])
    value.update(patch)
    return value


def test_base_sections_and_editor_selector_are_available_without_row_links(template_client):
    client, rid = template_client
    data = client.get('/templates/catalog').json()
    by_code = {item['code']:item for item in data['items']}
    assert by_code['RBC']['section'] == '血常规'
    assert by_code['CREA']['section'] == '肾功能'
    page = client.get(f'/report/{rid}').text
    assert 'id="template-editor"' in page
    assert 'data-edit-template' not in page
    assert 'id="template-item-select"' in page
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(page, 'html.parser')
    assert soup.select_one('select[name=section]')
    assert soup.select_one('#new-template-section')
    assert not soup.select_one('[name=english_name]')


def test_edit_updates_matching_export_and_section_but_not_reports_or_reviews(template_client):
    client, rid = template_client
    with db.connect() as con:
        before = [dict(r) for r in con.execute('SELECT * FROM extractions')]
        report_before = [dict(r) for r in con.execute('SELECT * FROM reports')]
    result = client.post('/templates/items',data=form(client))
    assert result.status_code == 200, result.text
    assert result.json()['saved']
    item = next(x for x in table_templates()['all']['items'] if x['code']=='CysC')
    assert item['section'] == '自定义分区'
    assert item['abbreviation'] == 'CYSNEW' and 'Cystatin C' in item['aliases']
    assert 'english_name' not in item
    for name in ('新兼容名称','CYSNEW','Cystatin C','胱抑素C（新展示）'):
        matched = apply_table_template([dict(item_original=name,value='9.99',unit='mg/L',
                                             payload_json={'reference_raw':'0.60-1.10'})],'all')[0]
        assert matched['item_standard'] == 'CysC'
        assert matched['value'] == '9.99'
        assert matched['payload_json']['template_match']['reference_match']
    exported = exporter.dataframe().iloc[0]
    assert exported['item_name'] == '胱抑素C（新展示）'
    assert exported['item_abbr'] == 'CYSNEW'
    with db.connect() as con:
        assert before == [dict(r) for r in con.execute('SELECT * FROM extractions')]
        assert report_before == [dict(r) for r in con.execute('SELECT * FROM reports')]
    assert custom_path().is_file()


def test_new_indicator_and_new_section_are_durable_and_shared(template_client, tmp_path, monkeypatch):
    client, _ = template_client
    result = client.post('/templates/items',data=form(client,target_code='',abbreviation='TESTNEW',
                                                      display_name='测试新增指标',aliases='新指标',section='新分区'))
    assert result.status_code == 200
    assert '新分区' in result.json()['sections']
    assert result.json()['item']['code'] == 'TESTNEW'
    content = custom_path().read_bytes()
    monkeypatch.setattr(config, 'PROJECT_DIR', tmp_path/'another-project')
    assert next(x for x in catalog_data()['items'] if x['code']=='TESTNEW')['display_name'] == '测试新增指标'
    assert custom_path().read_bytes() == content


def test_stale_save_invalid_range_duplicate_code_and_header_never_overwrite(template_client):
    client, _ = template_client
    first = form(client)
    assert client.post('/templates/items',data=first).status_code == 200
    old = custom_path().read_bytes()
    assert client.post('/templates/items',data=first).status_code == 422
    for patch in [dict(reference_ranges='abc'),dict(reference_ranges='9-3'),dict(display_name='项目名称'),
                  dict(abbreviation='has spaces'),dict(target_code='',abbreviation='WBC')]:
        assert client.post('/templates/items',data=form(client,**patch)).status_code == 422
        assert custom_path().read_bytes() == old


def test_edit_preserves_discriminators_and_keeps_backup(template_client):
    client, _ = template_client
    base = next(x for x in table_templates()['all']['items'] if x['code']=='eGFR-EPI')
    payload = form(client,target_code='eGFR-EPI',display_name='eGFR-EPI',aliases='eGFR-EPI(eGFR-EPI)',
                   abbreviation='eGFR-EPI',reference_ranges='>90',
                   unit='mL/min/1.73m²',alternative_units='',section='肾功能')
    assert client.post('/templates/items',data=payload).status_code == 200
    current = next(x for x in table_templates()['all']['items'] if x['code']=='eGFR-EPI')
    assert current['required_name_terms'] == base['required_name_terms']
    assert current['expected_unit'] == 'mL/min/1.73m^2'
    assert client.post('/templates/items',data=form(client)).status_code == 200
    assert len(list((custom_path().parent/'history').glob('*.yaml'))) == 1


def test_new_empty_section_is_persistent_and_catalog_is_live(template_client):
    client, _ = template_client
    original = client.get('/templates/catalog').json()
    response = client.post('/templates/sections',data={'section':'新建空分类','expected_revision':original['revision']})
    assert response.status_code == 200
    current = client.get('/templates/catalog').json()
    assert '新建空分类' in current['sections']
    assert len(current['items']) == len(original['items'])
    assert current['revision'] != original['revision']
    assert client.post('/templates/sections',data={'section':'新建空分类','expected_revision':current['revision']}).status_code == 422
    assert client.post('/templates/items',data=form(client,section='新建空分类')).status_code == 200
    assert next(x for x in client.get('/templates/catalog').json()['items'] if x['code']=='CysC')['section'] == '新建空分类'


def test_previous_english_name_becomes_alias_without_losing_it(template_client):
    client, _ = template_client
    import yaml
    path = custom_path()
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump({'version':1,'items':[{
        'code':'CysC','english_name':'Cystatin C','aliases':['胱抑素c']}]}),encoding='utf-8')
    item = next(x for x in client.get('/templates/catalog').json()['items'] if x['code']=='CysC')
    assert 'english_name' not in item
    assert 'Cystatin C' in item['aliases']
    result = apply_table_template([dict(item_original='Cystatin C',value='0.60',unit='mg/L')],'all')[0]
    assert result['item_standard'] == 'CysC'
