from __future__ import annotations

import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import Flask, jsonify, request
from psycopg2 import connect
from psycopg2.extras import RealDictCursor
from werkzeug.security import check_password_hash, generate_password_hash

DATABASE_URL = os.environ["DATABASE_URL"]
TOKEN_DAYS = int(os.environ.get("LISTINGTOOL_TOKEN_DAYS", "7"))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def db():
    return connect(DATABASE_URL, cursor_factory=RealDictCursor)


def init_db():
    with db() as c:
        with c.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS users(
                    id SERIAL PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    phone TEXT UNIQUE,
                    password_hash TEXT NOT NULL,
                    is_admin BOOLEAN NOT NULL DEFAULT FALSE,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tokens(
                    token_hash TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS app_config(
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )


def normalize_phone(v: str) -> str:
    raw = (v or "").strip()
    if not raw:
        return ""
    if raw.startswith("00"):
        raw = "+" + raw[2:]
    plus = raw.startswith("+")
    digits = "".join(x for x in raw if x.isdigit())
    if not (6 <= len(digits) <= 20):
        raise ValueError("手机号格式不正确。")
    if not plus and len(digits) == 11 and digits.startswith("1"):
        return "+86" + digits
    return ("+" if plus else "") + digits


def public_user(row):
    return {
        "id": int(row["id"]),
        "username": row["username"],
        "phone": row.get("phone"),
        "is_admin": bool(row["is_admin"]),
        "is_active": bool(row["is_active"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_token(user_id: int) -> str:
    token = secrets.token_urlsafe(48)
    now = datetime.now(timezone.utc)
    exp = now + timedelta(days=TOKEN_DAYS)
    with db() as c:
        with c.cursor() as cur:
            cur.execute(
                "INSERT INTO tokens(token_hash,user_id,expires_at,created_at,last_seen_at) VALUES(%s,%s,%s,%s,%s)",
                (token_hash(token), int(user_id), exp.isoformat(timespec="seconds"), now.isoformat(timespec="seconds"), now.isoformat(timespec="seconds")),
            )
    return token


def current_user_from_request():
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth[7:].strip()
    if not token:
        return None
    th = token_hash(token)
    with db() as c:
        with c.cursor() as cur:
            cur.execute(
                "SELECT t.expires_at,u.* FROM tokens t JOIN users u ON u.id=t.user_id WHERE t.token_hash=%s",
                (th,),
            )
            row = cur.fetchone()
            if not row:
                return None
            try:
                exp = datetime.fromisoformat(row["expires_at"])
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=timezone.utc)
                if exp < datetime.now(timezone.utc):
                    cur.execute("DELETE FROM tokens WHERE token_hash=%s", (th,))
                    return None
            except Exception:
                return None
            if not row["is_active"]:
                return None
            cur.execute("UPDATE tokens SET last_seen_at=%s WHERE token_hash=%s", (now_iso(), th))
            return row


def auth_required(fn):
    @wraps(fn)
    def inner(*args, **kwargs):
        u = current_user_from_request()
        if not u:
            return jsonify(error="登录已失效或用户已停用。"), 401
        request.cloud_user = u
        return fn(*args, **kwargs)
    return inner


def admin_required(fn):
    @wraps(fn)
    @auth_required
    def inner(*args, **kwargs):
        if not request.cloud_user["is_admin"]:
            return jsonify(error="需要管理员权限。"), 403
        return fn(*args, **kwargs)
    return inner


app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False
init_db()


@app.after_request
def add_headers(resp):
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    return resp


@app.get("/")
def root():
    return jsonify(ok=True, service="ListingTool Cloud User Center", version="1.1.0")


@app.get("/api/v1/health")
def health():
    return jsonify(ok=True, service="ListingTool Cloud User Center", time=now_iso())


@app.get("/api/v1/status")
def status():
    with db() as c:
        with c.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM users")
            n = int(cur.fetchone()["n"])
    return jsonify(ok=True, user_count=n, setup_required=(n == 0))


@app.post("/api/v1/bootstrap")
def bootstrap():
    data = request.get_json(silent=True) or {}
    with db() as c:
        with c.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM users")
            if int(cur.fetchone()["n"]) > 0:
                return jsonify(error="云端用户中心已经完成初始化。"), 409
            username = str(data.get("username") or "").strip()
            phone = normalize_phone(str(data.get("phone") or "")) if data.get("phone") else ""
            password = str(data.get("password") or "")
            if len(username) < 2 or len(password) < 8:
                return jsonify(error="用户名至少2位，密码至少8位。"), 400
            now = now_iso()
            cur.execute(
                "INSERT INTO users(username,phone,password_hash,is_admin,is_active,created_at,updated_at) VALUES(%s,%s,%s,TRUE,TRUE,%s,%s)",
                (username, phone or None, generate_password_hash(password), now, now),
            )
    return jsonify(ok=True)


@app.post("/api/v1/login")
def login():
    data = request.get_json(silent=True) or {}
    ident = str(data.get("login") or "").strip()
    password = str(data.get("password") or "")
    possible = [ident]
    try:
        n = normalize_phone(ident)
        if n and n not in possible:
            possible.append(n)
    except Exception:
        pass
    row = None
    with db() as c:
        with c.cursor() as cur:
            for value in possible:
                cur.execute("SELECT * FROM users WHERE lower(username)=lower(%s) OR phone=%s LIMIT 1", (value, value))
                row = cur.fetchone()
                if row:
                    break
    if not row or not row["is_active"] or not check_password_hash(row["password_hash"], password):
        return jsonify(error="手机号/用户名或密码错误。"), 401
    token = create_token(int(row["id"]))
    return jsonify(ok=True, token=token, user=public_user(row))


@app.get("/api/v1/me")
@auth_required
def me():
    return jsonify(ok=True, user=public_user(request.cloud_user))


@app.get("/api/v1/users")
@admin_required
def users_list():
    with db() as c:
        with c.cursor() as cur:
            cur.execute("SELECT * FROM users ORDER BY id")
            rows = cur.fetchall()
    return jsonify(ok=True, users=[public_user(r) for r in rows])


@app.post("/api/v1/users")
@admin_required
def users_create():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username") or "").strip()
    phone = normalize_phone(str(data.get("phone") or "")) if data.get("phone") else ""
    password = str(data.get("password") or "")
    if not username and phone:
        username = phone
    if len(username) < 2 or len(password) < 8:
        return jsonify(error="用户名/手机号至少2位，密码至少8位。"), 400
    now = now_iso()
    try:
        with db() as c:
            with c.cursor() as cur:
                cur.execute(
                    "INSERT INTO users(username,phone,password_hash,is_admin,is_active,created_at,updated_at) VALUES(%s,%s,%s,FALSE,TRUE,%s,%s) RETURNING *",
                    (username, phone or None, generate_password_hash(password), now, now),
                )
                row = cur.fetchone()
        return jsonify(ok=True, user=public_user(row))
    except Exception as e:
        if "duplicate key" in str(e).lower() or "unique" in str(e).lower():
            return jsonify(error="用户名或手机号已经存在。"), 409
        raise


@app.post("/api/v1/users/<int:user_id>/toggle")
@admin_required
def users_toggle(user_id: int):
    me = request.cloud_user
    if int(me["id"]) == int(user_id):
        return jsonify(error="不能停用当前登录的管理员账号。"), 400
    with db() as c:
        with c.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE id=%s", (user_id,))
            row = cur.fetchone()
            if not row:
                return jsonify(error="用户不存在。"), 404
            new_state = not bool(row["is_active"])
            cur.execute("UPDATE users SET is_active=%s,updated_at=%s WHERE id=%s", (new_state, now_iso(), user_id))
            if not new_state:
                cur.execute("DELETE FROM tokens WHERE user_id=%s", (user_id,))
            cur.execute("SELECT * FROM users WHERE id=%s", (user_id,))
            row = cur.fetchone()
    return jsonify(ok=True, user=public_user(row))


@app.delete("/api/v1/users/<int:user_id>")
@admin_required
def users_delete(user_id: int):
    me = request.cloud_user
    if int(me["id"]) == int(user_id):
        return jsonify(error="不能删除当前登录的管理员账号。"), 400
    with db() as c:
        with c.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE id=%s", (user_id,))
            if not cur.fetchone():
                return jsonify(error="用户不存在。"), 404
            cur.execute("DELETE FROM users WHERE id=%s", (user_id,))
    return jsonify(ok=True)


@app.get("/api/v1/version")
def version():
    with db() as c:
        with c.cursor() as cur:
            cur.execute("SELECT value FROM app_config WHERE key='version'")
            row = cur.fetchone()
    default = {
        "latest_version": "1.1.0",
        "mandatory": False,
        "download_url": "",
        "sha256": "",
        "notes": "ListingTool Cloud Sync initial release",
    }
    if row:
        try:
            default.update(json.loads(row["value"]))
        except Exception:
            pass
    return jsonify(default)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8787")))
