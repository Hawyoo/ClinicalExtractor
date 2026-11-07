"""AI can select a template name for a source row, never create result cells."""
from copy import deepcopy
import json
import re
from .config import load_settings
from .report_templates import table_templates, _candidate
from .jobs import emit


def correct_names(records, template_id):
    template = table_templates().get(template_id)
    if not template:
        emit('未选择模板，保留逐行 OCR 结果，不让 AI 生成数值')
        return records
    settings = load_settings()
    from .text_extractor import _progress_model
    model = _progress_model(settings)
    catalog = {item['code']:item for item in template['items']}
    output = deepcopy(records)
    for start in range(0,len(records),15):
        chunk = records[start:start+15]
        rows = [dict(row_id=str(start+i), name=r['item_original'], unit=r['unit'],
                     reference=r.get('payload_json',{}).get('reference_raw','')) for i,r in enumerate(chunk)]
        candidates = [item for item in template['items'] if any(_candidate(row,item) is not None for row in chunk)]
        if not candidates:
            continue
        prompt = ('独立识别本次图片的项目名称，不存在上一张图片或会话历史。'
                  '输入行已经由OCR按表格列恢复，结果值不交给你处理。'
                  '仅结合名称字形、单位与参考范围，在模板内选择项目代码。'
                  '模板可能不完整，不补齐；不能唯一确定或属于模板外则不返回该行。'
                  '同一代码不得对应多行。仅返回JSON对象：'
                  '{"matches":[{"row_id":"输入行ID","code":"模板代码"}]}。'
                  '严禁返回或生成value/result等数值字段。候选指标库：' + json.dumps(candidates,ensure_ascii=False) +
                  '\n本次图片的候选行：' + json.dumps(rows,ensure_ascii=False))
        emit(f'AI 正在核对项目名称（第 {start+1}—{start+len(chunk)} 行）；数值保持 OCR 原值')
        batches = list(model.infer([prompt]))
        raw = batches[0][0].output if batches and batches[0] else ''
        try:
            cleaned = re.sub(r'^```(?:json)?\s*|\s*```$', '', str(raw).strip(),flags=re.IGNORECASE)
            matches = json.loads(cleaned).get('matches',[])
            if not isinstance(matches,list):
                raise ValueError('matches must be a list')
        except (ValueError,TypeError,AttributeError):
            raise RuntimeError('AI 名称核对响应无效，未保存任何生成数据')
        seen = set()
        for match in matches:
            if not isinstance(match,dict) or set(match)-{'row_id','code','reason'}:
                continue
            index = str(match.get('row_id',''))
            if index not in {r['row_id'] for r in rows} or index in seen:
                continue
            seen.add(index)
            definition = catalog.get(match.get('code'))
            candidate = _candidate(output[int(index)],definition) if definition else None
            if candidate is None:
                continue
            payload = output[int(index)].setdefault('payload_json',{})
            payload['ai_template_code'] = definition['code']
    return output
