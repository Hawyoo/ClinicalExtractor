from __future__ import annotations
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from .config import DB_PATH

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  patient_id TEXT NOT NULL DEFAULT '',
  report_date TEXT NOT NULL DEFAULT '',
  report_type TEXT NOT NULL DEFAULT '未分类',
  profile TEXT NOT NULL DEFAULT 'generic',
  filename TEXT NOT NULL,
  file_path TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT '未处理',
  raw_text TEXT NOT NULL DEFAULT '',
  parser_json TEXT NOT NULL DEFAULT '',
  error TEXT NOT NULL DEFAULT '',
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
"""

@contextmanager
def connect():
    con = sqlite3.connect(DB_PATH)
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


def now_iso():
    return datetime.now().isoformat(timespec="seconds")
