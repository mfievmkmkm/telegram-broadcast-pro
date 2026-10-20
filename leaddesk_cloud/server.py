# -*- coding: utf-8 -*-
"""LeadDesk Cloud: guarded responses to individual PUBLIC contractor requests."""
import asyncio
import csv
import hmac
import html
import io
import json
import os
import re
import sqlite3
import time
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from aiohttp import web, BasicAuth

DATA=Path(os.getenv("LEADDESK_DATA_DIR", "/data"))
DATA.mkdir(parents=True,exist_ok=True)
DB=DATA/"leaddesk.sqlite3"
PATTERN=re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{4,31}$")
COLUMNS=("username","project","service","message","source_url","posted_on")
MAX_DAILY=5
MAX_HOURLY=3
MIN_INTERVAL=45
MAX_AGE=45

def db():
    con=sqlite3.connect(DB,timeout=20)
    con.row_factory=sqlite3.Row
    con.execute("PRAGMA busy_timeout=20000")
    return con

def initialize():
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE,
            project TEXT NOT NULL, service TEXT NOT NULL,
            message TEXT NOT NULL, source_url TEXT NOT NULL,
            posted_on TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'review',
            created_at REAL NOT NULL, sent_at REAL, attempted_at REAL, error TEXT NOT NULL DEFAULT ''
        )""")
        # Upgrade older SQLite volume databases without losing contacts/history.
        fields={row[1] for row in c.execute("PRAGMA table_info(leads)").fetchall()}
        if "attempted_at" not in fields:
            c.execute("ALTER TABLE leads ADD COLUMN attempted_at REAL")
        c.execute("CREATE TABLE IF NOT EXISTS kv (name TEXT PRIMARY KEY, value TEXT NOT NULL)")
        c.execute("INSERT OR IGNORE INTO kv VALUES('enabled','0')")
        c.commit()

def scalar(sql,args=()):
    with db() as c:
        r=c.execute(sql,args).fetchone()
        return r[0] if r else 0

def enabled():
    return scalar("SELECT value FROM kv WHERE name='enabled'")=="1"

def configured():
    try:
        return (bool(int(os.getenv("TG_API_ID","0"))) and
            bool(re.fullmatch(r"[0-9a-fA-F]{32}",os.getenv("TG_API_HASH",""))) and
            bool(os.getenv("TG_STRING_SESSION","").strip()))
    except ValueError:
        return False

def valid(row):
    row=dict(row)
    u=str(row.get("username","")).strip()
    if u.startswith("https://t.me/"):u=u[len("https://t.me/"):]
    u=u.strip("/").lstrip("@").lower()
    if not PATTERN.fullmatch(u):return "Укажи корректный публичный @username"
    text=str(row.get("message","")).strip()
    if not (20<=len(text)<=1800):return "Нужен личный текст длиной 20–1800 символов"
    link=str(row.get("source_url","")).strip()
    parsed=urlsplit(link)
    if parsed.scheme!="https" or not parsed.hostname or parsed.username or parsed.password:
        return "Требуется HTTPS-ссылка на публичный запрос заказчика"
    if parsed.hostname.lower() in ("t.me","www.t.me"):
        parts=[x for x in parsed.path.split("/") if x]
        if len(parts)!=2 or not parts[1].isdigit():
            return "Для Telegram нужна прямая ссылка t.me/канал/номер_поста"
    elif len(parsed.path.strip("/"))<5:
        return "Укажи прямую ссылку на заявку, а не главную страницу"
    try:
        age=(date.today()-date.fromisoformat(str(row.get("posted_on","")))).days
        if age<0 or age>MAX_AGE:return "Заявка старше 45 дней либо её дата в будущем"
    except ValueError:return "Дата заявки должна иметь формат ГГГГ-ММ-ДД"
    return None

def norm(row):
    u=str(row.get("username","")).strip()
    if u.startswith("https://t.me/"):u=u[len("https://t.me/"):]
    u=u.strip("/").lstrip("@").lower()
    return dict(username=u,project=str(row.get("project",""))[:140],
        service=str(row.get("service",""))[:80],message=str(row.get("message",""))[:1800],
        source_url=str(row.get("source_url",""))[:800],posted_on=str(row.get("posted_on",""))[:12])

def e(s):
    return html.escape(str(s),quote=True)

def counts():
    # Count ATTEMPTS, not just successes, to prevent rapid failed DMs.
    now=time.time()
    with db() as c:
        d=c.execute("SELECT count(*) FROM leads WHERE attempted_at>?",(now-86400,)).fetchone()[0]
        h=c.execute("SELECT count(*) FROM leads WHERE attempted_at>?",(now-3600,)).fetchone()[0]
        last=c.execute("SELECT max(attempted_at) FROM leads").fetchone()[0] or 0
    return d,h,last

def html_home():
    with db() as c:
        rows=c.execute("SELECT * FROM leads ORDER BY id DESC LIMIT 350").fetchall()
    d,h,last=counts()
    items=[]
    for r in rows:
        rid=int(r["id"]); status=r["status"]
        err=valid(r) if status in ("review","approved") else None
        controls=""
        if status in ("review","approved"):
            controls=f'<form method="post" action="/approve"><input type="hidden" name="id" value="{rid}"><button>Подтвердить заявку</button></form>'
        controls+=f'<form method="post" action="/save"><input type="hidden" name="id" value="{rid}"><textarea name="message" rows="3" maxlength="1800">{e(r["message"])}</textarea><button>Сохранить текст (снять одобрение)</button></form>'
        if status=="sending":
            controls+='<div class="warn">Отправка могла выполниться до сбоя. Сначала проверь чат вручную; автоматического повтора нет.</div>'
        items.append(f'<article><header><b>@{e(r["username"])}</b> <small>{e(status)}</small> <a target="_blank" rel="noopener noreferrer" href="{e(r["source_url"]) if str(r["source_url"]).startswith("https://") else ""}">Открыть объявление ↗</a></header><div class="sub">{e(r["project"])} · {e(r["service"])} · {e(r["posted_on"])}</div><p>{e(r["error"] or err or "")}</p>{controls}</article>')
    auth="Подключён" if configured() else "Не подключён: TG_API_ID, TG_API_HASH и TG_STRING_SESSION задаются в Railway Variables"
    state="ЗАПУЩЕНА" if enabled() else "ОСТАНОВЛЕНА"
    return f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>LeadDesk Cloud</title><style>
    *{{box-sizing:border-box}}body{{margin:0;background:#0b1220;color:#e6eefc;font:15px system-ui,Arial}}main{{max-width:1090px;margin:35px auto;padding:0 16px}}h1{{font-size:29px;margin-bottom:5px}}.sub,small{{color:#a1b3ce}}.top{{display:flex;gap:16px;flex-wrap:wrap;align-items:center;margin:15px 0 25px}}.panel,article{{padding:18px;border:1px solid #293b53;background:#172338;border-radius:13px;margin:14px 0}}button{{border:0;border-radius:8px;background:#347cf0;color:#fff;padding:11px 14px;cursor:pointer;font-weight:650}}button:hover{{background:#5795ff}}input,textarea{{display:block;width:100%;padding:10px;margin:9px 0;background:#0b1829;color:#f4f8ff;border:1px solid #354960;border-radius:7px}}textarea{{resize:vertical}}input[type=file]{{padding:7px}}input[type=checkbox]{{width:auto;display:inline}}form{{display:inline-block;vertical-align:top;margin:5px 9px 5px 0}}form:has(textarea){{display:block}}form:has(textarea) button{{background:#415674}}a{{color:#82baff}}article header{{display:flex;gap:20px;align-items:center;flex-wrap:wrap}}.warn{{color:#ffcc8f}}.red{{background:#af4658}}.ok{{color:#91dec2}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}@media(max-width:660px){{.grid{{grid-template-columns:1fr}}}}
    </style></head><body><main>
    <h1>LeadDesk Cloud</h1><div class="sub">Индивидуальные отклики на опубликованные заказы · без холодных массовых рассылок</div>
    <div class="panel"><div class="top"><b>Очередь: {state}</b><span>Telegram: {e(auth)}</span><span>Попыток: {d}/5 за 24 ч · {h}/3 за час</span></div>
    <form method="post" action="/start"><label><input type="checkbox" required name="confirm" value="yes"> Я лично проверил публичные запросы и одобрил сообщения</label><button>Запустить одобренную очередь</button></form>
    <form method="post" action="/stop"><button class="red">Остановить очередь</button></form>
    <p class="sub">При первом запуске отправка выключена. Выполняется не более 5 попыток в сутки и 3 в час, пауза от 45 секунд. Ограничения Telegram не обходятся.</p></div>
    <div class="grid"><section class="panel"><h3>Загрузить подборку</h3><form method="post" action="/upload" enctype="multipart/form-data"><input name="file" type="file" accept=".json,.csv" required><button>Импортировать файл</button></form><p class="sub">JSON список или {{ "leads": [...] }} либо CSV. Поля: username, project, service, message, source_url, posted_on.</p></section>
    <section class="panel"><h3>Добавить заявку</h3><form method="post" action="/add">
    <input name="username" placeholder="@username" required maxlength="80"><input name="project" placeholder="Название задания" required maxlength="140">
    <input name="service" placeholder="Услуга: Telegram-бот / дизайн" maxlength="80">
    <input name="source_url" placeholder="Прямая ссылка на объявление" required>
    <input name="posted_on" type="date" required><textarea name="message" rows="4" placeholder="Индивидуальное сообщение" required maxlength="1800"></textarea>
    <button>Добавить на проверку</button></form></section></div>
    <h2>Заявки ({len(rows)})</h2>{''.join(items) if items else '<p>Пока нет контактов — импортируй CSV/JSON.</p>'}
    </main></body></html>'''

def authorize(request):
    secret=os.getenv("ADMIN_PASSWORD","")
    if len(secret)<16:
        raise web.HTTPServiceUnavailable(text="Сервис защищён. Сначала установи ADMIN_PASSWORD (16+ символов) в Railway Variables.")
    authorization=request.headers.get("Authorization","")
    try:
        basic=BasicAuth.decode(authorization)
        good=basic.login=="admin" and hmac.compare_digest(basic.password,secret)
    except ValueError:
        good=False
    if not good:
        raise web.HTTPUnauthorized(headers={"WWW-Authenticate":'Basic realm="LeadDesk private console"'})
    if request.method=="POST":
        origin=request.headers.get("Origin","")
        referer=request.headers.get("Referer","")
        value=origin or referer
        parsed=urlsplit(value)
        if parsed.hostname!=request.host.split(":")[0]:
            raise web.HTTPForbidden(text="Cross-origin write denied")
    return True

@web.middleware
async def middleware(request, handler):
    if request.path=="/health":
        return await handler(request)
    authorize(request)
    reply=await handler(request)
    reply.headers["Cache-Control"]="no-store"
    reply.headers["X-Content-Type-Options"]="nosniff"
    reply.headers["X-Frame-Options"]="DENY"
    reply.headers["Content-Security-Policy"]="default-src 'none';style-src 'unsafe-inline';form-action 'self';base-uri 'none';frame-ancestors 'none'"
    return reply

def redirect():
    raise web.HTTPSeeOther("/")

async def home(request):
    return web.Response(text=html_home(),content_type="text/html")

async def health(request):
    return web.Response(text="ok")

async def upload(request):
    data=await request.post()
    file=data.get("file")
    if not file or not hasattr(file,"file"):
        raise web.HTTPBadRequest(text="Нужен CSV/JSON")
    content=file.file.read(180_000)
    if len(content)>=180_000:raise web.HTTPRequestEntityTooLarge(max_size=180000,actual_size=len(content))
    try:
        if str(file.filename).lower().endswith(".json"):
            obj=json.loads(content.decode("utf-8-sig"))
            rows=obj.get("leads",[]) if isinstance(obj,dict) else obj
        elif str(file.filename).lower().endswith(".csv"):
            rows=list(csv.DictReader(io.StringIO(content.decode("utf-8-sig"))))
        else:raise ValueError()
        if not isinstance(rows,list) or len(rows)>200:raise ValueError()
    except (UnicodeDecodeError,ValueError,json.JSONDecodeError):
        raise web.HTTPBadRequest(text="Некорректный JSON/CSV, максимум 200 строк")
    add_rows(rows)
    redirect()

def add_rows(rows):
    with db() as c:
        for row in rows:
            if not isinstance(row,dict):continue
            row=norm(row)
            if not PATTERN.fullmatch(row["username"]):continue
            # Duplicate identities never automatically overwrite approvals/history.
            c.execute("""INSERT OR IGNORE INTO leads(username,project,service,message,source_url,posted_on,created_at)
              VALUES(?,?,?,?,?,?,?)""",(row["username"],row["project"],row["service"],row["message"],
                row["source_url"],row["posted_on"],time.time()))
        c.commit()

async def add(request):
    raw=await request.post()
    add_rows([raw])
    redirect()

async def save(request):
    form=await request.post()
    message=str(form.get("message","")).strip()
    if not 20<=len(message)<=1800:raise web.HTTPBadRequest(text="Сообщение 20–1800 символов")
    with db() as c:
        c.execute("UPDATE leads SET message=?,status='review' WHERE id=? AND status IN ('review','approved')",
                  (message,int(form.get("id",0))))
        c.commit()
    redirect()

async def approve(request):
    form=await request.post()
    with db() as c:
        row=c.execute("SELECT * FROM leads WHERE id=? AND status IN ('review','approved')",(int(form.get("id",0)),)).fetchone()
        if not row:raise web.HTTPBadRequest(text="Недоступно")
        error=valid(row)
        if error:raise web.HTTPBadRequest(text=error)
        c.execute("UPDATE leads SET status='approved',error='' WHERE id=?",(row["id"],))
        c.commit()
    redirect()

async def start(request):
    form=await request.post()
    if form.get("confirm")!="yes":raise web.HTTPBadRequest(text="Требуется подтверждение")
    with db() as c:
        c.execute("UPDATE leads SET status='queued' WHERE status='approved'")
        c.execute("UPDATE kv SET value='1' WHERE name='enabled'")
        c.commit()
    redirect()

async def stop(request):
    with db() as c:
        c.execute("UPDATE kv SET value='0' WHERE name='enabled'")
        c.commit()
    redirect()

async def send_one(row):
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    from telethon.errors import FloodWaitError, PeerFloodError
    api_id=int(os.getenv("TG_API_ID"))
    api_hash=os.getenv("TG_API_HASH")
    session=os.getenv("TG_STRING_SESSION")
    client=TelegramClient(StringSession(session),api_id,api_hash,request_retries=0,connection_retries=0)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            return "SESSION_UNAUTHORIZED", True
        try:
            target=await client.get_entity(row["username"])
            await client.send_message(target,row["message"],link_preview=False)
            return None,False
        except (FloodWaitError,PeerFloodError):
            return "TELEGRAM_RATE_LIMIT_STOP",True
        except Exception as exc:
            return type(exc).__name__[:60],False
    finally:
        await client.disconnect()

async def worker(app):
    try:
        while True:
            await asyncio.sleep(8)
            if not enabled() or not configured():continue
            d,h,last=counts()
            if d>=MAX_DAILY or h>=MAX_HOURLY or (last and time.time()-last<MIN_INTERVAL):
                continue
            with db() as c:
                row=c.execute("SELECT * FROM leads WHERE status='queued' ORDER BY id LIMIT 1").fetchone()
                if not row:continue
                error=valid(row)
                if error:
                    c.execute("UPDATE leads SET status='review',error=? WHERE id=?",(error,row["id"]))
                    c.commit()
                    continue
                # Claim BEFORE the network request. An uncertain response stays 'sending'
                # and requires manual reconciliation, so crash/restart never sends twice.
                c.execute("UPDATE leads SET status='sending',attempted_at=?,error='' WHERE id=?",(time.time(),row["id"]))
                c.commit()
            try:
                problem,stop_now=await send_one(row)
            except Exception as exc:
                problem,stop_now=type(exc).__name__[:60],True
            with db() as c:
                if not problem:
                    c.execute("UPDATE leads SET status='sent',sent_at=?,error='' WHERE id=?",
                              (time.time(),row["id"]))
                else:
                    c.execute("UPDATE leads SET status='error',error=? WHERE id=?",(problem,row["id"]))
                if stop_now:
                    c.execute("UPDATE kv SET value='0' WHERE name='enabled'")
                c.commit()
    except asyncio.CancelledError:
        raise

async def background(app):
    job=asyncio.create_task(worker(app))
    yield
    job.cancel()
    await asyncio.gather(job,return_exceptions=True)

def application():
    initialize()
    app=web.Application(middlewares=[middleware],client_max_size=180_000)
    app.cleanup_ctx.append(background)
    app.add_routes([web.get("/",home),web.get("/health",health),web.post("/upload",upload),
        web.post("/add",add),web.post("/save",save),web.post("/approve",approve),
        web.post("/start",start),web.post("/stop",stop)])
    return app

if __name__=="__main__":
    web.run_app(application(),host="0.0.0.0",port=int(os.getenv("PORT","8080")))
