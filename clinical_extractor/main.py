from __future__ import annotations
import json
import shutil
import uuid
from pathlib import Path
from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from .config import ROOT, UPLOAD_DIR, EXPORT_DIR, load_settings, save_settings, Settings
from .db import init_db, connect, now_iso
from .profiles import list_profiles
from .service import process_report
from .exporter import export_csv, export_xlsx

app = FastAPI(title="ClinicalExtractor", version="1.0.0")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=ROOT / "templates")

@app.on_event("startup")
def startup(): init_db()

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    with connect() as con:
        reports = con.execute("SELECT r.*, (SELECT COUNT(*) FROM extractions e WHERE e.report_id=r.id) AS n FROM reports r ORDER BY r.id DESC").fetchall()
    return templates.TemplateResponse("index.html", {"request": request, "reports": reports, "profiles": list_profiles()})

@app.post("/upload")
async def upload(files: list[UploadFile] = File(...), patient_id: str = Form(""), report_date: str = Form(""), report_type: str = Form("未分类"), profile: str = Form("generic")):
    for f in files:
        suffix = Path(f.filename or "upload.bin").suffix.lower()
        if suffix not in {".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".txt", ".md"}:
            continue
        safe = f"{uuid.uuid4().hex[:10]}_{Path(f.filename or 'upload').name}"
        dest = UPLOAD_DIR / safe
        with dest.open("wb") as out:
            shutil.copyfileobj(f.file, out)
        with connect() as con:
            con.execute("INSERT INTO reports(patient_id,report_date,report_type,profile,filename,file_path,status,created_at) VALUES(?,?,?,?,?,?,?,?)",
                        (patient_id, report_date, report_type, profile, f.filename or safe, str(dest), "未处理", now_iso()))
    return RedirectResponse("/", status_code=303)

@app.get("/report/{report_id}/file")
def report_file(report_id: int):
    with connect() as con:
        row = con.execute("SELECT filename,file_path FROM reports WHERE id=?", (report_id,)).fetchone()
    if not row:
        return RedirectResponse("/", status_code=303)
    return FileResponse(row["file_path"], filename=row["filename"])

@app.post("/report/{report_id}/delete")
def delete_report(report_id: int):
    with connect() as con:
        row = con.execute("SELECT file_path FROM reports WHERE id=?", (report_id,)).fetchone()
        con.execute("DELETE FROM reports WHERE id=?", (report_id,))
    if row:
        try: Path(row["file_path"]).unlink(missing_ok=True)
        except Exception: pass
    return RedirectResponse("/", status_code=303)

@app.post("/report/{report_id}/process")
def process(report_id: int):
    try: process_report(report_id)
    except Exception: pass
    return RedirectResponse(f"/report/{report_id}", status_code=303)

@app.post("/process-pending")
def process_pending():
    with connect() as con:
        ids = [r[0] for r in con.execute("SELECT id FROM reports WHERE status IN ('未处理','失败') ORDER BY id").fetchall()]
    for rid in ids:
        try: process_report(rid)
        except Exception: continue
    return RedirectResponse("/", status_code=303)

@app.get("/report/{report_id}", response_class=HTMLResponse)
def report_view(request: Request, report_id: int):
    with connect() as con:
        report = con.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
        items = con.execute("SELECT * FROM extractions WHERE report_id=? ORDER BY id", (report_id,)).fetchall()
    return templates.TemplateResponse("report.html", {"request": request, "report": report, "items": items})

@app.post("/report/{report_id}/metadata")
def metadata(report_id: int, patient_id: str=Form(""), report_date: str=Form(""), report_type: str=Form("未分类"), profile: str=Form("generic")):
    with connect() as con:
        con.execute("UPDATE reports SET patient_id=?,report_date=?,report_type=?,profile=? WHERE id=?", (patient_id,report_date,report_type,profile,report_id))
    return RedirectResponse(f"/report/{report_id}", status_code=303)

@app.post("/extraction/{eid}/update")
def update_extraction(eid: int, item_standard: str=Form(""), value: str=Form(""), unit: str=Form(""), reference_low: str=Form(""), reference_high: str=Form(""), abnormal_flag: str=Form(""), reviewed: str=Form("0")):
    with connect() as con:
        row = con.execute("SELECT report_id FROM extractions WHERE id=?", (eid,)).fetchone()
        if row:
            con.execute("UPDATE extractions SET item_standard=?,value=?,unit=?,reference_low=?,reference_high=?,abnormal_flag=?,reviewed=? WHERE id=?",
                        (item_standard,value,unit,reference_low,reference_high,abnormal_flag,1 if reviewed=="1" else 0,eid))
            rid = row["report_id"]
        else: rid = 0
    return RedirectResponse(f"/report/{rid}", status_code=303)

@app.post("/report/{report_id}/mark-reviewed")
def mark_reviewed(report_id: int):
    with connect() as con:
        con.execute("UPDATE extractions SET reviewed=1 WHERE report_id=?", (report_id,))
        con.execute("UPDATE reports SET status='已审核' WHERE id=?", (report_id,))
    return RedirectResponse(f"/report/{report_id}", status_code=303)

@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    return templates.TemplateResponse("settings.html", {"request": request, "settings": load_settings()})

@app.post("/settings")
def settings_save(ollama_url: str=Form(...), ollama_model: str=Form(...), pp_device: str=Form("cpu"), max_text_chars: int=Form(12000), mock_mode: str=Form("0")):
    s = load_settings()
    s.ollama_url=ollama_url; s.ollama_model=ollama_model; s.pp_device=pp_device; s.max_text_chars=max_text_chars; s.mock_mode=(mock_mode=="1")
    save_settings(s)
    return RedirectResponse("/settings", status_code=303)

@app.get("/export/csv")
def download_csv(reviewed_only: int=0):
    p = EXPORT_DIR / "clinical_extractor.csv"; export_csv(p, bool(reviewed_only)); return FileResponse(p, filename=p.name)

@app.get("/export/xlsx")
def download_xlsx(reviewed_only: int=0):
    p = EXPORT_DIR / "clinical_extractor.xlsx"; export_xlsx(p, bool(reviewed_only)); return FileResponse(p, filename=p.name)

@app.get("/health")
def health():
    s=load_settings(); return {"ok": True, "model": s.ollama_model, "mock_mode": s.mock_mode}

def run():
    import uvicorn
    uvicorn.run("clinical_extractor.main:app", host="127.0.0.1", port=8765, reload=False)

if __name__ == "__main__": run()
