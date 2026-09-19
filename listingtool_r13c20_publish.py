#!/usr/bin/env python3
import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PATCH = ROOT / 'listingtool_r13c20.ltpatch'
META = ROOT / 'r13c20_release_meta.json'
RESULT = ROOT / 'r13c20_release_result.json'

def fail(message):
    RESULT.write_text(json.dumps({"ok": False, "error": message}, ensure_ascii=False, indent=2), encoding='utf-8')
    raise RuntimeError(message)

meta = json.loads(META.read_text(encoding='utf-8'))
patch = PATCH.read_bytes()
sha = hashlib.sha256(patch).hexdigest()
if len(patch) != int(meta['file_size']) or sha != meta['sha256']:
    fail(f"staged patch mismatch size={len(patch)} sha={sha}")

endpoint = meta['endpoint'].rstrip('/')
path = '/api/v1/signed/code-update/publish'
query = urllib.parse.urlencode({
    'patch_version': meta['patch_version'],
    'app_version': meta['app_version'],
    'notes': meta['notes'],
})
headers = {
    'Content-Type': 'application/zip',
    'Content-Length': str(len(patch)),
    'X-ListingTool-Key-Id': meta['key_id'],
    'X-ListingTool-Timestamp': meta['timestamp'],
    'X-ListingTool-Nonce': meta['nonce'],
    'X-ListingTool-Sha256': meta['sha256'],
    'X-ListingTool-Size': meta['file_size'],
    'X-ListingTool-Notes-Sha256': meta['notes_sha256'],
    'X-ListingTool-Signature': meta['signature'],
    'User-Agent': 'ListingTool-GitHub-OneShot-R13C20/1.0',
}
try:
    req = urllib.request.Request(endpoint + path + '?' + query, data=patch, headers=headers, method='POST')
    with urllib.request.urlopen(req, timeout=60) as resp:
        published = json.loads(resp.read().decode('utf-8'))
except urllib.error.HTTPError as exc:
    fail(f"publish HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')}")
except Exception as exc:
    fail(f"publish failed: {exc}")

if str(published.get('patch_version')) != meta['patch_version'] or str(published.get('sha256', '')).lower() != meta['sha256']:
    fail('publish response metadata mismatch')

try:
    with urllib.request.urlopen(urllib.request.Request(endpoint + '/api/v1/code-update/version', headers={'User-Agent': headers['User-Agent']}), timeout=30) as resp:
        version = json.loads(resp.read().decode('utf-8'))
except Exception as exc:
    fail(f"version readback failed: {exc}")

if str(version.get('patch_version')) != meta['patch_version']:
    fail(f"online patch_version mismatch: {version.get('patch_version')}")
if str(version.get('sha256', '')).lower() != meta['sha256']:
    fail(f"online sha mismatch: {version.get('sha256')}")
if int(version.get('file_size', -1)) != len(patch):
    fail(f"online size mismatch: {version.get('file_size')}")
download_url = str(version.get('download_url') or '')
if not download_url:
    fail('online download_url missing')

try:
    with urllib.request.urlopen(urllib.request.Request(download_url, headers={'User-Agent': headers['User-Agent']}), timeout=60) as resp:
        downloaded = resp.read()
except Exception as exc:
    fail(f"online patch download failed: {exc}")

download_sha = hashlib.sha256(downloaded).hexdigest()
if downloaded != patch or len(downloaded) != len(patch) or download_sha != meta['sha256']:
    fail(f"online bytes mismatch size={len(downloaded)} sha={download_sha}")

result = {
    'ok': True,
    'published': True,
    'verified_online': True,
    'patch_version': meta['patch_version'],
    'app_version': meta['app_version'],
    'sha256': meta['sha256'],
    'file_size': len(patch),
    'download_url': download_url,
    'idempotent': bool(published.get('idempotent')),
}
RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(result, ensure_ascii=False, indent=2))
