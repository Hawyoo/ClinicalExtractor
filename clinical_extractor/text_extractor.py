from __future__ import annotations
import json
import re
from .config import load_settings
from .profiles import load_profile

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

def extract_text(text: str, profile_id: str = "generic", page: int | None = None):
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
    examples_cfg = profile.get("examples") or [{"text": DEFAULT_EXAMPLE_TEXT, "extractions": DEFAULT_EXAMPLE}]
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
    )
    out = []
    for e in result.extractions:
        if e.extraction_class != "clinical_result":
            continue
        attrs = e.attributes or {}
        ci = getattr(e, "char_interval", None)
        grounded = ci is not None
        evidence = e.extraction_text or ""
        # LangExtract 官方建议丢弃无法映射回原文的结果，避免把模型幻觉带入科研数据。
        if not grounded:
            continue
        out.append({
            "source_kind": "text",
            "category": str(attrs.get("category", "")),
            "item_original": str(attrs.get("item", "")) or evidence,
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
                "char_start": getattr(ci, "start_pos", None) if ci else None,
                "char_end": getattr(ci, "end_pos", None) if ci else None,
                "alignment_status": str(getattr(e, "alignment_status", "")),
            },
        })
    return out
