from __future__ import annotations

import gc
from dataclasses import dataclass
from threading import Lock
from typing import Iterator

import cv2
import numpy as np
from rapidocr import RapidOCR

from app.config import (
    MAX_IMAGE_PIXELS,
    OCR_CPU_MEM_ARENA,
    OCR_INTER_OP_THREADS,
    OCR_INTRA_OP_THREADS,
)


@dataclass(frozen=True)
class OCRResult:
    text: str
    lines: tuple[str, ...]
    average_score: float | None


class OCRService:
    def __init__(self) -> None:
        self._engine: RapidOCR | None = None
        self._lock = Lock()

    def _get_engine(self) -> RapidOCR:
        if self._engine is None:
            with self._lock:
                if self._engine is None:
                    self._engine = RapidOCR(
                        params={
                            "EngineConfig.onnxruntime.intra_op_num_threads": OCR_INTRA_OP_THREADS,
                            "EngineConfig.onnxruntime.inter_op_num_threads": OCR_INTER_OP_THREADS,
                            "EngineConfig.onnxruntime.enable_cpu_mem_arena": OCR_CPU_MEM_ARENA,
                        }
                    )
        return self._engine

    def warmup(self) -> None:
        engine = self._get_engine()
        sample = np.full((64, 256, 3), 255, dtype=np.uint8)
        with self._lock:
            engine(sample, use_det=True, use_cls=True, use_rec=True)

    def runtime_info(self) -> dict[str, int | bool]:
        return {
            "engine_ready": self._engine is not None,
            "intra_op_threads": OCR_INTRA_OP_THREADS,
            "inter_op_threads": OCR_INTER_OP_THREADS,
            "cpu_mem_arena": OCR_CPU_MEM_ARENA,
        }

    @staticmethod
    def _decode(content: bytes) -> np.ndarray:
        data = np.frombuffer(content, dtype=np.uint8)
        image = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("Cannot decode image")
        h, w = image.shape[:2]
        pixels = h * w
        if pixels > MAX_IMAGE_PIXELS:
            scale = (MAX_IMAGE_PIXELS / pixels) ** 0.5
            image = cv2.resize(
                image,
                (max(1, int(w * scale)), max(1, int(h * scale))),
                interpolation=cv2.INTER_AREA,
            )
        return image

    @staticmethod
    def _variants(image: np.ndarray, enhanced: bool) -> Iterator[np.ndarray]:
        yield image
        if not enhanced:
            return

        h, w = image.shape[:2]
        if max(h, w) < 1600:
            scale = min(2.0, 1600 / max(h, w))
            yield cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        yield cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

        yield cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
        yield cv2.rotate(image, cv2.ROTATE_180)
        yield cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)

    def recognize(self, content: bytes, *, enhanced: bool = False) -> OCRResult:
        image = self._decode(content)
        engine = self._get_engine()
        lines: list[str] = []
        scores: list[float] = []
        seen: set[str] = set()

        for variant in self._variants(image, enhanced):
            try:
                with self._lock:
                    result = engine(variant, use_det=True, use_cls=True, use_rec=True)
                txts = tuple(getattr(result, "txts", ()) or ())
                result_scores = tuple(getattr(result, "scores", ()) or ())
                for index, raw_text in enumerate(txts):
                    text = str(raw_text).strip()
                    key = " ".join(text.casefold().split())
                    if text and key not in seen:
                        seen.add(key)
                        lines.append(text)
                        if index < len(result_scores):
                            try:
                                scores.append(float(result_scores[index]))
                            except (TypeError, ValueError):
                                pass
            finally:
                if variant is not image:
                    del variant

        avg = sum(scores) / len(scores) if scores else None
        gc.collect(0)
        return OCRResult("\n".join(lines), tuple(lines), avg)


ocr_service = OCRService()
