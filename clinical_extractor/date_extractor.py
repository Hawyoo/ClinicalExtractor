from __future__ import annotations

import re
from datetime import date


# Prefer a date next to a report-specific label.  The fallback supports scans
# whose OCR lost the label, but deliberately only accepts dates in 2000–2099.
_LABELED_DATE = re.compile(
    r"(?:报告|检查|检验|送检|采样|出具|打印)\s*日期?\s*[:：]?\s*"
    r"(20\d{2})\s*(?:年|[-/.])\s*(\d{1,2})\s*(?:月|[-/.])\s*(\d{1,2})(?:日)?"
)
_DATE = re.compile(
    r"\b(20\d{2})\s*(?:年|[-/.])\s*(\d{1,2})\s*(?:月|[-/.])\s*(\d{1,2})(?:日)?\b"
)
_COMPACT_DATE = re.compile(r"\b(20\d{2})(\d{2})(\d{2})\b")


def _normalise(year: str, month: str, day: str) -> str:
    try:
        return date(int(year), int(month), int(day)).isoformat()
    except ValueError:
        return ""


def extract_report_date(text: str) -> str:
    """Return an ISO report date from OCR text, or an empty string if unsure."""
    text = text or ""
    for pattern in (_LABELED_DATE, _DATE, _COMPACT_DATE):
        match = pattern.search(text)
        if match:
            value = _normalise(*match.groups())
            if value:
                return value
    return ""
