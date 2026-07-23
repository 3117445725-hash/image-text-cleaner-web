from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx

from app.config import MAX_IMAGE_MB, OUTBOUND_PROXY
from app.services.security import validate_public_http_url


@dataclass(frozen=True)
class DownloadedImage:
    content: bytes
    content_type: str
    final_url: str


class ImageDownloader:
    MAX_REDIRECTS = 5

    def __init__(self) -> None:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Cache-Control": "no-cache",
        }
        kwargs: dict = {
            "headers": headers,
            "follow_redirects": False,
            "timeout": httpx.Timeout(30.0, connect=15.0),
        }
        if OUTBOUND_PROXY:
            kwargs["proxy"] = OUTBOUND_PROXY
        self.client = httpx.Client(**kwargs)

    def close(self) -> None:
        self.client.close()

    def _open_validated_response(self, url: str):
        current_url = url
        for _ in range(self.MAX_REDIRECTS + 1):
            validate_public_http_url(current_url)
            parts = urlsplit(current_url)
            request_headers = {"Referer": f"{parts.scheme}://{parts.netloc}/"}
            request = self.client.build_request("GET", current_url, headers=request_headers)
            response = self.client.send(request, stream=True)

            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                response.close()
                if not location:
                    raise ValueError("图片链接发生重定向，但缺少目标地址")
                current_url = urljoin(current_url, location)
                continue

            response.raise_for_status()
            return response, current_url

        raise ValueError(f"图片链接重定向超过 {self.MAX_REDIRECTS} 次")

    def fetch(self, url: str) -> DownloadedImage:
        max_bytes = MAX_IMAGE_MB * 1024 * 1024
        response, final_url = self._open_validated_response(url)
        try:
            content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
            allowed_unknown_types = {"", "application/octet-stream", "binary/octet-stream"}
            if content_type not in allowed_unknown_types and not content_type.startswith("image/"):
                raise ValueError(f"返回内容不是图片：{content_type}")

            content_length = response.headers.get("content-length")
            if content_length:
                try:
                    if int(content_length) > max_bytes:
                        raise ValueError(f"图片超过 {MAX_IMAGE_MB}MB 限制")
                except ValueError as exc:
                    if "超过" in str(exc):
                        raise

            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_bytes(64 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise ValueError(f"图片超过 {MAX_IMAGE_MB}MB 限制")
                chunks.append(chunk)
        finally:
            response.close()

        content = b"".join(chunks)
        if not content:
            raise ValueError("下载到的图片为空")
        return DownloadedImage(content, content_type, final_url)
