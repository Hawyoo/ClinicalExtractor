from __future__ import annotations
import json
import os
import shutil
import threading
import time
import uuid
import asyncio
import sqlite3
from datetime import datetime
from urllib.parse import quote
from pathlib import Path
from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse, Response
from starlette.background import BackgroundTask
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from . import config
from .config import ROOT, load_settings, save_settings, Settings, ocr_thread_count
from .db import init_db, connect, now_iso
from .service import process_report
from .jobs import start_job, snapshots, is_busy, total_timer, resume_pending_jobs, report_deletion
from .preferences import load_preferences, save_preferences
from .report_templates import table_templates, ascii_unit, fill_missing_template_unit, refresh_reference_warning, ALL_TEMPLATE_ID
from .normalizer import chinese_item_name, normalize_record
from .review import attention_for
from .result_rules import is_header_name, is_header_record
from .grounding import ungrounded_ai_result
from .table_extractor import _value_num
from .transfer import TRANSFER_SUFFIX, create_transfer, inspect_transfer, import_transfer
from .exporter import csv_bytes

app = FastAPI(title="ClinicalExtractor", version="1.0.0")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
def shared_context(request):
    manager = config.PROJECT_MANAGER
    return {'ui_preferences':load_preferences(),
            'current_project':manager.active() if manager else None,
            'projects':manager.state['projects'] if manager else [],
            'project_management_enabled':manager is not None,
            'legacy_available':manager.legacy_available() if manager else False}


templates = Jinja2Templates(directory=ROOT / "templates", context_processors=[shared_context])
templates.env.globals['ui_preferences'] = {'theme':None,'report_sort':None}
templates.env.filters['from_json'] = json.loads
EXTRACTION_MODES = ["表格式报告", "长文本报告"]
_project_request_lock = asyncio.Lock()


@app.middleware('http')
async def isolate_project_requests(request: Request, call_next):
    # Serialize project changes with all in-flight report/upload/export requests.
    # Background workers are protected separately by project_transition().
    async with _project_request_lock:
        manager = config.PROJECT_MANAGER
        if manager and manager.refresh():
            config.activate_project(manager.active())
        expected = request.headers.get('x-clinical-project') or request.query_params.get('project_id')
        if manager and expected and expected != (manager.state['active_id'] or '__none__'):
            if not request.headers.get('x-clinical-project') and 'text/html' in request.headers.get('accept', ''):
                return RedirectResponse('/', status_code=303)
            return JSONResponse({'detail':'当前项目已切换，请刷新页面后操作'}, status_code=409,
                                headers={'X-Clinical-Project-Changed':'1'})
        if manager and not manager.active() and not (request.url.path in
                {'/', '/health', '/quit', '/settings', '/preferences'} or
                request.url.path.startswith(('/static/', '/projects/', '/api/preferences'))):
            if 'application/json' in request.headers.get('accept', '') or request.url.path == '/jobs':
                return JSONResponse({'detail':'请先创建或打开项目'}, status_code=409)
            return RedirectResponse('/', status_code=303)
        return await call_next(request)

@app.on_event("startup")
def startup():
    if config.PROJECT_MANAGER is not None or (config.PROJECT_DIR is not None and
            config.DB_PATH == config.PROJECT_DIR / 'clinical_extractor.sqlite3'):
        config.initialize_projects()
    if config.PROJECT_MANAGER is None or config.PROJECT_MANAGER.active():
        init_db()
        resume_pending_jobs()


@app.post('/projects/{action}')
def change_project(action: str, project_id: str=Form(''), name: str=Form(''), folder: str=Form(''), import_legacy: bool=Form(False)):
    from .jobs import project_transition
    manager = config.PROJECT_MANAGER
    if not manager:
        return JSONResponse({'detail':'项目管理尚未初始化，请重启程序'}, status_code=409)
    try:
        with project_transition() as allowed:
            if not allowed:
                return RedirectResponse('/?notice='+quote('当前有排队或处理中的任务，请完成后再切换项目'), status_code=303)
            if action == 'delete':
                manager.delete(project_id)
                config.activate_project(manager.active())
                return RedirectResponse('/?notice='+quote('项目已删除，文件已移入 DELETE，可恢复'), status_code=303)
            if action == 'create':
                entry = manager.create(name, import_legacy=import_legacy)
            elif action == 'open':
                entry = manager.open(folder)
            elif action == 'switch':
                entry = next((p for p in manager.state['projects'] if p['id'] == project_id), None)
                if entry is None:
                    raise ValueError('项目不存在')
            else:
                raise ValueError('未知项目操作')
            previous = manager.active()
            try:
                manager.select(entry['id'])
                config.activate_project(entry)
                init_db()
                if action == 'create' and import_legacy:
                    manager.finish_legacy_import(entry)
            except Exception:
                if previous:
                    manager.select(previous['id'])
                else:
                    manager.state['active_id'] = ''
                    manager._save()
                config.activate_project(previous)
                raise
        resume_pending_jobs()
        return RedirectResponse('/', status_code=303)
    except (ValueError, OSError, sqlite3.Error) as exc:
        return RedirectResponse('/?notice='+quote('项目操作失败：'+str(exc)), status_code=303)

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    if config.PROJECT_MANAGER and not config.PROJECT_MANAGER.active():
        return templates.TemplateResponse(request=request, name='project_welcome.html',
                                          context={'notice':request.query_params.get('notice','')})
    with connect() as con:
        reports = con.execute("""SELECT r.*, (SELECT COUNT(*) FROM extractions e WHERE e.report_id=r.id) AS n
            FROM reports r ORDER BY CASE r.status
            WHEN '未处理' THEN 0 WHEN '待处理' THEN 0 WHEN '待审核' THEN 1 WHEN '失败' THEN 2 WHEN 'OCR已完成' THEN 3
            WHEN 'AI处理中' THEN 4 WHEN 'AI排队中' THEN 5 WHEN 'OCR处理中' THEN 6 WHEN 'OCR排队中' THEN 7
            WHEN '已审核' THEN 8 ELSE 1 END,r.id ASC""").fetchall()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"reports": reports, "extraction_modes": EXTRACTION_MODES, "table_templates": table_templates(), "notice": request.query_params.get("notice", "")},
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
        dest = config.UPLOAD_DIR / safe
        with dest.open("wb") as out:
            shutil.copyfileobj(f.file, out)
        with connect() as con:
            con.execute("INSERT INTO reports(patient_id,report_type,profile,filename,file_path,status,transfer_key,created_at) VALUES(?,?,?,?,?,?,?,?)",
                        (patient_id, "", profiles[index] if index < len(profiles) else "表格式报告",
                         f.filename or safe, str(dest), "未处理", str(uuid.uuid4()), now_iso()))
            rid = con.execute("SELECT last_insert_rowid()").fetchone()[0]
            mode = profiles[index] if index < len(profiles) else '表格式报告'
            con.execute("UPDATE reports SET template_id=? WHERE id=?", (ALL_TEMPLATE_ID if mode=='表格式报告' else '',rid))
    return RedirectResponse("/", status_code=303)

@app.get("/report/{report_id}/file")
def report_file(report_id: int):
    with connect() as con:
        row = con.execute("SELECT filename,file_path FROM reports WHERE id=?", (report_id,)).fetchone()
    if not row:
        return RedirectResponse("/", status_code=303)
    path = config.UPLOAD_DIR / Path(row['file_path']).name
    return FileResponse(path, filename=row["filename"])

@app.post("/report/{report_id}/delete")
def delete_report(report_id: int, request: Request):
    with report_deletion(report_id) as allowed:
        if not allowed:
            return JSONResponse({'deleted':False,'running':True,'detail':'正在处理，完成后可删除'}, status_code=409)
        with connect() as con:
            row = con.execute("SELECT file_path FROM reports WHERE id=?", (report_id,)).fetchone()
            con.execute("DELETE FROM reports WHERE id=?", (report_id,))
    if row:
        # Delete only the application's uploaded copy, including after moving
        # a data directory from another machine.
        path = config.UPLOAD_DIR / Path(row["file_path"]).name
        try: path.unlink(missing_ok=True)
        except Exception: pass
    if 'application/json' in request.headers.get('accept',''):
        return JSONResponse({'deleted':True,'report_id':report_id})
    return RedirectResponse("/", status_code=303)


@app.post("/report/{report_id}/ocr")
def process_ocr(report_id: int, request: Request):
    start_job(report_id, 'ocr')
    if 'application/json' in request.headers.get('accept', ''):
        return JSONResponse({'report_id': report_id, 'stage': 'ocr', 'accepted': True}, status_code=202)
    return RedirectResponse(f"/report/{report_id}", status_code=303)

@app.post("/report/{report_id}/llm")
def process_llm(report_id: int, request: Request):
    start_job(report_id, 'llm')
    if 'application/json' in request.headers.get('accept', ''):
        return JSONResponse({'report_id': report_id, 'stage': 'llm', 'accepted': True}, status_code=202)
    return RedirectResponse(f"/report/{report_id}", status_code=303)

@app.post("/process-pending")
def process_pending():
    with connect() as con:
        ids = [r[0] for r in con.execute("""SELECT id FROM reports WHERE status NOT IN
                ('已审核','待审核','OCR排队中','AI排队中','OCR处理中','AI处理中') ORDER BY id""").fetchall()]
    ids = [rid for rid in ids if not is_busy(rid)]
    if not ids:
        return RedirectResponse('/?notice='+quote('没有需要运行的报告'), status_code=303)
    ready = ollama_available()
    for rid in ids:
        start_job(rid, 'ocr', then_ai=ready)
    notice = f'已将 {len(ids)} 份报告加入 OCR → AI 队列' if ready else f'已将 {len(ids)} 份报告加入 OCR 队列；未连接可用的 Ollama 模型，本次仅运行 OCR'
    return RedirectResponse('/?notice='+quote(notice), status_code=303)


def ollama_available():
    """Check the configured local model once before submitting a batch."""
    import requests
    settings = load_settings()
    try:
        response = requests.get(settings.ollama_url.rstrip('/')+'/api/tags', timeout=2)
        response.raise_for_status()
        expected = settings.ollama_model
        expected = expected if ':' in expected else expected+':latest'
        return any((model.get('name') or model.get('model')) == expected
                   for model in response.json().get('models', []))
    except (requests.RequestException,ValueError,TypeError,AttributeError):
        return False



@app.get('/jobs')
def job_progress():
    jobs = snapshots()
    with connect() as con:
        reports = {row['id']:dict(row) for row in con.execute('''
            SELECT r.id,r.patient_id,r.filename,r.status,r.error,COUNT(e.id) AS n
            FROM reports r LEFT JOIN extractions e ON e.report_id=r.id GROUP BY r.id ORDER BY r.id
        ''').fetchall()}
        for job in jobs:
            row = reports.get(job['report_id'])
            job['report_status'] = row['status'] if row else '报告已删除'
            job['label'] = ((row['patient_id'] or '未填写患者ID') + ' · ' + row['filename']) if row else '报告已删除'
            job['file_name'] = row['filename'] if row else ''
    return {'jobs': jobs, 'total_timer': total_timer(),
            'report_states':[{**{k:row[k] for k in ('id','status','error','n')},
                              'running':any(j['report_id']==row['id'] and j['state']=='running' for j in jobs)}
                             for row in reports.values()]}

@app.get("/transfer/export")
def export_ocr_transfer():
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = config.EXPORT_DIR / f"clinical-extractor-ocr-{stamp}{TRANSFER_SUFFIX}"
    try:
        create_transfer(path)
    except ValueError as exc:
        return RedirectResponse(f"/?notice={quote(str(exc))}", status_code=303)
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")

@app.post("/transfer/import")
async def import_transfer_file(package: UploadFile = File(...)):
    if not (package.filename or "").lower().endswith(TRANSFER_SUFFIX):
        return RedirectResponse(f"/?notice={quote('请选择 ClinicalExtractor OCR 数据包（.ceocr）')}", status_code=303)
    staging_dir = config.PROJECT_DIR / "transfer-staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    temporary = staging_dir / f"{token}{TRANSFER_SUFFIX}"
    try:
        with temporary.open("wb") as output:
            shutil.copyfileobj(package.file, output)
        inspect_transfer(temporary)
        return RedirectResponse(f"/transfer/resolve/{token}", status_code=303)
    except Exception as exc:
        return RedirectResponse(f"/?notice={quote(f'导入失败：{str(exc)}')}", status_code=303)

@app.get("/transfer/resolve/{token}", response_class=HTMLResponse)
def resolve_ocr_transfer(request: Request, token: str):
    package = config.PROJECT_DIR / "transfer-staging" / f"{token}{TRANSFER_SUFFIX}"
    if not package.exists():
        return RedirectResponse(f"/?notice={quote('OCR 数据包已过期，请重新选择文件')}", status_code=303)
    try:
        preview = inspect_transfer(package)
    except Exception as exc:
        package.unlink(missing_ok=True)
        return RedirectResponse(f"/?notice={quote(f'无法读取 OCR 数据包：{str(exc)}')}", status_code=303)
    return templates.TemplateResponse(request=request, name="transfer_resolve.html", context={"token": token, **preview})

@app.post("/transfer/resolve/{token}")
def confirm_ocr_transfer(token: str, replace_keys: list[str] = Form([])):
    package = config.PROJECT_DIR / "transfer-staging" / f"{token}{TRANSFER_SUFFIX}"
    if not package.exists():
        return RedirectResponse(f"/?notice={quote('OCR 数据包已过期，请重新选择文件')}", status_code=303)
    try:
        result = import_transfer(package, set(replace_keys))
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
        items = con.execute("SELECT * FROM extractions WHERE report_id=? ORDER BY sort_order,id", (report_id,)).fetchall()
    items = [dict(item) for item in items if not is_header_record(dict(item)) and not ungrounded_ai_result({**dict(item),'profile':report['profile']})]
    catalog = table_templates()
    has_headerless_rows = False
    for item in items:
        refresh_reference_warning(item, report['template_id'], catalog)
        fill_missing_template_unit(item, report['template_id'], catalog)
        item['display_name'] = chinese_item_name(item, catalog)
        item['unit'] = ascii_unit(item['unit'])
        item['attention'] = attention_for(item)
        try:
            payload = item.get('payload_json') or {}
            if isinstance(payload, str):
                payload = json.loads(payload)
            if isinstance(payload, dict) and payload.get('headerless_recovery'):
                has_headerless_rows = True
        except (TypeError, ValueError):
            pass
    attention_items = sorted((item for item in items if item['attention']['visible']),
                             key=lambda item:(item['attention']['priority'], bool(item['reviewed'])))
    try:
        from .row_validation import saved_assignment_warnings
        row_warnings = []
        if not report['ocr_text_edited']:
            for page in json.loads(report['parser_json'] or '[]'):
                page_items = [item for item in items if item['page']==page.get('page_index') and item['source_kind']=='table']
                current = page_items if any(item['attention']['pairing'] for item in page_items) else None
                row_warnings.extend(w['message'] for w in saved_assignment_warnings(page,current)
                                    if w.get('kind') != 'verification_unavailable' and
                                    w.get('message') != '本页未能独立定位结果列，无法完成数量核验；这不代表结果重复，请核对原图。')
    except (TypeError,ValueError,KeyError):
        row_warnings = []
    return templates.TemplateResponse(
        request=request,
        name="report.html",
        context={"report": report, "items": items, "attention_items": attention_items, "table_templates": table_templates(), "row_warnings": row_warnings, "has_headerless_rows": has_headerless_rows},
    )

@app.get('/templates/catalog')
def template_catalog():
    from .template_editor import catalog_data
    return JSONResponse(catalog_data(), headers={'Cache-Control':'no-store'})


@app.post('/templates/items')
def save_template_item(target_code: str=Form(''), display_name: str=Form(...), aliases: str=Form(''),
                       abbreviation: str=Form(...), reference_ranges: str=Form(''),
                       unit: str=Form(''), alternative_units: str=Form(''), section: str=Form(...),
                       expected_revision: str=Form(...)):
    from .template_editor import save_item
    try:
        return JSONResponse(save_item(target_code=target_code, display_name=display_name, aliases=aliases,
                                      abbreviation=abbreviation,
                                      reference_ranges=reference_ranges, unit=unit,
                                      alternative_units=alternative_units, section=section,
                                      expected_revision=expected_revision))
    except ValueError as exc:
        return JSONResponse({'detail':str(exc)}, status_code=422)
    except OSError:
        return JSONResponse({'detail':'模板保存失败，请检查数据目录是否可写，原模板未被删除'},status_code=500)


@app.post('/templates/sections')
def create_template_section(section: str=Form(...), expected_revision: str=Form(...)):
    from .template_editor import save_section
    try:
        return JSONResponse(save_section(section, expected_revision))
    except ValueError as exc:
        return JSONResponse({'detail':str(exc)}, status_code=422)
    except OSError:
        return JSONResponse({'detail':'分类保存失败，请检查数据目录是否可写'}, status_code=500)

@app.post('/report/{report_id}/ocr-text')
def edit_ocr_text(request: Request, report_id: int, text: str=Form(''), action: str=Form('save')):
    if is_busy(report_id):
        return JSONResponse({'detail':'该报告正在排队或处理，请完成后再修改 OCR 文本'},status_code=409)
    if action not in {'save','save_ai','restore'}:
        return JSONResponse({'detail':'未知操作'},status_code=422)
    with connect() as con:
        report=con.execute('SELECT * FROM reports WHERE id=?',(report_id,)).fetchone()
        if not report:
            return JSONResponse({'detail':'报告不存在'},status_code=404)
        original=report['ocr_text_original'] if report['ocr_text_original'] or report['ocr_text_edited'] else report['raw_text']
        updated=original if action=='restore' else text.replace('\r\n','\n')
        if action!='restore' and not updated.strip():
            return JSONResponse({'detail':'OCR 文本不能为空'},status_code=422)
        changed=updated!=report['raw_text']
        status=report['status']
        if changed:
            con.execute('INSERT INTO ocr_text_revisions(report_id,previous_text,new_text,created_at) VALUES(?,?,?,?)',
                        (report_id,report['raw_text'],updated,now_iso()))
            status='OCR已完成' if updated.strip() else '未处理'
            con.execute('UPDATE reports SET raw_text=?,ocr_text_original=?,ocr_text_edited=?,status=?,error=? WHERE id=?',
                        (updated,original,int(updated!=original),status,'',report_id))
            con.execute('UPDATE extractions SET reviewed=0 WHERE report_id=?',(report_id,))
    queued=action=='save_ai'
    if queued:
        start_job(report_id,'llm')
    if 'application/json' in request.headers.get('accept',''):
        return JSONResponse(dict(saved=True,changed=changed,queued=queued,text=updated,
                                 edited=updated!=original,status='AI排队中' if queued else status))
    return RedirectResponse(f'/report/{report_id}',status_code=303)


@app.post('/report/{report_id}/extractions/add')
def add_extraction(request: Request, report_id: int, item_name: str=Form(...), value: str=Form(...),
                   unit: str=Form(''), after_eid: int=Form(-1)):
    if is_busy(report_id):
        return JSONResponse({'detail':'该报告正在排队或处理，请完成后再新增项目'},status_code=409)
    if not item_name.strip() or not value.strip() or is_header_name(item_name):
        return JSONResponse({'detail':'请填写真实的项目名称和结果，不能添加表头'},status_code=422)
    from .report_templates import apply_table_template
    record=normalize_record(dict(item_original=item_name.strip(),value=value.strip(),unit=ascii_unit(unit.strip()),payload_json={}))
    record=apply_table_template([record],ALL_TEMPLATE_ID)[0]
    payload=record['payload_json']
    payload.update(manual_entry=True,manual_value_verified=True)
    evidence='手动添加：'+' | '.join((item_name.strip(),value.strip(),unit.strip()))
    with connect() as con:
        report=con.execute('SELECT * FROM reports WHERE id=?',(report_id,)).fetchone()
        if not report:
            return JSONResponse({'detail':'报告不存在'},status_code=404)
        ordered=[r['id'] for r in con.execute('SELECT id FROM extractions WHERE report_id=? ORDER BY sort_order,id',(report_id,))]
        if after_eid not in {-1,0} and after_eid not in ordered:
            return JSONResponse({'detail':'插入位置已变化，请重新选择'},status_code=422)
        duplicate=con.execute('SELECT id FROM extractions WHERE report_id=? AND lower(item_standard)=?',
                              (report_id,record['item_standard'].casefold())).fetchone()
        if duplicate:
            return JSONResponse({'detail':'该项目已存在，请直接修改对应行'},status_code=409)
        index=len(ordered) if after_eid==-1 else 0 if after_eid==0 else ordered.index(after_eid)+1
        previous=ordered[index-1] if index else 0
        eid=con.execute('''INSERT INTO extractions(report_id,source_kind,category,item_original,item_standard,value,value_num,unit,
                           evidence,reviewed,payload_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                        (report_id,'manual','手动添加',item_name.strip(),record['item_standard'],value.strip(),
                         _value_num(value),record['unit'],evidence,0,json.dumps(payload,ensure_ascii=False))).lastrowid
        ordered.insert(index,eid)
        con.executemany('UPDATE extractions SET sort_order=? WHERE id=?',[(i,item_id) for i,item_id in enumerate(ordered,1)])
        con.execute("UPDATE reports SET status='待审核' WHERE id=?",(report_id,))
        item=dict(con.execute('SELECT * FROM extractions WHERE id=?',(eid,)).fetchone())
    item['display_name']=chinese_item_name(item)
    item['attention']=attention_for(item)
    if 'application/json' in request.headers.get('accept',''):
        return JSONResponse(dict(added=True,eid=eid,after_eid=previous,display_name=item['display_name'],
            html=templates.env.get_template('extraction_row.html').render(x=item),
            attention_html=templates.env.get_template('review_attention_item.html').render(x=item) if item['attention']['visible'] else ''))
    return RedirectResponse(f'/report/{report_id}',status_code=303)


@app.post("/report/{report_id}/metadata")
def metadata(report_id: int, patient_id: str=Form(""), report_type: str=Form("未分类"), profile: str=Form("generic")):
    with connect() as con:
        con.execute("UPDATE reports SET patient_id=?,report_type=?,profile=? WHERE id=?", (patient_id,report_type,profile,report_id))
        con.execute('UPDATE reports SET template_id=? WHERE id=?', (ALL_TEMPLATE_ID if profile=='表格式报告' else '',report_id))
    return RedirectResponse(f"/report/{report_id}", status_code=303)

@app.post("/extraction/{eid}/update")
def update_extraction(request: Request, eid: int, item_standard: str=Form(""), value: str=Form(""), unit: str=Form("")):
    if is_header_name(item_standard):
        return JSONResponse({'detail':'表头不能作为检验项目'},status_code=422)
    with connect() as con:
        row = con.execute("SELECT report_id,payload_json FROM extractions WHERE id=?", (eid,)).fetchone()
        if row:
            payload = json.loads(row['payload_json'] or '{}')
            payload['display_name'] = item_standard
            payload['manual_value_verified'] = True
            con.execute("UPDATE extractions SET value=?,value_num=?,unit=?,reviewed=1,payload_json=? WHERE id=?",
                        (value,_value_num(value),unit,json.dumps(payload,ensure_ascii=False),eid))
            rid = row["report_id"]
            remaining = con.execute('SELECT COUNT(*) FROM extractions WHERE report_id=? AND reviewed=0', (rid,)).fetchone()[0]
            if not remaining:
                con.execute("UPDATE reports SET status='已审核' WHERE id=?", (rid,))
        else:
            if 'application/json' in request.headers.get('accept', ''):
                return JSONResponse({'detail':'该项目不存在，请刷新页面'}, status_code=404)
            return RedirectResponse('/', status_code=303)
    if 'application/json' in request.headers.get('accept', ''):
        return JSONResponse({'reviewed':True, 'report_reviewed':not remaining})
    return RedirectResponse(f"/report/{rid}", status_code=303)

@app.post("/report/{report_id}/mark-reviewed")
def mark_reviewed(request: Request, report_id: int, eids: list[int]=Form([]), names: list[str]=Form([]), values: list[str]=Form([]), units: list[str]=Form([])):
    if any(is_header_name(name) for name in names):
        return JSONResponse({'detail':'表头不能作为检验项目'},status_code=422)
    with connect() as con:
        if not (len(eids) == len(names) == len(values) == len(units)):
            return HTMLResponse('行数据不完整，请刷新后重试。', status_code=422)
        for eid, name, value, unit in zip(eids, names, values, units):
            row = con.execute('SELECT payload_json FROM extractions WHERE id=? AND report_id=?', (eid,report_id)).fetchone()
            if row:
                payload = json.loads(row['payload_json'] or '{}')
                payload['display_name'] = name
                payload['manual_value_verified'] = True
                con.execute('UPDATE extractions SET value=?,value_num=?,unit=?,payload_json=? WHERE id=? AND report_id=?',
                            (value,_value_num(value),unit,json.dumps(payload,ensure_ascii=False),eid,report_id))
        con.execute("UPDATE extractions SET reviewed=1 WHERE report_id=?", (report_id,))
        con.execute("UPDATE reports SET status='已审核' WHERE id=?", (report_id,))
    if 'application/json' in request.headers.get('accept', ''):
        return JSONResponse({'reviewed':True, 'report_reviewed':True})
    return RedirectResponse(f"/report/{report_id}", status_code=303)

@app.post('/extraction/{eid}/delete')
def delete_extraction(eid: int):
    with connect() as con:
        row = con.execute('SELECT report_id FROM extractions WHERE id=?',(eid,)).fetchone()
        if not row:
            return JSONResponse({'detail':'该结果已不存在'},status_code=404)
        rid = row['report_id']
        if is_busy(rid):
            return JSONResponse({'detail':'该报告正在处理，请完成后再删除结果'},status_code=409)
        con.execute('DELETE FROM extractions WHERE id=?',(eid,))
        remaining = con.execute('SELECT COUNT(*),SUM(CASE WHEN reviewed=0 THEN 1 ELSE 0 END) FROM extractions WHERE report_id=?',(rid,)).fetchone()
        reviewed = bool(remaining[0] and not remaining[1])
        con.execute('UPDATE reports SET status=? WHERE id=?',('已审核' if reviewed else '待审核',rid))
    return JSONResponse({'deleted':True,'report_reviewed':reviewed})

@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={"settings": load_settings(), "auto_ocr_threads": ocr_thread_count()},
    )


@app.post('/preferences')
def preferences_save(theme: str | None=Form(None), report_sort: str | None=Form(None)):
    patch={key:value for key,value in {'theme':theme,'report_sort':report_sort}.items() if value is not None}
    try:
        return JSONResponse(save_preferences(patch))
    except ValueError as exc:
        return JSONResponse({'detail':str(exc)},status_code=422)

@app.post("/settings")
def settings_save(ollama_url: str=Form(...), ollama_model: str=Form(...), pp_device: str=Form("cpu"), max_text_chars: int=Form(12000), ocr_cpu_threads: int=Form(0,ge=0,le=256)):
    s = load_settings()
    s.ocr_cpu_threads = ocr_cpu_threads
    s.ollama_url=ollama_url; s.ollama_model=ollama_model; s.pp_device=pp_device; s.max_text_chars=max_text_chars
    save_settings(s)
    return RedirectResponse("/settings", status_code=303)

@app.get("/export/csv")
def download_csv():
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    return Response(csv_bytes(), media_type='text/csv',
                    headers={'Content-Disposition':f'attachment; filename="clinical_extractor-{stamp}.csv"',
                             'Cache-Control':'no-store'})


@app.get("/health")
def health():
    s=load_settings(); return {"ok": True, "model": s.ollama_model}

def _exit_after_response():
    time.sleep(1.5)
    from .ocr_process import OCR_PARSER
    # Stop the native child without waiting for a long-running inference lock.
    process = OCR_PARSER._process
    if process and process.is_alive():
        process.terminate()
    os._exit(0)

@app.post('/quit')
def quit_application():
    return JSONResponse({'status':'shutting_down'}, headers={'Cache-Control':'no-store'},
                        background=BackgroundTask(_exit_after_response))


def run():
    import uvicorn
    port = int(os.getenv("CLINICAL_EXTRACTOR_PORT", "8765"))
    uvicorn.run("clinical_extractor.main:app", host="127.0.0.1", port=port, reload=False)

if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    run()
