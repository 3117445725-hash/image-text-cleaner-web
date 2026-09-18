#!/usr/bin/env python3
import base64, hashlib, json, os, threading, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STATUS={"ok":False,"state":"starting","release_id":os.environ.get("LT_RELEASE_ID","")}

def sha256(b):
    return hashlib.sha256(b).hexdigest()

def patch_bytes():
    parts=[(k,v) for k,v in os.environ.items() if k.startswith("LT_PATCH_B64_")]
    if not parts:
        raise RuntimeError("missing patch chunks")
    return base64.b64decode("".join(v for k,v in sorted(parts)))

def req_json(req, timeout=120):
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError("HTTP %s: %s"%(e.code,e.read().decode(errors="replace")))

def publish():
    try:
        data=patch_bytes()
        expected=os.environ["LT_EXPECTED_SHA256"].lower()
        if sha256(data)!=expected:
            raise RuntimeError("patch sha mismatch")
        publish_url=os.environ["LT_PUBLISH_URL"]
        headers=json.loads(os.environ["LT_HEADERS_JSON"])
        STATUS.update(state="publishing",sha256=expected,file_size=len(data))
        result=req_json(urllib.request.Request(publish_url,data=data,headers=headers,method="POST"))
        STATUS.update(state="verifying")
        version_url=os.environ["LT_VERSION_URL"]
        version=req_json(urllib.request.Request(version_url,headers={"User-Agent":"ListingTool-Release-Relay/1.0"}))
        if str(version.get("patch_version"))!=os.environ["LT_PATCH_VERSION"] or str(version.get("sha256","")).lower()!=expected or int(version.get("file_size",-1))!=len(data):
            raise RuntimeError("online metadata mismatch")
        dl=str(version.get("download_url") or "")
        if not dl:
            raise RuntimeError("missing download url")
        with urllib.request.urlopen(urllib.request.Request(dl,headers={"User-Agent":"ListingTool-Release-Relay/1.0"}),timeout=120) as r:
            back=r.read(8*1024*1024+1)
        if back!=data or sha256(back)!=expected:
            raise RuntimeError("online bytes mismatch")
        STATUS.update(ok=True,state="complete",verified_online=True,download_url=dl,idempotent=bool(result.get("idempotent")))
    except Exception as e:
        STATUS.update(ok=False,state="failed",error=str(e))

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body=json.dumps(STATUS,ensure_ascii=False).encode("utf-8")
        self.send_response(200 if STATUS.get("ok") else 202)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Cache-Control","no-store")
        self.end_headers()
        self.wfile.write(body)
    def log_message(self,*args):
        pass

if __name__=="__main__":
    threading.Thread(target=publish,daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0",int(os.environ.get("PORT","10000"))),Handler).serve_forever()
