"""Rules shared by OCR, AI, review and export: headers are never analytes."""
import json
import re
import unicodedata

HEADER_NAMES = {
    '项目名称','项目','检验项目','检测项目','检查项目','指标名称','名称',
    '结果','本次结果','检测结果','检验结果','历史结果','参考值','参考范围','正常范围',
    '单位','序号','编号','异常','提示','标志',
    'item','itemname','test','testname','result','value','unit','reference','range','no.',
}


def is_header_name(name):
    text = unicodedata.normalize('NFKC',str(name or '')).casefold()
    text = re.sub(r'\([^)]*\)', '', text)
    text = re.sub(r'[\s:：|｜*＊]+', '', text).strip()
    return text in HEADER_NAMES


def is_header_record(record):
    if any(is_header_name(record.get(field)) for field in ('item_original','item_standard')):
        return True
    payload = record.get('payload_json') or {}
    if isinstance(payload,str):
        try:
            payload = json.loads(payload)
        except (ValueError,TypeError):
            payload = {}
    return isinstance(payload,dict) and is_header_name(payload.get('display_name'))
