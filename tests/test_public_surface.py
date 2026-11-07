from dataclasses import fields
from types import SimpleNamespace
import sys


def test_only_current_product_entry_points_and_settings_are_exposed():
    from clinical_extractor import main,config,parser
    from clinical_extractor.report_templates import table_templates
    paths={r.path for r in main.app.routes}
    assert not paths & {'/ocr-pending','/llm-pending','/export/xlsx','/report/{report_id}/process'}
    assert {'/process-pending','/export/csv','/transfer/export','/transfer/import'}<=paths
    assert {f.name for f in fields(config.Settings)}=={'ollama_url','ollama_model','pp_device','ocr_cpu_threads','max_text_chars'}
    assert set(table_templates())=={'all'}
    assert hasattr(parser,'ReportParser') and not hasattr(parser,'PPStructureParser')


def test_long_text_uses_generic_profile_and_keeps_grounded_results(monkeypatch):
    from clinical_extractor import text_extractor
    from clinical_extractor.config import Settings
    text='白细胞计数 5.1 10^9/L'
    extraction=SimpleNamespace(extraction_class='clinical_result',extraction_text=text,
        attributes={'item':'白细胞计数','value':'5.1','unit':'10^9/L'},
        char_interval=SimpleNamespace(start_pos=0,end_pos=len(text)),alignment_status='exact')
    calls=[]
    def extract(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(extractions=[extraction])
    fake=SimpleNamespace(data=SimpleNamespace(Extraction=lambda **kw:SimpleNamespace(**kw),ExampleData=lambda **kw:SimpleNamespace(**kw)),extract=extract)
    monkeypatch.setitem(sys.modules,'langextract',fake)
    monkeypatch.setattr(text_extractor,'load_settings',lambda:Settings())
    monkeypatch.setattr(text_extractor,'_progress_model',lambda settings:object())
    rows=text_extractor.extract_text(text,page=0)
    assert len(rows)==1 and rows[0]['value']=='5.1' and rows[0]['evidence']==text
    assert calls[0]['max_workers']==1
