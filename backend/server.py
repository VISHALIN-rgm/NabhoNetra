"""NabhoNetra server: live pipeline on a schedule, storage (SQLite locally, DynamoDB + S3 on AWS), subscriber sign-up,
alert delivery, REST API, and (if built) the web dashboard. Run: python server.py"""
import datetime, hashlib, hmac, os, re, secrets, smtplib, threading, time, uuid
from email.message import EmailMessage
from contextlib import asynccontextmanager
from fastapi import FastAPI, File, Header, HTTPException, Request, Response, UploadFile
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import config as C, pipeline, store, impact, places, engine, geo
import agent
from agent import write_alert
from pipeline import haversine

HERE = os.path.dirname(os.path.abspath(__file__))
ADMIN = os.getenv("ADMIN_TOKEN", "")
DELIVERY = os.getenv("DELIVERY", "log")            # log = record only, live = really send via SNS (sms) / SES or SMTP (email)
REFRESH_H = float(os.getenv("REFRESH_HOURS", "3"))
AUTO = os.getenv("AUTO_ALERT", "0") == "1"         # auto-alert new high-priority clusters after each refresh
INCLUDE_DEMO = os.getenv("INCLUDE_DEMO", "0") == "1" and DELIVERY != "live"   # demo subscribers (see seed_demo.py) are never messaged; shown only when this is 1, and never in live mode
DEDUPE_H = 12
state = {"running": False, "error": ""}
lock = threading.Lock()
now = lambda: datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z"
init = store.init

def admin(token):
    if not ADMIN: raise HTTPException(403, "ADMIN_TOKEN is not set on the server.")
    if not hmac.compare_digest((token or "").encode(), ADMIN.encode()): raise HTTPException(401, "Wrong admin token.")

def deliver(sub, subject, text):
    if sub.get("demo"): return "demo", ""
    if DELIVERY != "live":
        print(f"[test mode] to {sub['channel']} ***{str(sub['contact'])[-4:]}: {text[:300]}")
        return "logged", ""
    try:
        if sub["channel"] == "sms":
            import boto3
            boto3.client("sns", region_name=os.getenv("SNS_REGION", C.BEDROCK_REGION)).publish(PhoneNumber=sub["contact"], Message=text,
                MessageAttributes={"AWS.SNS.SMS.SMSType": {"DataType": "String", "StringValue": "Transactional"}})
        elif sub["channel"] == "whatsapp":
            import boto3, json
            tpl = os.getenv("WHATSAPP_TEMPLATE")
            msg = ({"type": "template", "template": {"name": tpl, "language": {"code": os.getenv("WHATSAPP_TEMPLATE_LANG", "en")},
                    "components": [{"type": "body", "parameters": [{"type": "text", "text": text}]}]}} if tpl else {"type": "text", "text": {"body": text}})
            boto3.client("socialmessaging", region_name=os.getenv("WHATSAPP_REGION", C.BEDROCK_REGION)).send_whatsapp_message(
                originationPhoneNumberId=os.environ["WHATSAPP_PHONE_ID"], metaApiVersion="v20.0",
                message=json.dumps({"messaging_product": "whatsapp", "to": sub["contact"], **msg}).encode())
        elif os.getenv("EMAIL_PROVIDER") == "ses":
            import boto3
            boto3.client("ses", region_name=os.getenv("SES_REGION", C.BEDROCK_REGION)).send_email(Source=os.getenv("SES_FROM") or os.environ["SMTP_FROM"],
                Destination={"ToAddresses": [sub["contact"]]}, Message={"Subject": {"Data": subject}, "Body": {"Text": {"Data": text}}})
        else:
            m = EmailMessage(); m["Subject"] = subject; m["From"] = os.environ["SMTP_FROM"]; m["To"] = sub["contact"]; m.set_content(text)
            with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.getenv("SMTP_PORT", "587"))) as s:
                s.starttls(); s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"]); s.send_message(m)
        return "sent", ""
    except Exception as e:
        return "failed", str(e)[:200]

def recently_alerted(c):
    return store.recent_alert(c["lat"], c["lon"], DEDUPE_H)

def visible_subs():
    """People who take part in matching, counts and alerts. Administrator accounts are staff only, so they are never in here."""
    return [s for s in store.list_subs(active_only=True) if (INCLUDE_DEMO or not s.get("demo")) and s["role"] != "admin"]

def visible_ivs():
    return [i for i in store.list_interventions(500) if INCLUDE_DEMO or not i.get("demo")]

def available_channels():
    email = DELIVERY != "live" or (os.getenv("EMAIL_PROVIDER") == "ses" and os.getenv("SES_FROM")) or os.getenv("SMTP_HOST")
    return ["sms"] + (["email"] if email else []) + (["whatsapp"] if DELIVERY != "live" or os.getenv("WHATSAPP_PHONE_ID") else [])

def base_url(request=None):
    return os.getenv("PUBLIC_URL", "").rstrip("/") or (str(request.base_url).rstrip("/") if request else "")

def coordinate_iv(iv, request=None, links=None):
    url = base_url(request)
    if not url: raise HTTPException(400, "Set PUBLIC_URL so requests can include a response link.")
    if not engine.secret(): raise HTTPException(400, "Set ADMIN_TOKEN or TOKEN_SECRET so response links can be signed.")
    send = lambda s, text: deliver(s, "NabhoNetra request", agent.translate(text, s.get("lang", "en")))
    return engine.coordinate(iv, visible_subs(), send, url, links)

def count_near(c, role, subs=None):
    return sum(1 for s in (subs if subs is not None else visible_subs()) if s["role"] == role and haversine(c["lat"], c["lon"], s["lat"], s["lon"]) <= s["radius_km"])

_prov = {"t": 0, "v": []}
def providers():
    """Registered machine providers and biomass buyers who agreed to be listed: offered to farmers as alternatives (cached for a minute)."""
    if time.time() - _prov["t"] > 60:
        label = {"machine_provider": "Machine provider", "biomass_buyer": "Biomass buyer"}
        _prov.update(t=time.time(), v=[{"name": s["name"], "type": label[s["role"]] + " (registered)", "lat": s["lat"], "lon": s["lon"], "contact": s["contact"], "registered": True}
                                       for s in visible_subs() if s["role"] in label and s.get("share")])
    return _prov["v"]
agent.extra_providers = providers

def personal_alert(s, c):
    """The message one recipient gets: their own distance and the alternative nearest to them. The AI-written text goes to officers and the dashboard."""
    d, where, when, role = round(haversine(c["lat"], c["lon"], s["lat"], s["lon"])), agent._where(c), agent._when(c), s["role"]
    if role in ("officer", "official"):
        return f"[{c['priority'].upper()}] {c['fires']} fires near {where}, {c['distance_km']} km from {agent._city(c)}.{agent._eta(c)} {c['alert']['text']}"
    if role == "machine_provider":
        n = count_near(c, "farmer")
        return (f"NabhoNetra: {c['fires']} crop fires detected {d} km from you near {where} ({when}). Farmers nearby may need a seeder, baler or mulcher instead of burning."
                + (f" {n} registered farmers are in range." if n else ""))
    if role == "biomass_buyer":
        return f"NabhoNetra: {c['fires']} crop fires detected {d} km from you near {where} ({when}). Straw is likely to be available nearby for collection."
    tag = {"high": "URGENT", "medium": "Notice", "low": "Advisory"}[c["priority"]]
    msg = f"{tag}: {c['fires']} crop fires {d} km from you near {where} ({when}).{agent._eta(c)} Please do not burn the residue."
    alts = agent.nearby_alternatives(s["lat"], s["lon"], 1)
    if alts:
        x = alts[0]; msg += f" Nearest option to you: {x['type']} - {x['name']}, {x['km']} km, contact {x['contact']}."
    return msg

def in_window():
    a, b = (float(x) for x in C.ALERT_WINDOW_UTC.split("-")); t = datetime.datetime.utcnow(); h = t.hour + t.minute / 60
    return a <= h < b

def send_alert(c, manual=False):
    subs = visible_subs()
    targets = [s for s in subs if engine.ok_to_contact(s, c, manual) and ((engine.officer_covers(s, c)) if s["role"] in ("officer", "official") else engine.in_range(s, c))]
    if not targets:
        return {"recipients": 0, "delivered": 0, "failed": 0, "mode": DELIVERY}
    text = c["alert"]["text"]; res = []
    for s in targets:
        res.append((s["id"],) + deliver(s, "NabhoNetra crop-fire alert", agent.translate(personal_alert(s, c), s.get("lang", "en"))))
    ok = sum(r[1] == "sent" for r in res); bad = sum(r[1] == "failed" for r in res)
    store.add_alert({"created": now(), "lat": c["lat"], "lon": c["lon"], "priority": c["priority"], "message": text,
                     "recipients": len(targets), "delivered": ok, "failed": bad, "mode": DELIVERY}, res)
    return {"recipients": len(targets), "delivered": ok, "failed": bad, "mode": DELIVERY, "demo": sum(1 for s in targets if s.get("demo"))}

def run_pipeline():
    data = pipeline.run(mock=os.getenv("PIPELINE_MOCK") == "1", alert_fn=write_alert)
    cells = data.pop("_cells", {})
    store.save_snapshot(data)
    store.merge_cells(cells)
    subs, all_cells = visible_subs(), store.load_cells()
    for c in data["clusters"]:
        if c["priority"] == "low": continue
        iv = engine.ensure(c, subs, all_cells, [a for a in agent.nearby_alternatives(c["lat"], c["lon"], 5) if not a.get("registered")])
        if AUTO and in_window() and c["priority"] == "high":
            if not recently_alerted(c): send_alert(c)
            if iv["status"] == "open":
                try: coordinate_iv(iv)
                except HTTPException as e: print("Coordination skipped:", e.detail)

def refresh():
    with lock:
        if state["running"]: return False
        state["running"] = True
    try:
        run_pipeline(); state["error"] = ""
    except Exception as e:
        state["error"] = str(e)[:300]; print("Pipeline run failed:", e)
    finally:
        state["running"] = False
    return True

def snapshot_age_s():
    snap = store.latest_snapshot()
    return None if not snap else (datetime.datetime.utcnow() - datetime.datetime.fromisoformat(snap[0].rstrip("Z"))).total_seconds()

def loop():
    while True:
        try:
            age = snapshot_age_s()
            snap = store.latest_snapshot()
            changed = bool(snap) and snap[1].get("cfg") != pipeline.config_key(os.getenv("PIPELINE_MOCK") == "1")   # region or scope settings changed since the last run
            if age is None or age > REFRESH_H * 3600 or changed: refresh()
        except Exception as e:
            print("Scheduler error:", e)
        time.sleep(300)

@asynccontextmanager
async def lifespan(_app):
    init(); places.load([], network=False); threading.Thread(target=loop, daemon=True).start()
    yield

app = FastAPI(title="NabhoNetra", lifespan=lifespan)

@app.middleware("http")
async def security_headers(request, call_next):
    r = await call_next(request)
    r.headers.update({"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "same-origin"})
    return r

hits = {}
def client_ip(request):
    xff = request.headers.get("x-forwarded-for", "").split(",")[0].strip() if os.getenv("TRUST_PROXY") == "1" else ""
    return xff or (request.client.host if request.client else "?")

def limit(request, key, n, per=3600):
    ip = client_ip(request); t = time.time(); k = (ip, key)
    if len(hits) > 5000:
        for old in [o for o, v in hits.items() if not v or t - v[-1] > per]: del hits[old]
    hits[k] = [x for x in hits.get(k, []) if t - x < per]
    if len(hits[k]) >= n: raise HTTPException(429, "Too many requests. Please try again later.")
    hits[k].append(t)

def norm(channel, contact):
    if channel not in ("sms", "email", "whatsapp"): raise HTTPException(400, "Choose SMS, email or WhatsApp.")
    contact = contact.strip().replace(" ", "")[:120]
    return contact.lower() if channel == "email" else contact

otp_day = {"d": "", "n": 0}
OTP_DAILY_MAX = int(os.getenv("OTP_DAILY_MAX", "300"))   # caps SMS/email cost if someone floods the form from many addresses

def otp_send(channel, contact, purpose):
    today = datetime.date.today().isoformat()
    if otp_day["d"] != today: otp_day.update(d=today, n=0)
    if otp_day["n"] >= OTP_DAILY_MAX: raise HTTPException(429, "Verification is temporarily unavailable. Please try again tomorrow.")
    code = f"{secrets.randbelow(10**6):06d}"; t = time.time()
    r = store.otp_get(channel, contact, purpose)
    if r and t - r["sent"] < 60: raise HTTPException(429, "Please wait a minute before asking for another code.")
    store.otp_put(channel, contact, purpose, hashlib.sha256(code.encode()).hexdigest(), t + 600, t)
    status, _err = deliver({"channel": channel, "contact": contact}, "NabhoNetra verification code",
            f"NabhoNetra code: {code}. It expires in 10 minutes. If you did not ask for it, ignore this message.")
    if status == "failed":
        store.otp_del(channel, contact, purpose)
        raise HTTPException(502, "We could not send the code. Check the phone number or email and try again.")
    otp_day["n"] += 1
    return code

def otp_check(channel, contact, purpose, code):
    h = hashlib.sha256(code.strip().encode()).hexdigest(); bad = ""
    r = store.otp_get(channel, contact, purpose)
    if not r or r["expires"] < time.time(): bad = "That code has expired. Request a new one."
    elif r["attempts"] >= 5: bad = "Too many wrong attempts. Request a new code."
    elif not hmac.compare_digest(r["code"], h): store.otp_bump(channel, contact, purpose); bad = "Wrong code."
    else: store.otp_del(channel, contact, purpose)
    if bad: raise HTTPException(400, bad)

@app.get("/api/health")
def health():
    age = snapshot_age_s()
    return {"ok": True, "delivery": DELIVERY, "auto_alert": AUTO, "refreshing": state["running"],
            "data_age_minutes": None if age is None else round(age / 60), "last_error": bool(state["error"]), "store": store.KIND}

@app.get("/api/data")
def get_data():
    snap = store.latest_snapshot()
    if not snap:
        raise HTTPException(503, "No data yet. " + (state["error"] or "The first pipeline run is in progress, try again in a minute."))
    d = snap[1]; d.pop("_cells", None)
    for c in d["clusters"]:
        c["status"] = "sent" if recently_alerted(c) else "pending"
    subs = visible_subs()
    for c in d["clusters"]:
        c["nearby"] = {r: count_near(c, r, subs) for r in ("farmer", "machine_provider", "biomass_buyer")}
    d["subscribers_count"] = len(subs)
    d["subscribers_by_role"] = {r: sum(1 for s in subs if s["role"] == r) for r in {s["role"] for s in subs}}
    d["demo_subscribers"] = sum(1 for s in subs if s.get("demo"))
    d["refreshing"] = state["running"]; d["last_error"] = state["error"]; d["delivery"] = DELIVERY
    return d

@app.post("/api/refresh")
def post_refresh(request: Request, x_admin_token: str = Header(None), x_session: str = Header(None)):
    w = need_admin(request, x_admin_token, x_session); audit(request, w, "refresh")
    if state["running"]: return {"started": False, "detail": "A refresh is already running."}
    threading.Thread(target=refresh, daemon=True).start()
    return {"started": True}

class Pt(BaseModel):
    lat: float
    lon: float

@app.post("/api/alerts/send")
def post_send(p: Pt, request: Request, x_admin_token: str = Header(None), x_session: str = Header(None)):
    w = need_admin(request, x_admin_token, x_session); audit(request, w, "alert_send", f"{p.lat:.2f},{p.lon:.2f}")
    snap = store.latest_snapshot()
    if not snap: raise HTTPException(404, "No data yet.")
    for c in snap[1]["clusters"]:
        if abs(c["lat"] - p.lat) < .02 and abs(c["lon"] - p.lon) < .02:
            return send_alert(c, manual=True)
    raise HTTPException(404, "Cluster not found in the latest data.")

@app.get("/api/impact")
def get_impact():
    return {**impact.effect(store.load_cells(), store.list_alerts(500)), "interventions": engine.metrics(visible_ivs())}

@app.get("/api/alerts")
def get_alerts():
    return store.list_alerts(100)

class Sub(BaseModel):
    name: str
    role: str = "farmer"
    channel: str
    contact: str
    lat: float
    lon: float
    radius_km: float = 10
    lang: str = "en"
    share: bool = False
    consent: bool = False
    profile: dict = {}

@app.post("/api/subscribers")
def post_sub(s: Sub, request: Request, x_admin_token: str = Header(None), x_session: str = Header(None)):
    limit(request, "sub", 10)
    s.name = s.name.strip(); s.channel = s.channel.strip(); s.contact = norm(s.channel, s.contact)
    if not 1 <= len(s.name) <= 80: raise HTTPException(400, "Enter your name.")
    if s.role not in ("farmer", "machine_provider", "biomass_buyer", "officer"): raise HTTPException(400, "Choose farmer, machine provider, biomass buyer or officer.")
    if s.role == "officer": audit(request, need_admin(request, x_admin_token, x_session), "officer_registered", s.name)
    if s.channel in ("sms", "whatsapp") and not re.fullmatch(r"\+\d{10,15}", s.contact): raise HTTPException(400, "Phone must include the country code, like +91XXXXXXXXXX.")
    if s.channel == "email" and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", s.contact): raise HTTPException(400, "Enter a valid email address.")
    if not (-90 <= s.lat <= 90 and -180 <= s.lon <= 180): raise HTTPException(400, "Invalid location.")
    if not 1 <= s.radius_km <= 50: raise HTTPException(400, "Radius must be between 1 and 50 km.")
    if s.lang not in agent.LANGS: raise HTTPException(400, "Choose English, Hindi or Punjabi.")
    if s.channel not in available_channels(): raise HTTPException(400, "That channel is not set up on this server.")
    if not s.consent: raise HTTPException(400, "Please tick the consent box so we can contact you.")
    try: profile = engine.clean_profile(s.role, s.profile)
    except ValueError as e: raise HTTPException(400, str(e))
    profile["consent"] = {"at": now(), "channel": s.channel, "version": 1}
    s.share = s.share and s.role != "officer"
    officer = s.role == "officer"
    old = store.get_sub(s.channel, s.contact)
    if old and old["role"] == "admin": return {"ok": True, "verify": False, "detail": "This contact is already registered."}   # an administrator account can never be overwritten through the API
    if old and old["active"] and not officer:
        return {"ok": True, "verify": False, "detail": "This contact is already registered. To change details, stop alerts first, then register again."}
    store.put_sub({"created": now(), "name": s.name, "role": s.role, "channel": s.channel, "contact": s.contact, "lat": s.lat, "lon": s.lon,
                   "radius_km": s.radius_km, "active": 1 if officer else 0, "demo": 0, "lang": s.lang, "share": 1 if s.share else 0, "profile": profile})
    if officer:
        me = store.get_sub(s.channel, s.contact)
        return {"ok": True, "verify": False, "registry": engine.registry_view(me, visible_ivs(), visible_subs())}
    code = otp_send(s.channel, s.contact, "subscribe")
    return {"ok": True, "verify": True, **({"dev_code": code} if DELIVERY != "live" else {})}

class Ref(BaseModel):
    channel: str
    contact: str

class Verify(Ref):
    code: str

@app.post("/api/subscribers/verify")
def post_verify(v: Verify, request: Request):
    limit(request, "otp", 30); c = norm(v.channel, v.contact)
    otp_check(v.channel, c, "subscribe", v.code)
    store.set_active(v.channel, c, 1)
    me = store.get_sub(v.channel, c)
    return {"ok": True, "registry": engine.registry_view(me, visible_ivs(), visible_subs()) if me else None, **(session_for(me) if me else {})}

ROLE_LABEL = {"farmer": "Farmer", "machine_provider": "Machine provider", "biomass_buyer": "Biomass buyer", "officer": "Officer", "admin": "Administrator"}
PRIVILEGED = ("officer", "admin")
SESSION_DAYS = {"admin": 8 / 24, "officer": 3}     # staff sessions are short; everyone else stays signed in for 30 days

def me_view(s):
    p = s.get("profile") or {}
    keep = ("land_acres", "crop", "needs", "machines", "availability", "materials", "capacity_tpd", "designation", "min_priority", "area")
    return {"name": s["name"], "role": s["role"], "role_label": ROLE_LABEL.get(s["role"], s["role"]), "lat": s["lat"], "lon": s["lon"],
            "radius_km": s["radius_km"], "share": bool(s.get("share")), "profile": {k: p[k] for k in keep if k in p}}

def session_for(s, strict=False):
    if not engine.secret():
        if strict: raise HTTPException(400, "Sign-in is not set up: the server needs ADMIN_TOKEN or TOKEN_SECRET.")
        return {}
    return {"session": engine.make_session(s["id"], SESSION_DAYS.get(s["role"], 30)), "me": me_view(s)}

def audit(request, who, action, target="", detail=""):
    """Append one row to the audit trail. Rows hold who, what and where, never contact details."""
    try: store.add_audit({"at": now(), "actor": who.get("name", "?"), "role": who.get("role", "?"), "sid": who.get("sid", ""), "action": action,
                          "target": target, "detail": str(detail)[:200], "ip": client_ip(request) if request else ""})
    except Exception as e: print("Audit write failed:", e)

sub_who = lambda s: {"name": s["name"], "role": s["role"], "sid": str(s["id"])}

def me_of(x_session):
    sid = engine.parse_session(x_session)
    return next((s for s in store.list_subs(active_only=True) if str(s["id"]) == sid and (INCLUDE_DEMO or not s.get("demo"))), None) if sid else None

def need_me(x_session):
    s = me_of(x_session)
    if not s: raise HTTPException(401, "Please sign in to continue.")
    return s

TOKEN_WHO = {"name": "admin token", "role": "admin", "sid": "", "sub": None}
def who_is(request, x_admin_token, x_session):
    """The caller. The admin token is for operators and scripts calling the API; the website never asks for it. People sign in with a code."""
    if x_admin_token:
        limit(request, "admintoken", 30)
        try: admin(x_admin_token)
        except HTTPException: audit(request, {"name": "unknown", "role": "none"}, "admin_token_rejected"); raise
        return TOKEN_WHO
    s = me_of(x_session)
    return {**sub_who(s), "sub": s} if s else None

def need_admin(request, x_admin_token, x_session):
    w = who_is(request, x_admin_token, x_session)
    if not w: raise HTTPException(401, "Sign in as an administrator to do this.")
    if w["role"] != "admin": audit(request, w, "denied_admin_only"); raise HTTPException(403, "Only administrators can do this.")
    return w

def need_staff(request, x_admin_token, x_session, iv=None):
    """An administrator, or an officer whose assigned area covers this intervention. Role and location are checked together."""
    w = who_is(request, x_admin_token, x_session)
    if not w or w["role"] not in PRIVILEGED: raise HTTPException(401, "Sign in as an officer to do this.")
    if w["role"] == "officer" and iv and not engine.officer_covers(w["sub"], iv["cluster"]):
        audit(request, w, "denied_outside_area", iv["iid"]); raise HTTPException(403, "This intervention is outside your assigned area.")
    return w

@app.post("/api/session/start")
def session_start(r: Ref, request: Request):
    limit(request, "otp", 30); c = norm(r.channel, r.contact)
    s = store.get_sub(r.channel, c)
    code = otp_send(r.channel, c, "login") if s and s.get("active") and not s.get("demo") else None
    # Staff codes are never shown on screen, even in test mode: an operator reads them from the server log.
    return {"ok": True, **({"dev_code": code} if code and DELIVERY != "live" and s["role"] not in PRIVILEGED else {})}

@app.post("/api/session/verify")
def session_verify(v: Verify, request: Request):
    limit(request, "otp", 30); c = norm(v.channel, v.contact); s = store.get_sub(v.channel, c)
    try: otp_check(v.channel, c, "login", v.code)
    except HTTPException:
        if s and s["role"] in PRIVILEGED: audit(request, sub_who(s), "login_failed")
        raise
    if not s or not s.get("active"): raise HTTPException(400, "No active registration for this contact.")
    if s["role"] in PRIVILEGED: audit(request, sub_who(s), "login")
    return {"ok": True, **session_for(s, strict=True)}

@app.get("/api/me")
def get_me(x_session: str = Header(None)): return me_view(need_me(x_session))

@app.get("/api/me/interventions")
def get_my_interventions(x_session: str = Header(None)): return engine.mine(need_me(x_session), visible_ivs())

@app.get("/api/me/requests")
def get_my_requests(x_session: str = Header(None)):
    s = need_me(x_session)
    if s["role"] != "farmer": raise HTTPException(403, "Only farmers have help requests.")
    return engine.my_requests(s, visible_ivs(), {str(x["id"]): x for x in store.list_subs()})

@app.get("/api/audit")
def get_audit(request: Request, x_admin_token: str = Header(None), x_session: str = Header(None)):
    need_admin(request, x_admin_token, x_session); return store.list_audit(200)

@app.post("/api/subscribers/optout")
def post_optout(r: Ref, request: Request):
    limit(request, "otp", 30); c = norm(r.channel, r.contact)
    code = otp_send(r.channel, c, "optout") if store.get_sub(r.channel, c) else None
    return {"ok": True, **({"dev_code": code} if code and DELIVERY != "live" else {})}

@app.post("/api/subscribers/optout/confirm")
def post_optout_confirm(v: Verify, request: Request):
    limit(request, "otp", 30); c = norm(v.channel, v.contact)
    otp_check(v.channel, c, "optout", v.code)
    store.delete_sub(v.channel, c)
    return {"ok": True}

@app.get("/api/subscribers")
def list_subs(request: Request, x_admin_token: str = Header(None), x_session: str = Header(None)):
    audit(request, need_admin(request, x_admin_token, x_session), "subscribers_listed")
    keys = ("id", "created", "name", "role", "channel", "contact", "lat", "lon", "radius_km", "active", "demo", "lang", "share")
    return [{k: s.get(k) for k in keys} for s in store.list_subs()]

@app.get("/api/config")
def get_config(): return {"channels": available_channels(), "delivery": DELIVERY}

@app.get("/api/geocode")
def get_geocode(request: Request, state: str = "", district: str = "", village: str = ""):
    limit(request, "geo", 30)
    q = ", ".join(x.strip()[:60] for x in (village, district, state) if x.strip())
    if not q: raise HTTPException(400, "Enter a village, district or state.")
    return {"results": geo.search(q)}

@app.get("/api/reverse")
def get_reverse(request: Request, lat: float, lon: float):
    limit(request, "geo", 30)
    return {"area": geo.locate(lat, lon, network=True)}

def _cluster_at(p):
    snap = store.latest_snapshot()
    if not snap: raise HTTPException(404, "No data yet.")
    for c in snap[1]["clusters"]:
        if abs(c["lat"] - p.lat) < .02 and abs(c["lon"] - p.lon) < .02: return c
    raise HTTPException(404, "Cluster not found in the latest data.")

def _iv(iid):
    iv = store.get_intervention(iid)
    if not iv: raise HTTPException(404, "Intervention not found.")
    return iv

@app.get("/api/interventions")
def list_interventions(): return [engine.public_view(i) for i in visible_ivs()[:100]]

@app.post("/api/interventions/plan")
def post_plan(p: Pt, request: Request, x_admin_token: str = Header(None), x_session: str = Header(None)):
    w = need_admin(request, x_admin_token, x_session); audit(request, w, "intervention_planned", f"{p.lat:.2f},{p.lon:.2f}"); c = _cluster_at(p)
    return engine.public_view(engine.ensure(c, visible_subs(), store.load_cells(), [a for a in agent.nearby_alternatives(c["lat"], c["lon"], 5) if not a.get("registered")]))

@app.get("/api/interventions/{iid}")
def get_intervention(iid: str, request: Request, x_admin_token: str = Header(None), x_session: str = Header(None)):
    iv = _iv(iid); need_staff(request, x_admin_token, x_session, iv); by = {str(s["id"]): s for s in store.list_subs()}
    return {**iv, "matches": [{**m, "contact": by.get(m["sid"], {}).get("contact"), "channel": by.get(m["sid"], {}).get("channel")} for m in iv["matches"]]}

@app.post("/api/interventions/{iid}/coordinate")
def post_coordinate(iid: str, request: Request, x_admin_token: str = Header(None), x_session: str = Header(None)):
    iv = _iv(iid); w = need_staff(request, x_admin_token, x_session, iv)
    links = [] if DELIVERY != "live" else None   # in test mode, show the response links so the provider page can be opened for a demo
    out = {"asked": coordinate_iv(iv, request, links), "status": iv["status"]}; audit(request, w, "requests_sent", iid, f"asked={out['asked']}")
    return {**out, "links": links} if links is not None else out

class Verdict(BaseModel):
    approve: bool
    note: str = ""
    sid: str | None = None     # one provider's completion claim; leave out to decide every pending claim

@app.post("/api/interventions/{iid}/verify")
def post_iv_verify(iid: str, d: Verdict, request: Request, x_admin_token: str = Header(None), x_session: str = Header(None)):
    iv = _iv(iid); w = need_staff(request, x_admin_token, x_session, iv)
    if d.sid and w.get("sid") == d.sid: raise HTTPException(403, "You cannot verify your own work.")
    try: engine.verify(iv, d.approve, d.note, store.load_cells(), d.sid, w["name"])
    except ValueError as e: raise HTTPException(400, str(e))
    audit(request, w, "claim_verified" if d.approve else "claim_rejected", iid, d.sid or "all pending")
    return engine.public_view(iv)

@app.get("/api/evidence/{iid}/{name}")
def get_evidence(iid: str, name: str, request: Request, x_admin_token: str = Header(None), x_session: str = Header(None)):
    w = need_staff(request, x_admin_token, x_session, _iv(iid)); audit(request, w, "evidence_viewed", iid, name); got = store.get_evidence(iid, name)
    if not got: raise HTTPException(404, "Not found.")
    return Response(content=got[0], media_type=got[1])

def _resolve(token):
    p = engine.parse_token(token); iv = store.get_intervention(p[0]) if p else None
    m = next((x for x in iv["matches"] if x["sid"] == p[1]), None) if iv else None
    if not m: raise HTTPException(404, "This link is not valid.")
    return iv, m

def provider_jobs(iv, m):
    """Consented jobs for this provider, and how many other registered farmers in range have not chosen them (a count, nothing else)."""
    by = {str(x["id"]): x for x in store.list_subs()}; provider = by.get(m["sid"])
    jobs = engine.jobs_for(iv, m, by, provider) if provider else []
    leads = [{"name": j["name"], "contact": j["contact"], "land_acres": j.get("land_acres"), "crop": j.get("crop"), "needs": j["needs"], "area": j["area"],
              "lat": j.get("lat"), "lon": j.get("lon")} for j in jobs if "contact" in j]
    others = sum(1 for f in visible_subs() if f["role"] == "farmer" and engine.in_range(f, iv["cluster"])) - len(jobs)
    return jobs, leads, max(0, others)

@app.get("/api/respond/{token}")
def get_respond(token: str, request: Request):
    limit(request, "respond", 60); iv, m = _resolve(token); c = iv["cluster"]; jobs, leads, hidden = provider_jobs(iv, m)
    return {"role": m["role"], "name": m["name"], "status": m["status"], "intervention_status": iv["status"], "cluster": c,
            "demand": engine.public_registry(iv["analysis"]["registry"]), "observed": iv["analysis"]["observed"], "estimated": iv["analysis"]["estimated"],
            "offers": m.get("offers") or m.get("materials"), "jobs": jobs, "leads": leads, "leads_not_shared": hidden}

class Act(BaseModel):
    action: str
    note: str = ""

@app.post("/api/respond/{token}")
def post_respond(token: str, a: Act, request: Request):
    limit(request, "respond", 60); iv, m = _resolve(token)
    try: engine.apply(iv, m["sid"], a.action, a.note)
    except ValueError as e: raise HTTPException(400, str(e))
    audit(request, {"name": m["name"], "role": m["role"], "sid": m["sid"]}, "provider_" + a.action, iv["iid"])
    return {"ok": True, "status": m["status"], "intervention_status": iv["status"]}

async def save_photo(iv, m, file):
    if m["status"] not in ("accepted", "completed"): raise HTTPException(400, "Accept the request first.")
    data = await file.read(5_000_001)
    if len(data) > 5_000_000: raise HTTPException(413, "Photo is larger than 5 MB.")
    ext = "jpg" if data[:3] == b"\xff\xd8\xff" else "png" if data[:8] == b"\x89PNG\r\n\x1a\n" else None
    if not ext: raise HTTPException(400, "Upload a JPEG or PNG photo.")
    if sum(1 for e in iv["evidence"] if e["type"] == "photo" and e["by"] == m["sid"]) >= 5: raise HTTPException(400, "At most 5 photos per request.")
    name = f"{uuid.uuid4().hex[:10]}.{ext}"
    store.put_evidence(iv["iid"], name, data, "image/jpeg" if ext == "jpg" else "image/png")
    iv["evidence"].append({"type": "photo", "by": m["sid"], "name": name, "at": now()}); iv["updated"] = now(); store.put_intervention(iv)
    return {"ok": True}

@app.post("/api/respond/{token}/evidence")
async def post_evidence(token: str, request: Request, file: UploadFile = File(...)):
    limit(request, "evidence", 20); iv, m = _resolve(token)
    return await save_photo(iv, m, file)

# ---- role-based access: what each signed-in role can see and do on an intervention
def my_match(iv, s):
    return next((x for x in iv["matches"] if x["sid"] == str(s["id"])), None)

def need_provider(x_session, iid):
    s = need_me(x_session)
    if s["role"] not in ("machine_provider", "biomass_buyer"): raise HTTPException(403, "Only machine providers and biomass buyers can respond to requests.")
    iv = _iv(iid); m = my_match(iv, s)
    if not m: raise HTTPException(403, "This request was not matched to you.")
    return s, iv, m

def need_farmer(x_session):
    s = need_me(x_session)
    if s["role"] != "farmer": raise HTTPException(403, "Only farmers can ask for help.")
    return s

def own_request(iv, s, rid):
    rq = next((r for r in iv.get("requests", []) if r["rid"] == rid and r["fsid"] == str(s["id"])), None)
    if not rq: raise HTTPException(404, "Request not found.")     # the same answer for someone else's request, so ids reveal nothing
    return rq

all_subs = lambda: {str(x["id"]): x for x in store.list_subs()}

@app.get("/api/interventions/{iid}/role")
def get_iv_role(iid: str, request: Request, x_session: str = Header(None)):
    s = need_me(x_session); iv = _iv(iid); c = iv["cluster"]; role = s["role"]; out = {"role": role}; by = all_subs()
    if role in PRIVILEGED:
        if role == "officer" and not engine.officer_covers(s, c): return {**out, "covered": False}
        if iv.get("requests"): audit(request, sub_who(s), "farmer_requests_viewed", iid)
        return {**out, "covered": True, "evidence": iv["evidence"], "verification": iv.get("verification"), "claims": engine.claims_view(iv),
                "requests": engine.staff_requests(iv, by),
                "matches": [{**m, "contact": by.get(m["sid"], {}).get("contact"), "channel": by.get(m["sid"], {}).get("channel")} for m in iv["matches"]]}
    if role in ("machine_provider", "biomass_buyer"):
        m = my_match(iv, s)
        if not m: return {**out, "mine": None, "in_range": engine.in_range(s, c)}
        jobs, leads, hidden = provider_jobs(iv, m)
        return {**out, "mine": {k: m.get(k) for k in ("status", "km", "offers", "materials")}, "jobs": jobs, "leads": leads, "leads_not_shared": hidden,
                "my_photos": sum(1 for e in iv["evidence"] if e["type"] == "photo" and e["by"] == m["sid"])}
    reqs = [engine.request_view(iv, r, by) for r in iv.get("requests", []) if r["fsid"] == str(s["id"])]
    near = engine.in_range(s, c)
    return {**out, "in_range": near, "km": round(haversine(c["lat"], c["lon"], s["lat"], s["lon"])), "requests": reqs,
            "can_request": near and not any(r["status"] not in ("withdrawn", "verified", "rejected") for r in reqs),
            "needs_default": (s.get("profile") or {}).get("needs", [])}

@app.post("/api/interventions/{iid}/act")
def post_iv_act(iid: str, a: Act, request: Request, x_session: str = Header(None)):
    limit(request, "respond", 60); s, iv, m = need_provider(x_session, iid)
    try: engine.apply(iv, m["sid"], a.action, a.note)
    except ValueError as e: raise HTTPException(400, str(e))
    audit(request, sub_who(s), "provider_" + a.action, iid)
    return {"ok": True, "status": m["status"], "intervention_status": iv["status"]}

@app.post("/api/interventions/{iid}/evidence")
async def post_iv_evidence(iid: str, request: Request, file: UploadFile = File(...), x_session: str = Header(None)):
    limit(request, "evidence", 20); s, iv, m = need_provider(x_session, iid)
    r = await save_photo(iv, m, file); audit(request, sub_who(s), "evidence_uploaded", iid); return r

# ---- farmer requests: ask for help, choose a proposed solution, track it, withdraw it
class ReqIn(BaseModel):
    needs: list[str] = []
    note: str = ""

class Choice(BaseModel):
    sid: str
    share_location: bool = False     # exact location only if the farmer ticks this

@app.post("/api/interventions/{iid}/requests")
def post_request(iid: str, d: ReqIn, request: Request, x_session: str = Header(None)):
    s = need_farmer(x_session); limit(request, "farmreq", 10); iv = _iv(iid)
    if not engine.in_range(s, iv["cluster"]): raise HTTPException(403, "This cluster is outside your alert area.")
    try: rq = engine.create_request(iv, s, d.needs, d.note, visible_subs())
    except ValueError as e: raise HTTPException(400, str(e))
    audit(request, sub_who(s), "request_created", iid)
    return engine.request_view(iv, rq, all_subs())

@app.post("/api/interventions/{iid}/requests/{rid}/accept")
def post_req_accept(iid: str, rid: str, d: Choice, request: Request, x_session: str = Header(None)):
    s = need_farmer(x_session); limit(request, "farmreq", 30); iv = _iv(iid); rq = own_request(iv, s, rid)
    provider = next((x for x in visible_subs() if str(x["id"]) == d.sid), None)
    if not provider: raise HTTPException(400, "That option is not available.")
    try: m = engine.accept_proposal(iv, rq, d.sid, d.share_location, provider)
    except ValueError as e: raise HTTPException(400, str(e))
    audit(request, sub_who(s), "proposal_accepted", iid, "exact location shared" if d.share_location else "area only")
    url = base_url(request)
    if url and engine.secret() and m["status"] == "asked":      # tell the provider there is a request; the message holds no farmer details
        where = iv["cluster"].get("place") or "your area"
        deliver(provider, "NabhoNetra request", agent.translate(f"NabhoNetra: a farmer near {where} chose you for their residue request. See what is needed and reply: {url}/#/respond/{engine.make_token(iid, m['sid'])}", provider.get("lang", "en")))
    return engine.request_view(iv, rq, all_subs())

@app.post("/api/interventions/{iid}/requests/{rid}/decline")
def post_req_decline(iid: str, rid: str, d: Choice, request: Request, x_session: str = Header(None)):
    s = need_farmer(x_session); limit(request, "farmreq", 30); iv = _iv(iid); rq = own_request(iv, s, rid)
    try: engine.decline_proposal(iv, rq, d.sid)
    except ValueError as e: raise HTTPException(400, str(e))
    return engine.request_view(iv, rq, all_subs())

@app.post("/api/interventions/{iid}/requests/{rid}/withdraw")
def post_req_withdraw(iid: str, rid: str, request: Request, x_session: str = Header(None)):
    s = need_farmer(x_session); limit(request, "farmreq", 30); iv = _iv(iid); rq = own_request(iv, s, rid)
    try: engine.withdraw_request(iv, rq)
    except ValueError as e: raise HTTPException(400, str(e))
    audit(request, sub_who(s), "request_withdrawn", iid)
    return engine.request_view(iv, rq, all_subs())

@app.post("/api/interventions/{iid}/requests/{rid}/propose")
def post_req_propose(iid: str, rid: str, request: Request, x_admin_token: str = Header(None), x_session: str = Header(None)):
    iv = _iv(iid); w = need_staff(request, x_admin_token, x_session, iv)
    rq = next((r for r in iv.get("requests", []) if r["rid"] == rid), None); f = all_subs().get(rq["fsid"]) if rq else None
    if not rq or not f: raise HTTPException(404, "Request not found.")
    before = len(rq["proposals"]); engine.propose(iv, rq, f, visible_subs()); store.put_intervention(iv)
    audit(request, w, "proposals_refreshed", iid)
    return {"added": len(rq["proposals"]) - before}

@app.get("/api/admin/check")
def admin_check(request: Request, x_admin_token: str = Header(None)):
    limit(request, "admin", 20); admin(x_admin_token)
    return {"ok": True}

DIST = os.path.join(HERE, "..", "frontend", "dist")
if os.path.isdir(DIST):
    app.mount("/", StaticFiles(directory=DIST, html=True), name="web")
else:
    @app.get("/", include_in_schema=False)
    def no_frontend():
        return HTMLResponse("<h2>NabhoNetra API is running, but the website has not been built.</h2>"
                            "<p>In a second terminal: <code>cd frontend; npm install; npm run build</code>, then restart this server and reload.<br>"
                            "Or for development: <code>cd frontend; npm install; npm run dev</code> and open <a href='http://localhost:5173'>http://localhost:5173</a>.</p>")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8000")))
