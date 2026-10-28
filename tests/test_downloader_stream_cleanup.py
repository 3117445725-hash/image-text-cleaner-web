"""HTTP failure must close streamed responses to avoid connection exhaustion."""
import unittest
from unittest.mock import patch

import httpx

from app.services.downloader import ImageDownloader


class Stream(httpx.SyncByteStream):
    def __init__(self, payload: bytes):
        self.payload = payload
        self.closed = False

    def __iter__(self):
        yield self.payload

    def close(self):
        self.closed = True


class DownloaderStreamCleanupTests(unittest.TestCase):
    def make_downloader(self, handler):
        downloader = ImageDownloader()
        downloader.client.close()
        downloader.client = httpx.Client(transport=httpx.MockTransport(handler))
        self.addCleanup(downloader.close)
        return downloader

    def test_404_closes_stream_before_raising(self):
        responses = []
        def handler(request):
            response = httpx.Response(404, request=request, stream=Stream(b"not found"))
            responses.append(response)
            return response
        downloader = self.make_downloader(handler)
        with patch("app.services.downloader.validate_public_http_url"):
            with self.assertRaises(httpx.HTTPStatusError):
                downloader.fetch("https://images.example.invalid/notfound.png")
        self.assertEqual(len(responses), 1)
        self.assertTrue(responses[0].is_closed, "stream leaked after 404")

    def test_503_closes_stream_before_raising(self):
        responses = []
        def handler(request):
            response = httpx.Response(503, request=request, stream=Stream(b"busy"))
            responses.append(response)
            return response
        downloader = self.make_downloader(handler)
        with patch("app.services.downloader.validate_public_http_url"):
            with self.assertRaises(httpx.HTTPStatusError):
                downloader.fetch("https://images.example.invalid/busy.png")
        self.assertTrue(responses[0].is_closed, "stream leaked after 503")

    def test_redirect_to_404_closes_both_streams(self):
        responses = []
        def handler(request):
            if request.url.path == "/start":
                response = httpx.Response(302, request=request, headers={"location": "/missing"}, stream=Stream(b""))
            else:
                response = httpx.Response(404, request=request, stream=Stream(b"missing"))
            responses.append(response)
            return response
        downloader = self.make_downloader(handler)
        with patch("app.services.downloader.validate_public_http_url"):
            with self.assertRaises(httpx.HTTPStatusError):
                downloader.fetch("https://images.example.invalid/start")
        self.assertEqual(len(responses), 2)
        self.assertTrue(all(response.is_closed for response in responses))

    def test_429_closes_stream_before_raising(self):
        responses = []
        def handler(request):
            response = httpx.Response(429, request=request, stream=Stream(b"rate limited"))
            responses.append(response)
            return response
        downloader = self.make_downloader(handler)
        with patch("app.services.downloader.validate_public_http_url"):
            with self.assertRaises(httpx.HTTPStatusError):
                downloader.fetch("https://images.example.invalid/rate.png")
        self.assertTrue(responses[0].is_closed)

    def test_success_stream_is_closed_after_fetch(self):
        responses = []
        def handler(request):
            response = httpx.Response(200, request=request, headers={"content-type": "image/png"}, stream=Stream(b"image bytes"))
            responses.append(response)
            return response
        downloader = self.make_downloader(handler)
        with patch("app.services.downloader.validate_public_http_url"):
            result = downloader.fetch("https://images.example.invalid/ok.png")
        self.assertEqual(result.content, b"image bytes")
        self.assertTrue(responses[0].is_closed)

    def test_redirect_stream_is_closed_before_next_request(self):
        responses = []
        def handler(request):
            if request.url.path == "/start":
                response = httpx.Response(302, request=request, headers={"location": "/final"})
            else:
                self.assertTrue(responses[0].is_closed, "redirect stream remained open")
                response = httpx.Response(200, request=request, headers={"content-type": "image/png"}, stream=Stream(b"ok"))
            responses.append(response)
            return response
        downloader = self.make_downloader(handler)
        with patch("app.services.downloader.validate_public_http_url"):
            result = downloader.fetch("https://images.example.invalid/start")
        self.assertEqual(result.final_url, "https://images.example.invalid/final")
        self.assertTrue(all(response.is_closed for response in responses))

    def test_redirect_without_location_closes_stream(self):
        responses = []
        def handler(request):
            response = httpx.Response(302, request=request)
            responses.append(response)
            return response
        downloader = self.make_downloader(handler)
        with patch("app.services.downloader.validate_public_http_url"):
            with self.assertRaisesRegex(ValueError, "缺少目标地址"):
                downloader.fetch("https://images.example.invalid/redirect")
        self.assertTrue(responses[0].is_closed)


if __name__ == "__main__":
    unittest.main()
