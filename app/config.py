from __future__ import annotations

import os
from pathlib import Path


def _env_int(name: str, default: int, *, minimum: int = 1, maximum: int | None = None) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"环境变量 {name} 必须是整数，当前值：{raw!r}") from exc
    if value < minimum:
        raise RuntimeError(f"环境变量 {name} 不能小于 {minimum}")
    if maximum is not None and value > maximum:
        raise RuntimeError(f"环境变量 {name} 不能大于 {maximum}")
    return value


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"环境变量 {name} 必须是布尔值（1/0、true/false）")


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data")).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)

APP_TITLE = os.getenv("APP_TITLE", "图片敏感词链接检测平台").strip() or "图片敏感词链接检测平台"
APP_PASSWORD = os.getenv("APP_PASSWORD", "").strip()
OUTBOUND_PROXY = os.getenv("OUTBOUND_PROXY", "").strip() or None
MAX_UPLOAD_MB = _env_int("MAX_UPLOAD_MB", 50, maximum=500)
MAX_URLS_PER_JOB = _env_int("MAX_URLS_PER_JOB", 5000, maximum=100_000)
MAX_IMAGE_MB = _env_int("MAX_IMAGE_MB", 15, maximum=100)
MAX_IMAGE_PIXELS = _env_int("MAX_IMAGE_PIXELS", 20_000_000, minimum=1_000_000, maximum=80_000_000)
MAX_CONCURRENT_JOBS = _env_int("MAX_CONCURRENT_JOBS", 1, maximum=16)
JOB_TTL_HOURS = _env_int("JOB_TTL_HOURS", 24, maximum=24 * 30)

# OCR performance tuning. Defaults remain portable; the Windows launcher overrides them for the local workstation.
OCR_INTRA_OP_THREADS = _env_int("OCR_INTRA_OP_THREADS", max(1, min(os.cpu_count() or 1, 6)), maximum=64)
OCR_INTER_OP_THREADS = _env_int("OCR_INTER_OP_THREADS", 1, maximum=16)
OCR_CPU_MEM_ARENA = _env_bool("OCR_CPU_MEM_ARENA", True)
OCR_PREWARM = _env_bool("OCR_PREWARM", False)
