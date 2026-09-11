const TOKEN_DAYS_DEFAULT = 7;
const PBKDF2_ITERATIONS = 120000;
let schemaPromise = null;

const SCHEMA_SQL = `
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL,
  phone TEXT,
  password_hash TEXT NOT NULL,
  is_admin INTEGER NOT NULL DEFAULT 0,
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username_nocase ON users(username COLLATE NOCASE);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_phone ON users(phone) WHERE phone IS NOT NULL AND phone <> '';
CREATE TABLE IF NOT EXISTS tokens(
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL,
  expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_tokens_user_id ON tokens(user_id);
`;

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
    },
  });
}

function nowIso() { return new Date().toISOString(); }

function normalizePhone(v) {
  let raw = String(v || "").trim();
  if (!raw) return "";
  if (raw.startsWith("00")) raw = "+" + raw.slice(2);
  const plus = raw.startsWith("+");
  const digits = (raw.match(/\d/g) || []).join("");
  if (digits.length < 6 || digits.length > 20) throw new Error("手机号格式不正确。");
  if (!plus && digits.length === 11 && digits.startsWith("1")) return "+86" + digits;
  return (plus ? "+" : "") + digits;
}

function publicUser(row) {
  return { id:Number(row.id), username:row.username, phone:row.phone || null, is_admin:Boolean(row.is_admin), is_active:Boolean(row.is_active), created_at:row.created_at, updated_at:row.updated_at };
}

function b64url(bytes) {
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}
function fromB64url(s) {
  const pad = s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4);
  const bin = atob(pad);
  const out = new Uint8Array(bin.length);
  for (let i=0;i<bin.length;i++) out[i] = bin.charCodeAt(i);
  return out;
}
async function sha256Hex(text) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(buf)].map((b)=>b.toString(16).padStart(2,"0")).join("");
}
async function hashPassword(password) {
  const salt = crypto.getRandomValues(new Uint8Array(16));
  const baseKey = await crypto.subtle.importKey("raw", new TextEncoder().encode(password), {name:"PBKDF2"}, false, ["deriveBits"]);
  const bits = await crypto.subtle.deriveBits({name:"PBKDF2",hash:"SHA-256",salt,iterations:PBKDF2_ITERATIONS}, baseKey, 256);
  return `pbkdf2_sha256$${PBKDF2_ITERATIONS}$${b64url(salt)}$${b64url(new Uint8Array(bits))}`;
}
async function verifyPassword(password, encoded) {
  try {
    const [kind,iterText,saltText,expectedText] = String(encoded||"").split("$");
    if (kind !== "pbkdf2_sha256") return false;
    const iterations = Number(iterText);
    if (!Number.isFinite(iterations) || iterations < 10000 || iterations > 1000000) return false;
    const salt = fromB64url(saltText), expected = fromB64url(expectedText);
    const baseKey = await crypto.subtle.importKey("raw", new TextEncoder().encode(password), {name:"PBKDF2"}, false, ["deriveBits"]);
    const bits = new Uint8Array(await crypto.subtle.deriveBits({name:"PBKDF2",hash:"SHA-256",salt,iterations}, baseKey, expected.length*8));
    if (bits.length !== expected.length) return false;
    let diff=0; for (let i=0;i<bits.length;i++) diff |= bits[i]^expected[i];
    return diff===0;
  } catch { return false; }
}
async function ensureSchema(env) {
  if (!schemaPromise) schemaPromise=(async()=>{ for(const sql of SCHEMA_SQL.split(";").map(x=>x.trim()).filter(Boolean)) await env.DB.prepare(sql).run(); return true; })().catch(err=>{schemaPromise=null;throw err;});
  return schemaPromise;
}
async function readJson(request) { try { return await request.json(); } catch { return {}; } }
async function createToken(env,userId) {
  const raw=crypto.getRandomValues(new Uint8Array(48)); const token=b64url(raw); const th=await sha256Hex(token);
  const days=Math.max(1,Math.min(90,Number(env.TOKEN_DAYS||TOKEN_DAYS_DEFAULT)||TOKEN_DAYS_DEFAULT)); const now=new Date(); const exp=new Date(now.getTime()+days*86400000);
  await env.DB.prepare("INSERT INTO tokens(token_hash,user_id,expires_at,created_at,last_seen_at) VALUES(?,?,?,?,?)").bind(th,Number(userId),exp.toISOString(),now.toISOString(),now.toISOString()).run();
  return token;
}
async function currentUser(env,request) {
  const auth=request.headers.get("authorization")||""; if(!auth.startsWith("Bearer ")) return null; const token=auth.slice(7).trim(); if(!token) return null; const th=await sha256Hex(token);
  const row=await env.DB.prepare("SELECT t.expires_at,u.* FROM tokens t JOIN users u ON u.id=t.user_id WHERE t.token_hash=? LIMIT 1").bind(th).first();
  if(!row) return null; if(!row.expires_at || Date.parse(row.expires_at)<Date.now()){await env.DB.prepare("DELETE FROM tokens WHERE token_hash=?").bind(th).run();return null;} if(!row.is_active) return null;
  await env.DB.prepare("UPDATE tokens SET last_seen_at=? WHERE token_hash=?").bind(nowIso(),th).run(); return row;
}
async function requireUser(env,request){const user=await currentUser(env,request);if(!user)return{response:json({error:"登录已失效或用户已停用。"},401)};return{user};}
async function requireAdmin(env,request){const auth=await requireUser(env,request);if(auth.response)return auth;if(!auth.user.is_admin)return{response:json({error:"需要管理员权限。"},403)};return auth;}

async function routeApi(request,env){
  await ensureSchema(env); const url=new URL(request.url); const path=url.pathname.replace(/\/+$/,"")||"/"; const method=request.method.toUpperCase();
  if(method==="GET"&&path==="/") return json({ok:true,service:"ListingTool Cloud User Center",mode:"Cloudflare Workers + D1"});
  if(method==="GET"&&path==="/api/v1/health") return json({ok:true,service:"ListingTool Cloud User Center",time:nowIso()});
  if(method==="GET"&&path==="/api/v1/status"){const row=await env.DB.prepare("SELECT COUNT(*) AS n FROM users").first();const n=Number(row?.n||0);return json({ok:true,user_count:n,setup_required:n===0});}
  if(method==="POST"&&path==="/api/v1/bootstrap"){
    const count=await env.DB.prepare("SELECT COUNT(*) AS n FROM users").first(); if(Number(count?.n||0)>0)return json({error:"云端用户中心已经完成初始化。"},409);
    const data=await readJson(request), username=String(data.username||"").trim(); let phone=""; try{phone=data.phone?normalizePhone(data.phone):"";}catch(e){return json({error:e.message},400);} const password=String(data.password||"");
    if(username.length<2||password.length<6)return json({error:"用户名至少2位，密码至少6位。"},400); const now=nowIso(), passwordHash=await hashPassword(password);
    try{await env.DB.prepare("INSERT INTO users(username,phone,password_hash,is_admin,is_active,created_at,updated_at) VALUES(?,?,?,?,?,?,?)").bind(username,phone||null,passwordHash,1,1,now,now).run();return json({ok:true});}catch{return json({error:"用户名或手机号已经存在。"},409);}
  }
  if(method==="POST"&&path==="/api/v1/login"){
    const data=await readJson(request), ident=String(data.login||"").trim(), password=String(data.password||""); let normalized=""; try{normalized=normalizePhone(ident);}catch{}
    const row=await env.DB.prepare("SELECT * FROM users WHERE lower(username)=lower(?) OR phone=? OR phone=? LIMIT 1").bind(ident,ident,normalized||ident).first();
    if(!row||!row.is_active||!(await verifyPassword(password,row.password_hash)))return json({error:"手机号/用户名或密码错误。"},401); const token=await createToken(env,Number(row.id)); return json({ok:true,token,user:publicUser(row)});
  }
  if(method==="GET"&&path==="/api/v1/me"){const auth=await requireUser(env,request);if(auth.response)return auth.response;return json({ok:true,user:publicUser(auth.user)});}
  if(method==="GET"&&path==="/api/v1/users"){const auth=await requireAdmin(env,request);if(auth.response)return auth.response;const result=await env.DB.prepare("SELECT * FROM users ORDER BY id").all();return json({ok:true,users:(result.results||[]).map(publicUser)});}
  if(method==="POST"&&path==="/api/v1/users"){
    const auth=await requireAdmin(env,request);if(auth.response)return auth.response;const data=await readJson(request);let username=String(data.username||"").trim(),phone="";try{phone=data.phone?normalizePhone(data.phone):"";}catch(e){return json({error:e.message},400);}const password=String(data.password||"");if(!username&&phone)username=phone;if(username.length<2||password.length<6)return json({error:"用户名/手机号至少2位，密码至少6位。"},400);const now=nowIso(),passwordHash=await hashPassword(password);
    try{const res=await env.DB.prepare("INSERT INTO users(username,phone,password_hash,is_admin,is_active,created_at,updated_at) VALUES(?,?,?,?,?,?,?)").bind(username,phone||null,passwordHash,0,1,now,now).run();const id=Number(res.meta?.last_row_id||0);const row=id?await env.DB.prepare("SELECT * FROM users WHERE id=?").bind(id).first():await env.DB.prepare("SELECT * FROM users WHERE lower(username)=lower(?) LIMIT 1").bind(username).first();return json({ok:true,user:publicUser(row)});}catch{return json({error:"用户名或手机号已经存在。"},409);}
  }
  let m=path.match(/^\/api\/v1\/users\/(\d+)\/toggle$/); if(method==="POST"&&m){const auth=await requireAdmin(env,request);if(auth.response)return auth.response;const userId=Number(m[1]);if(Number(auth.user.id)===userId)return json({error:"不能停用当前登录的管理员账号。"},400);let row=await env.DB.prepare("SELECT * FROM users WHERE id=?").bind(userId).first();if(!row)return json({error:"用户不存在。"},404);const newState=row.is_active?0:1;await env.DB.prepare("UPDATE users SET is_active=?,updated_at=? WHERE id=?").bind(newState,nowIso(),userId).run();if(!newState)await env.DB.prepare("DELETE FROM tokens WHERE user_id=?").bind(userId).run();row=await env.DB.prepare("SELECT * FROM users WHERE id=?").bind(userId).first();return json({ok:true,user:publicUser(row)});}
  m=path.match(/^\/api\/v1\/users\/(\d+)$/); if(method==="DELETE"&&m){const auth=await requireAdmin(env,request);if(auth.response)return auth.response;const userId=Number(m[1]);if(Number(auth.user.id)===userId)return json({error:"不能删除当前登录的管理员账号。"},400);const row=await env.DB.prepare("SELECT id FROM users WHERE id=?").bind(userId).first();if(!row)return json({error:"用户不存在。"},404);await env.DB.prepare("DELETE FROM tokens WHERE user_id=?").bind(userId).run();await env.DB.prepare("DELETE FROM users WHERE id=?").bind(userId).run();return json({ok:true});}
  if(method==="GET"&&path==="/api/v1/version")return json({latest_version:String(env.LATEST_VERSION||"1.1.0"),mandatory:String(env.UPDATE_MANDATORY||"false").toLowerCase()==="true",download_url:String(env.UPDATE_DOWNLOAD_URL||""),sha256:String(env.UPDATE_SHA256||""),notes:String(env.UPDATE_NOTES||"ListingTool Cloudflare zero-cost user center")});
  return json({error:"Not Found"},404);
}

export default { async fetch(request,env){ if(request.method==="OPTIONS")return new Response(null,{status:204,headers:{allow:"GET,POST,DELETE,OPTIONS"}}); try{return await routeApi(request,env);}catch(e){console.error(e);return json({error:"服务器内部错误。"},500);} } };
export { normalizePhone, hashPassword, verifyPassword };
