from __future__ import annotations
from pathlib import Path
import pandas as pd
from .db import connect
from .config import EXPORT_DIR

COLS = ["report_id","patient_id","report_date","report_type","filename","source_kind","category","item_original","item_standard","value","value_num","unit","reference_low","reference_high","abnormal_flag","evidence","page","reviewed"]

def dataframe(reviewed_only: bool = False):
    where = "WHERE e.reviewed=1" if reviewed_only else ""
    sql = f"""
    SELECT e.report_id,r.patient_id,r.report_date,r.report_type,r.filename,
           e.source_kind,e.category,e.item_original,e.item_standard,e.value,e.value_num,e.unit,
           e.reference_low,e.reference_high,e.abnormal_flag,e.evidence,e.page,e.reviewed
    FROM extractions e JOIN reports r ON e.report_id=r.id {where}
    ORDER BY e.report_id,e.id
    """
    with connect() as con:
        rows = con.execute(sql).fetchall()
    return pd.DataFrame([dict(x) for x in rows], columns=COLS)

def export_csv(path: Path, reviewed_only=False):
    dataframe(reviewed_only).to_csv(path, index=False, encoding="utf-8-sig")
    return path

def export_xlsx(path: Path, reviewed_only=False):
    dataframe(reviewed_only).to_excel(path, index=False, sheet_name="results")
    return path
