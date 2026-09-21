from clinical_extractor.table_extractor import extract_table_rows
from clinical_extractor.parser import TableBlock
from clinical_extractor.normalizer import normalize_item

def test_table_extractor():
    b = TableBlock(page=0, html="", rows=[["项目","结果","单位","参考范围"],["ALT","58↑","U/L","7-40"],["AST","32","U/L","13-35"]])
    out = extract_table_rows(b)
    assert len(out) == 2
    assert out[0]["item_original"] == "ALT"
    assert out[0]["value_num"] == 58
    assert out[0]["abnormal_flag"] == "高"
    assert out[0]["reference_low"] == "7"
    assert out[0]["reference_high"] == "40"

def test_normalize():
    assert normalize_item("白细胞计数") == "WBC"
    assert normalize_item("Ki-67") == "Ki-67"
