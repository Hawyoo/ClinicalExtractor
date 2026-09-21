from __future__ import annotations

def validate_record(r: dict):
    warnings = []
    if not (r.get("item_standard") or r.get("item_original")):
        warnings.append("缺少项目名")
    if not r.get("value"):
        warnings.append("缺少结果")
    item = (r.get("item_standard") or "").lower()
    num = r.get("value_num")
    if item in {"ki-67", "er", "pr"} and num is not None and not (0 <= num <= 100):
        warnings.append("百分比超出0-100")
    if item == "her2" and r.get("value") and str(r["value"]).strip() not in {"0", "0+", "1+", "2+", "3+", "阴性", "阳性"}:
        warnings.append("HER2格式需人工确认")
    return warnings
