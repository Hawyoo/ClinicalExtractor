from __future__ import annotations
import json
import os
import shutil
import threading
import time
import uuid
from datetime import datetime
from urllib.parse import quote
from pathlib import Path
from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from .config import ROOT, DATA_DIR, UPLOAD_DIR, EXPORT_DIR, load_settings, save_settings, Settings
from .db import init_db, connect, now_iso
from .service import process_report
from .transfer import TRANSFER_SUFFIX, create_ocr_transfer, inspect_ocr_transfer, import_ocr_transfer
from .exporter import export_csv, export_xlsx

app = FastAPI(title="ClinicalExtractor", version="1.0.0")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=ROOT / "templates")
EXTRACTION_MODES = ["表格式报告", "长文本报告"]

@app.on_event("startup")
def startup(): init_db()

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    with connect() as con:
        reports = con.execute("SELECT r.*, (SELECT COUNT(*) FROM extractions e WHERE e.report_id=r.id) AS n FROM reports r ORDER BY r.id DESC").fetchall()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"reports": reports, "extraction_modes": EXTRACTION_MODES, "notice": request.query_params.get("notice", "")},
    )

@app.post("/upload")
async def upload(
    files: list[UploadFile] = File(...),
    patient_id: str = Form(""),
    profiles: list[str] = Form([]),
):
    for index, f in enumerate(files):
        suffix = Path(f.filename or "upload.bin").suffix.lower()
        if suffix not in {".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".txt", ".md"}:
            continue
        safe = f"{uuid.uuid4().hex[:10]}_{Path(f.filename or 'upload').name}"
        dest = UPLOAD_DIR / safe
        with dest.open("wb") as out:
            shutil.copyfileobj(f.file, out)
        with connect() as con:
            con.execute("INSERT INTO reports(patient_id,report_date,report_type,profile,filename,file_path,status,transfer_key,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                        (patient_id, "", "", profiles[index] if index < len(profiles) else "表格式报告",
                         f.filename or safe, str(dest), "未处理", str(uuid.uuid4()), now_iso()))
    return RedirectResponse("/", status_code=303)

@app.get("/report/{report_id}/file")
def report_file(report_id: int):
    with connect() as con:
        row = con.execute("SELECT filename,file_path FROM reports WHERE id=?", (report_id,)).fetchone()
    if not row:
        return RedirectResponse("/", status_code=303)
    path = Path(row["file_path"])
    if not path.exists():
        path = UPLOAD_DIR / path.name
    return FileResponse(path, filename=row["filename"])

@app.post("/report/{report_id}/delete")
def delete_report(report_id: int):
    with connect() as con:
        row = con.execute("SELECT file_path FROM reports WHERE id=?", (report_id,)).fetchone()
        con.execute("DELETE FROM reports WHERE id=?", (report_id,))
    if row:
        path = Path(row["file_path"])
        if not path.exists():
            path = UPLOAD_DIR / path.name
        try: path.unlink(missing_ok=True)
        except Exception: pass
    return RedirectResponse("/", status_code=303)

@app.post("/report/{report_id}/process")
def process(report_id: int):
    try:
        process_report(report_id)
    except Exception:
        # The service records a full diagnostic in reports.error. Return the
        # user to that report rather than emitting a bare FastAPI 500 page.
        pass
    return RedirectResponse(f"/report/{report_id}", status_code=303)

@app.post("/report/{report_id}/ocr")
def process_ocr(report_id: int):
    try:
        process_report(report_id, stage="ocr")
    except Exception:
        pass
    return RedirectResponse(f"/report/{report_id}", status_code=303)

@app.post("/report/{report_id}/llm")
def process_llm(report_id: int):
    try:
        process_report(report_id, stage="llm")
    except Exception:
        pass
    return RedirectResponse(f"/report/{report_id}", status_code=303)

@app.post("/process-pending")
def process_pending():
    with connect() as con:
        ids = [r[0] for r in con.execute("SELECT id FROM reports WHERE status IN ('未处理','失败') ORDER BY id").fetchall()]
    for rid in ids:
        try:
            process_report(rid)
        except Exception:
            # Continue batch work; each individual error is saved in SQLite and
            # displayed by the report list.
            continue
    return RedirectResponse("/", status_code=303)

@app.post("/ocr-pending")
def ocr_pending():
    with connect() as con:
        ids = [r[0] for r in con.execute("SELECT id FROM reports WHERE status IN ('未处理','失败') ORDER BY id").fetchall()]
    for rid in ids:
        try:
            process_report(rid, stage="ocr")
        except Exception:
            continue
    return RedirectResponse("/", status_code=303)

@app.get("/transfer/export-ocr")
def export_ocr_transfer():
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = EXPORT_DIR / f"clinical-extractor-ocr-{stamp}{TRANSFER_SUFFIX}"
    try:
        create_ocr_transfer(path)
    except ValueError as exc:
        return RedirectResponse(f"/?notice={quote(str(exc))}", status_code=303)
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")

@app.post("/transfer/import-ocr")
async def import_ocr_transfer_file(package: UploadFile = File(...)):
    if not (package.filename or "").lower().endswith(TRANSFER_SUFFIX):
        return RedirectResponse(f"/?notice={quote('请选择 ClinicalExtractor OCR 数据包（.ceocr）')}", status_code=303)
    staging_dir = DATA_DIR / "transfer-staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    temporary = staging_dir / f"{token}{TRANSFER_SUFFIX}"
    try:
        with temporary.open("wb") as output:
            shutil.copyfileobj(package.file, output)
        inspect_ocr_transfer(temporary)
        return RedirectResponse(f"/transfer/resolve/{token}", status_code=303)
    except Exception as exc:
        return RedirectResponse(f"/?notice={quote(f'导入失败：{str(exc)}')}", status_code=303)

@app.get("/transfer/resolve/{token}", response_class=HTMLResponse)
def resolve_ocr_transfer(request: Request, token: str):
    package = DATA_DIR / "transfer-staging" / f"{token}{TRANSFER_SUFFIX}"
    if not package.exists():
        return RedirectResponse(f"/?notice={quote('OCR 数据包已过期，请重新选择文件')}", status_code=303)
    try:
        preview = inspect_ocr_transfer(package)
    except Exception as exc:
        package.unlink(missing_ok=True)
        return RedirectResponse(f"/?notice={quote(f'无法读取 OCR 数据包：{str(exc)}')}", status_code=303)
    return templates.TemplateResponse(request=request, name="transfer_resolve.html", context={"token": token, **preview})

@app.post("/transfer/resolve/{token}")
def confirm_ocr_transfer(token: str, replace_keys: list[str] = Form([])):
    package = DATA_DIR / "transfer-staging" / f"{token}{TRANSFER_SUFFIX}"
    if not package.exists():
        return RedirectResponse(f"/?notice={quote('OCR 数据包已过期，请重新选择文件')}", status_code=303)
    try:
        result = import_ocr_transfer(package, set(replace_keys))
        notice = f"导入完成：新增 {result.imported} 份，覆盖更新 {result.replaced} 份，保留原有 {result.skipped} 份"
        return RedirectResponse(f"/?notice={quote(notice)}", status_code=303)
    except Exception as exc:
        return RedirectResponse(f"/?notice={quote(f'导入失败：{str(exc)}')}", status_code=303)
    finally:
        package.unlink(missing_ok=True)

@app.get("/report/{report_id}", response_class=HTMLResponse)
def report_view(request: Request, report_id: int):
    with connect() as con:
        report = con.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
        items = con.execute("SELECT * FROM extractions WHERE report_id=? ORDER BY id", (report_id,)).fetchall()
    return templates.TemplateResponse(
        request=request,
        name="report.html",
        context={"report": report, "items": items},
    )

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
    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={"settings": load_settings()},
    )

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

def _exit_after_response():
    time.sleep(0.35)
    os._exit(0)

@app.post("/quit", response_class=HTMLResponse)
def quit_application():
    # The delay lets the browser receive this response before its local server
    # exits. The Portable launcher observes the process and closes with it.
    threading.Thread(target=_exit_after_response, daemon=True).start()
    return "<meta charset='utf-8'><title>ClinicalExtractor</title><p style='font-family:Microsoft YaHei;margin:40px'>程序已退出，可关闭此网页。</p>"

def run():
    import uvicorn
    port = int(os.getenv("CLINICAL_EXTRACTOR_PORT", "8765"))
    uvicorn.run("clinical_extractor.main:app", host="127.0.0.1", port=port, reload=False)

if __name__ == "__main__": run()
