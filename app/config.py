from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data")).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)

APP_TITLE = os.getenv("APP_TITLE", "图片敏感词链接检测平台")
APP_PASSWORD = os.getenv("APP_PASSWORD", "").strip()
OUTBOUND_PROXY = os.getenv("OUTBOUND_PROXY", "").strip() or None
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "50"))
MAX_URLS_PER_JOB = int(os.getenv("MAX_URLS_PER_JOB", "5000"))
MAX_IMAGE_MB = int(os.getenv("MAX_IMAGE_MB", "15"))
MAX_CONCURRENT_JOBS = max(1, int(os.getenv("MAX_CONCURRENT_JOBS", "1")))
JOB_TTL_HOURS = int(os.getenv("JOB_TTL_HOURS", "24"))
