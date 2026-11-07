from __future__ import annotations
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from . import config

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  patient_id TEXT NOT NULL DEFAULT '',
  report_type TEXT NOT NULL DEFAULT '未分类',
  profile TEXT NOT NULL DEFAULT '表格式报告',
  filename TEXT NOT NULL,
  file_path TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT '未处理',
  raw_text TEXT NOT NULL DEFAULT '',
  parser_json TEXT NOT NULL DEFAULT '',
  error TEXT NOT NULL DEFAULT '',
  transfer_key TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS extractions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  report_id INTEGER NOT NULL,
  source_kind TEXT NOT NULL DEFAULT 'text',
  category TEXT NOT NULL DEFAULT '',
  item_original TEXT NOT NULL DEFAULT '',
  item_standard TEXT NOT NULL DEFAULT '',
  value TEXT NOT NULL DEFAULT '',
  value_num REAL,
  unit TEXT NOT NULL DEFAULT '',
  reference_low TEXT NOT NULL DEFAULT '',
  reference_high TEXT NOT NULL DEFAULT '',
  abnormal_flag TEXT NOT NULL DEFAULT '',
  evidence TEXT NOT NULL DEFAULT '',
  page INTEGER,
  bbox_json TEXT NOT NULL DEFAULT '',
  confidence REAL,
  reviewed INTEGER NOT NULL DEFAULT 0,
  payload_json TEXT NOT NULL DEFAULT '',
  FOREIGN KEY(report_id) REFERENCES reports(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(status);
CREATE INDEX IF NOT EXISTS idx_extractions_report ON extractions(report_id);
CREATE TABLE IF NOT EXISTS transfer_imports (
  batch_id TEXT PRIMARY KEY,
  imported_at TEXT NOT NULL,
  report_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS ocr_text_revisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  report_id INTEGER NOT NULL,
  previous_text TEXT NOT NULL,
  new_text TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(report_id) REFERENCES reports(id) ON DELETE CASCADE
);
"""

@contextmanager
def connect():
    if config.DB_PATH is None:
        raise ValueError('请先创建或打开项目')
    # OCR and AI have separate workers; short write transactions can wait for
    # one another without failing a large batch on a transient database lock.
    con = sqlite3.connect(config.DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init_db():
    with connect() as con:
        con.executescript(SCHEMA)
        # Legacy column stays for compatibility with old databases/packages,
        # but report dates are no longer retained as structured metadata.
        columns = {row["name"] for row in con.execute("PRAGMA table_info(reports)")}
        if "template_id" not in columns:
            con.execute("ALTER TABLE reports ADD COLUMN template_id TEXT NOT NULL DEFAULT ''")
        for name,definition in [('ocr_text_original',"TEXT NOT NULL DEFAULT ''"),('ocr_text_edited','INTEGER NOT NULL DEFAULT 0')]:
            if name not in columns:
                con.execute(f'ALTER TABLE reports ADD COLUMN {name} {definition}')
        extraction_columns={row['name'] for row in con.execute('PRAGMA table_info(extractions)')}
        if 'sort_order' not in extraction_columns:
            con.execute('ALTER TABLE extractions ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0')
            con.execute('UPDATE extractions SET sort_order=id')
        # Existing table reports join the unified catalog without touching
        # OCR evidence, numeric results, or review confirmations.
        con.execute("UPDATE reports SET template_id='all' WHERE profile='表格式报告' AND template_id<>'all'")
        if "transfer_key" not in columns:
            con.execute("ALTER TABLE reports ADD COLUMN transfer_key TEXT NOT NULL DEFAULT ''")
        con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_reports_transfer_key ON reports(transfer_key) WHERE transfer_key <> ''")
        # Existing databases predate portable transfers. Give their reports a
        # stable identifier once so later exports can be compared safely.
        import uuid
        for row in con.execute("SELECT id FROM reports WHERE transfer_key='' ").fetchall():
            con.execute("UPDATE reports SET transfer_key=? WHERE id=?", (str(uuid.uuid4()), row["id"]))
        normalize_stored_unit_powers(con)


def normalize_stored_unit_powers(con):
    """Migrate unit typography only; never invalidate existing reviews."""
    import re
    from .report_templates import ascii_unit
    updates = []
    for row in con.execute('SELECT id,item_standard,unit FROM extractions').fetchall():
        raw = row['unit']
        # Keep all non-exponent unit spelling intact in this migration.
        unit = ascii_unit(raw) if re.search('[⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺]', raw) else raw
        if row['item_standard'].casefold() in {'egfr', 'egfr-epi'} and re.fullmatch(
                r'ml/min/1[.,]73m(?:\^?2|["”\x27]2)?', unit.replace(' ', ''), re.I):
            unit = 'mL/min/1.73m^2'
        if unit != raw:
            updates.append((unit, row['id']))
    con.executemany('UPDATE extractions SET unit=? WHERE id=?', updates)
    return len(updates)


def now_iso():
    return datetime.now().isoformat(timespec="seconds")
