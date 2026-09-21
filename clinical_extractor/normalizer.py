from __future__ import annotations
import re

ITEM_MAP = {
    "wbc": "WBC", "白细胞": "WBC", "白细胞计数": "WBC",
    "hgb": "HGB", "hb": "HGB", "血红蛋白": "HGB",
    "plt": "PLT", "血小板": "PLT", "血小板计数": "PLT",
    "alt": "ALT", "丙氨酸氨基转移酶": "ALT", "谷丙转氨酶": "ALT",
    "ast": "AST", "天门冬氨酸氨基转移酶": "AST", "谷草转氨酶": "AST",
    "cea": "CEA", "ca153": "CA15-3", "ca15-3": "CA15-3", "ca 15-3": "CA15-3",
    "er": "ER", "pr": "PR", "her2": "HER2", "ki67": "Ki-67", "ki-67": "Ki-67",
}

def normalize_item(name: str) -> str:
    key = re.sub(r"[\s_（）()]+", "", (name or "").strip().lower())
    return ITEM_MAP.get(key, (name or "").strip())

def normalize_record(r: dict) -> dict:
    r = dict(r)
    r["item_standard"] = normalize_item(r.get("item_standard") or r.get("item_original") or "")
    flag = str(r.get("abnormal_flag") or "").strip().lower()
    if flag in {"h", "high", "↑", "偏高"}: r["abnormal_flag"] = "高"
    elif flag in {"l", "low", "↓", "偏低"}: r["abnormal_flag"] = "低"
    elif flag in {"positive", "+", "阳性"}: r["abnormal_flag"] = "阳性"
    elif flag in {"negative", "-", "阴性"}: r["abnormal_flag"] = "阴性"
    return r
