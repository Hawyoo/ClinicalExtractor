from __future__ import annotations
import json
import re
from .config import load_settings
from .profiles import load_profile
from .grounding import value_is_grounded

DEFAULT_EXAMPLE_TEXT = "免疫组化：ER约90%肿瘤细胞强阳性，PR约30%阳性，HER2（2+），Ki-67约40%。"
DEFAULT_EXAMPLE = [
    {"text": "ER约90%肿瘤细胞强阳性", "attributes": {"category": "免疫组化", "item": "ER", "value": "90%", "unit": "", "abnormal_flag": "阳性"}},
    {"text": "PR约30%阳性", "attributes": {"category": "免疫组化", "item": "PR", "value": "30%", "unit": "", "abnormal_flag": "阳性"}},
    {"text": "HER2（2+）", "attributes": {"category": "免疫组化", "item": "HER2", "value": "2+", "unit": "", "abnormal_flag": ""}},
    {"text": "Ki-67约40%", "attributes": {"category": "免疫组化", "item": "Ki-67", "value": "40%", "unit": "", "abnormal_flag": ""}},
]

def _num(s: str):
    m = re.search(r"-?\d+(?:\.\d+)?", s or "")
    return float(m.group()) if m else None

def extract_text(text: str, profile_id: str = "generic", page: int | None = None, template_id: str = ''):
    settings = load_settings()
    text = (text or "").strip()
    if not text:
        return []
    if settings.mock_mode:
        return []
    try:
        import langextract as lx
    except Exception as e:
        raise RuntimeError("未安装 LangExtract，请重新运行安装脚本。") from e

    profile = load_profile(profile_id)
    prompt = profile.get("prompt") or (
        "从临床检查、检验、病理或免疫组化文本中提取明确出现的结构化结果。"
        "只提取原文明确记载的信息，不推断、不补全。extraction_text必须逐字来自原文。"
        "每条结果使用 clinical_result 类，并在 attributes 中提供 category、item、value、unit、"
        "reference_low、reference_high、abnormal_flag。没有的信息用空字符串。"
    )
    from .report_templates import table_templates
    prompt += '\n只抽取检验/检查指标及结果，不提取报告日期、采样时间、审核时间等日期时间元数据。项目名称、检验项目、结果、历史结果、单位、参考值等是表头，绝不能作为clinical_result项目输出。'
    prompt += '\n本次输入是唯一数据来源。只允许解释项目名称，结果必须逐字复制本条extraction_text中的本次结果；不得计算、猜测、改写、补零或从模板、示例、参考范围、其他行和其他图片借用数值。只有项目名没有结果时，不输出该条clinical_result。'
    template = table_templates().get(template_id)
    if template:
        prompt += (
            '\n本报告套用“' + template['name'] + '”模板。候选项目定义：' +
            json.dumps(template['items'], ensure_ascii=False) +
            '\n按以下流程逐行识别，不依赖预先列出的错字替换表：'
            '模板是可能不完整的参考项目表，既不要求报告包含全部模板项目，也不要求所有报告项目都出现在模板中。'
            '模板外但原文明示的项目同样提取，保留其原始名称、结果和单位，不强行映射到模板项目。'
            '1.定位同一行的项目原文、本次结果、单位和上下文，先排除历史结果与参考值。'
            '2.在模板内比较候选名称，允许汉字形近误认、偏旁误认、漏字、多字、断词和单位尾部粘连。'
            '3.把整张表与模板一对一对齐：先用明确项目作为锚点，再结合固定参考范围、'
            '名称相似程度、保留的关键汉字、英文缩写和单位维度筛选其余候选。'
            '不同OCR行不能重复占用同一模板项目；不得把缺行的结果向下一行顺移。'
            '参考范围必须从原文抄入reference_low、reference_high，供后续联合匹配。单位本身也可能有OCR错误，'
            '不能单凭单位下结论。结果数值是否处于参考范围不能作为选择项目的依据。'
            '4.比较最可能候选与其他候选，特别检查嗜酸/嗜碱、计数/百分比、含量/浓度、CV/SD；'
            '不能仅凭行顺序或为了凑齐模板项目而替换。'
            '5.若证据足以唯一确定，attributes.item逐字使用模板的display_name（没有该字段时用name），'
            '不要自行改写、扩写或翻译模板名称；否则保留原始项目名称，'
            'attributes.needs_review设为true，并写明reason和候选项目。'
            '无论是否纠正，都将识别到的原始项目文字写入attributes.item_ocr_original，'
            '纠正理由写入attributes.correction_reason。'
            'extraction_text仍必须逐字复制OCR原文，不能用纠正后的名称改写证据。'
            '只取本次结果，不取历史结果；不根据模板补齐缺项或改动数值。'
        )
    examples_cfg = profile.get("examples") or [{"text": DEFAULT_EXAMPLE_TEXT, "extractions": DEFAULT_EXAMPLE}]
    if template:
        # A negative example cannot leak an illustrative result into a report.
        sample = template['items'][0]
        sample_name = sample.get('display_name', sample['name'])
        examples_cfg = [{"text": sample_name + '（结果缺失）', "extractions": []}]
    examples = []
    for ex in examples_cfg:
        extractions = []
        for item in ex.get("extractions", []):
            extractions.append(lx.data.Extraction(
                extraction_class="clinical_result",
                extraction_text=item.get("text", ""),
                attributes=item.get("attributes", {}),
            ))
        examples.append(lx.data.ExampleData(text=ex.get("text", ""), extractions=extractions))

    result = lx.extract(
        text_or_documents=text[: settings.max_text_chars],
        prompt_description=prompt,
        examples=examples,
        model_id=settings.ollama_model,
        model_url=settings.ollama_url,
        temperature=0.0,
        max_char_buffer=3000,
        model=_progress_model(settings),
        max_workers=1,
    )
    out = []
    for e in result.extractions:
        if e.extraction_class != "clinical_result":
            continue
        attrs = e.attributes or {}
        from .result_rules import is_header_name
        if is_header_name(attrs.get('item')) or is_header_name(attrs.get('item_ocr_original')):
            continue
        if str(attrs.get('item', '')).strip() in {
            '日期', '报告日期', '检查日期', '检验日期', '采样日期', '采样时间',
            '报告时间', '检查时间', '检验时间', '审核时间', '审核日期', '出生日期',
        }:
            continue
        ci = getattr(e, "char_interval", None)
        grounded = ci is not None
        evidence = e.extraction_text or ""
        # LangExtract 官方建议丢弃无法映射回原文的结果，避免把模型幻觉带入科研数据。
        if not grounded or not evidence or evidence not in text[:settings.max_text_chars]:
            continue
        if not value_is_grounded(attrs.get('value'), evidence,
                                 attrs.get('item_ocr_original') or attrs.get('item'), attrs.get('unit')):
            continue
        out.append({
            "source_kind": "text",
            "category": str(attrs.get("category", "")),
            "item_original": str(attrs.get("item_ocr_original") or attrs.get("item", "")) or evidence,
            "item_standard": str(attrs.get("item", "")) or evidence,
            "value": str(attrs.get("value", "")),
            "value_num": _num(str(attrs.get("value", ""))),
            "unit": str(attrs.get("unit", "")),
            "reference_low": str(attrs.get("reference_low", "")),
            "reference_high": str(attrs.get("reference_high", "")),
            "abnormal_flag": str(attrs.get("abnormal_flag", "")),
            "evidence": evidence,
            "page": page,
            "bbox_json": "",
            "confidence": 1.0 if grounded else 0.0,
            "payload_json": {
                "item_ocr_original": str(attrs.get('item_ocr_original', '')),
                "ai_correction_reason": str(attrs.get('correction_reason', '')),
                "ai_review_warning": (
                    str(attrs.get('reason') or 'AI无法唯一确定项目，请核对')
                    if str(attrs.get('needs_review', False)).lower() == 'true' else ''
                ),
                "char_start": getattr(ci, "start_pos", None) if ci else None,
                "char_end": getattr(ci, "end_pos", None) if ci else None,
                "alignment_status": str(getattr(e, "alignment_status", "")),
            },
        })
    return out


def _progress_model(settings):
    from .ollama_progress import ProgressOllamaModel
    from .jobs import progress_callback
    return ProgressOllamaModel(model_id=settings.ollama_model, model_url=settings.ollama_url,
                               temperature=0.0).set_progress(progress_callback())
