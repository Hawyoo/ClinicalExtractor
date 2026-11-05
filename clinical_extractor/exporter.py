from __future__ import annotations
from pathlib import Path
import pandas as pd
from .db import connect
from .config import EXPORT_DIR
from .normalizer import chinese_item_name, item_abbreviation
from .report_templates import table_templates, ascii_unit, fill_missing_template_unit
from .result_rules import is_header_record
from .grounding import ungrounded_legacy_ai

COLS = ['patient_id', 'report_type', 'file_name', 'item_name', 'item_abbr', 'result', 'unit', 'reviewed']

def dataframe(reviewed_only: bool = False):
    where = "WHERE e.reviewed=1" if reviewed_only else ""
    sql = f"""
    SELECT e.report_id,r.patient_id,r.report_type,r.filename,r.profile,r.template_id,
           e.item_original,e.item_standard,e.value,e.unit,e.payload_json,e.reviewed
    FROM extractions e JOIN reports r ON e.report_id=r.id {where}
    ORDER BY e.report_id,e.sort_order,e.id
    """
    with connect() as con:
        rows = con.execute(sql).fetchall()
    catalog = table_templates()
    rows = [dict(row) for row in rows]
    output = []
    for row in rows:
        record = dict(row)
        fill_missing_template_unit(record, record['template_id'], catalog)
        if is_header_record(record) or ungrounded_legacy_ai(record):
            continue
        record['item_name'] = chinese_item_name(record, catalog)
        record['item_abbr'] = item_abbreviation(record, catalog)
        record['file_name'] = record['filename']
        record['result'] = record['value']
        record['unit'] = ascii_unit(record['unit'])
        record['report_type'] = catalog.get(record['template_id'], {}).get('name') or record['report_type'] or record['profile']
        record['reviewed'] = int(bool(record['reviewed']))
        output.append(record)
    return pd.DataFrame(output, columns=COLS)

def export_csv(path: Path, reviewed_only=False):
    dataframe(reviewed_only).to_csv(path, index=False, encoding="utf-8-sig")
    return path


def csv_bytes(reviewed_only=False):
    """Create a private download snapshot without a shared intermediate file."""
    return dataframe(reviewed_only).to_csv(index=False).encode('utf-8-sig')

def export_xlsx(path: Path, reviewed_only=False):
    dataframe(reviewed_only).to_excel(path, index=False, sheet_name="results")
    return path
