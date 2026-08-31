from __future__ import annotations

import hmac
import shutil
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import (
    APP_PASSWORD,
    APP_TITLE,
    DATA_DIR,
    JOB_TTL_HOURS,
    MAX_CONCURRENT_JOBS,
    MAX_IMAGE_MB,
    MAX_IMAGE_PIXELS,
    MAX_UPLOAD_MB,
    MAX_URLS_PER_JOB,
    OCR_CPU_MEM_ARENA,
    OCR_INTER_OP_THREADS,
    OCR_INTRA_OP_THREADS,
    OCR_PREWARM,
)
from app.models import job_store
from app.services.excel import process_workbook
from app.services.matcher import parse_keywords
from app.services.ocr import ocr_service

job_slots = threading.Semaphore(MAX_CONCURRENT_JOBS)


@asynccontextmanager
async def lifespan(_: FastAPI):
    job_store.recover_interrupted()
    cleanup_old_jobs()
    if OCR_PREWARM:
        ocr_service.warmup()
    yield


app = FastAPI(title=APP_TITLE, docs_url=None, redoc_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")


def check_password(value: str | None) -> None:
    if APP_PASSWORD:
        supplied = value or ""
        if not hmac.compare_digest(supplied, APP_PASSWORD):
            raise HTTPException(status_code=401, detail="访问密码不正确")


def cleanup_old_jobs() -> None:
    cutoff = time.time() - JOB_TTL_HOURS * 3600
    try:
        entries = list(DATA_DIR.iterdir())
    except OSError:
        return
    for path in entries:
        try:
            if path.is_dir() and path.stat().st_mtime < cutoff:
                shutil.rmtree(path, ignore_errors=True)
                job_store.remove(path.name)
        except OSError:
            continue


def run_job(
    job_id: str,
    input_path: Path,
    output_path: Path,
    log_path: Path,
    keywords: list[str],
    match_mode: str,
    case_sensitive: bool,
    enhanced_ocr: bool,
) -> None:
    acquired = False
    try:
        job_store.update(job_id, status="queued", message="任务已进入队列，等待 OCR 处理")
        job_slots.acquire()
        acquired = True
        job_store.update(job_id, status="running", message="正在读取 Excel")

        def progress(processed: int, total: int, matched: int, failed: int, current_url: str) -> None:
            percent = 5 + int((processed / max(total, 1)) * 88)
            job_store.update(
                job_id,
                status="running",
                message=f"正在识别第 {processed}/{total} 张图片",
                progress=min(percent, 93),
                total_links=total,
                processed_links=processed,
                matched_links=matched,
                failed_links=failed,
            )

        total, matched, failed, changed = process_workbook(
            input_path,
            output_path,
            log_path,
            keywords=keywords,
            match_mode=match_mode,
            case_sensitive=case_sensitive,
            enhanced_ocr=enhanced_ocr,
            progress_callback=progress,
        )
        job_store.update(
            job_id,
            status="completed",
            message="处理完成",
            progress=100,
            total_links=total,
            processed_links=total,
            matched_links=matched,
            failed_links=failed,
            changed_cells=changed,
            output_file=str(output_path),
            log_file=str(log_path),
            error=None,
        )
    except Exception as exc:  # noqa: BLE001
        job_store.update(job_id, status="failed", message="处理失败", error=str(exc))
    finally:
        if acquired:
            job_slots.release()


def start_job_thread(*args) -> None:
    thread = threading.Thread(target=run_job, args=args, daemon=True, name=f"ocr-job-{args[0][:8]}")
    thread.start()


@app.get("/")
def index() -> FileResponse:
    cleanup_old_jobs()
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/api/config")
def config() -> dict:
    return {
        "title": APP_TITLE,
        "password_required": bool(APP_PASSWORD),
        "max_upload_mb": MAX_UPLOAD_MB,
    }


@app.post("/api/jobs", status_code=202)
async def create_job(
    file: UploadFile = File(...),
    keywords_raw: str = Form(...),
    match_mode: str = Form("whole"),
    case_sensitive: bool = Form(False),
    enhanced_ocr: bool = Form(False),
    x_app_password: str | None = Header(default=None),
) -> dict:
    check_password(x_app_password)
    cleanup_old_jobs()

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".xlsx", ".xlsm"}:
        raise HTTPException(status_code=400, detail="仅支持 .xlsx 或 .xlsm 文件")
    if match_mode not in {"whole", "substring"}:
        raise HTTPException(status_code=400, detail="匹配方式无效")

    keywords = parse_keywords(keywords_raw)
    if not keywords:
        raise HTTPException(status_code=400, detail="请至少输入一个检测关键词")
    if len(keywords) > 100:
        raise HTTPException(status_code=400, detail="单次最多输入100个关键词")

    job_id = uuid.uuid4().hex
    job_dir = DATA_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=False)
    input_path = job_dir / f"input{suffix}"
    output_path = job_dir / f"处理结果_已清除敏感词链接{suffix}"
    log_path = job_dir / "OCR识别记录.csv"

    max_bytes = MAX_UPLOAD_MB * 1024 * 1024
    size = 0
    try:
        with input_path.open("wb") as output:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(status_code=413, detail=f"文件不能超过 {MAX_UPLOAD_MB}MB")
                output.write(chunk)
        if size == 0:
            raise HTTPException(status_code=400, detail="上传文件为空")
        with input_path.open("rb") as handle:
            if handle.read(4)[:2] != b"PK":
                raise HTTPException(status_code=400, detail="文件不是有效的 Excel 工作簿")
    except Exception:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise
    finally:
        await file.close()

    job_store.create(job_id)
    start_job_thread(
        job_id,
        input_path,
        output_path,
        log_path,
        keywords,
        match_mode,
        case_sensitive,
        enhanced_ocr,
    )
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str, x_app_password: str | None = Header(default=None)) -> dict:
    check_password(x_app_password)
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    return job.to_dict()


@app.get("/api/jobs/{job_id}/download/{kind}")
def download(job_id: str, kind: str, x_app_password: str | None = Header(default=None)) -> FileResponse:
    check_password(x_app_password)
    job = job_store.get(job_id)
    if not job or job.status != "completed":
        raise HTTPException(status_code=404, detail="结果不存在或尚未完成")
    path_str = job.output_file if kind == "excel" else job.log_file if kind == "log" else None
    if not path_str:
        raise HTTPException(status_code=404, detail="文件不存在")
    path = Path(path_str)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="文件已过期")
    if kind == "excel":
        media_type = (
            "application/vnd.ms-excel.sheet.macroEnabled.12"
            if path.suffix.lower() == ".xlsm"
            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    else:
        media_type = "text/csv; charset=utf-8"
    return FileResponse(path, filename=path.name, media_type=media_type)


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "performance": {
            **ocr_service.runtime_info(),
            "prewarm_enabled": OCR_PREWARM,
            "max_concurrent_jobs": MAX_CONCURRENT_JOBS,
            "max_upload_mb": MAX_UPLOAD_MB,
            "max_urls_per_job": MAX_URLS_PER_JOB,
            "max_image_mb": MAX_IMAGE_MB,
            "max_image_pixels": MAX_IMAGE_PIXELS,
            "data_dir": str(DATA_DIR),
        },
    }
