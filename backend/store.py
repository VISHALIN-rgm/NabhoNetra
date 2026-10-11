"""Storage. STORE=sqlite (default, local) or STORE=dynamodb (AWS: DynamoDB tables for subscribers, alerts and codes; S3 for the latest data snapshot)."""
import datetime, hashlib, json, os, sqlite3, uuid
from decimal import Decimal

KIND = os.getenv("STORE", "sqlite").lower()
HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.getenv("DB_PATH", os.path.join(HERE, "nabhonetra.db"))
PREFIX = os.getenv("DDB_PREFIX", "nabhonetra")
SNAP_BUCKET = os.getenv("SNAPSHOT_BUCKET", "")
AWS = KIND == "dynamodb"
_now = lambda: datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z"
_sid = lambda ch, ct: hashlib.sha256(f"{ch}|{ct}".encode()).hexdigest()[:24]

# ---------- SQLite ----------
def _db():
    c = sqlite3.connect(DB, timeout=30); c.row_factory = sqlite3.Row; return c

def init():
    if AWS: return   # tables are created by deploy/apprunner.yaml (or create_tables() for tests)
    os.makedirs(os.path.dirname(DB) or ".", exist_ok=True)
    with _db() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript("""
        CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);
        CREATE TABLE IF NOT EXISTS interventions(iid TEXT PRIMARY KEY, key TEXT, status TEXT, created TEXT, updated TEXT, doc TEXT);
        CREATE TABLE IF NOT EXISTS snapshots(id INTEGER PRIMARY KEY, created TEXT, body TEXT);
        CREATE TABLE IF NOT EXISTS subscribers(id INTEGER PRIMARY KEY, created TEXT, name TEXT, role TEXT, channel TEXT,
            contact TEXT, lat REAL, lon REAL, radius_km REAL, active INTEGER DEFAULT 1, UNIQUE(channel, contact));
        CREATE TABLE IF NOT EXISTS alerts(id INTEGER PRIMARY KEY, created TEXT, lat REAL, lon REAL, priority TEXT,
            message TEXT, recipients INTEGER, delivered INTEGER, failed INTEGER, mode TEXT);
        CREATE TABLE IF NOT EXISTS deliveries(id INTEGER PRIMARY KEY, alert_id INTEGER, subscriber_id INTEGER, status TEXT, error TEXT);
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, at TEXT, actor TEXT, role TEXT, sid TEXT, action TEXT, target TEXT, detail TEXT, ip TEXT);
        CREATE TABLE IF NOT EXISTS otps(channel TEXT, contact TEXT, purpose TEXT, code TEXT, expires REAL, attempts INTEGER DEFAULT 0, sent REAL,
            PRIMARY KEY(channel, contact, purpose));""")
        for col in ("demo INTEGER DEFAULT 0", "lang TEXT DEFAULT 'en'", "share INTEGER DEFAULT 0", "profile TEXT"):
            try: c.execute("ALTER TABLE subscribers ADD COLUMN " + col)
            except sqlite3.OperationalError: pass

# ---------- DynamoDB / S3 ----------
def _region(): return os.getenv("STORE_REGION") or os.getenv("AWS_REGION") or None
def _ddb():
    import boto3
    return boto3.resource("dynamodb", region_name=_region())
def _t(name): return _ddb().Table(f"{PREFIX}-{name}")
def _s3():
    import boto3
    return boto3.client("s3", region_name=_region())
def _py(v):
    if isinstance(v, Decimal): return int(v) if v == v.to_integral_value() else float(v)
    if isinstance(v, dict): return {k: _py(x) for k, x in v.items()}
    if isinstance(v, list): return [_py(x) for x in v]
    return v
def _dec(v):
    if isinstance(v, float): return Decimal(str(v))
    if isinstance(v, dict): return {k: _dec(x) for k, x in v.items()}
    if isinstance(v, list): return [_dec(x) for x in v]
    return v
def _scan(table):
    items, kw = [], {}
    while True:
        r = table.scan(**kw); items += r["Items"]
        if "LastEvaluatedKey" not in r: return [_py(i) for i in items]
        kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]

def create_tables():
    """For tests or manual setup outside CloudFormation."""
    c = _ddb().meta.client
    mk = lambda name, keys: c.create_table(TableName=f"{PREFIX}-{name}", BillingMode="PAY_PER_REQUEST",
        KeySchema=[{"AttributeName": k, "KeyType": t} for k, t in keys], AttributeDefinitions=[{"AttributeName": k, "AttributeType": "S"} for k, _ in keys])
    mk("subscribers", [("sid", "HASH")]); mk("alerts", [("day", "HASH"), ("aid", "RANGE")]); mk("otps", [("oid", "HASH")]); mk("interventions", [("iid", "HASH")]); mk("audit", [("aid", "HASH")])

# ---------- audit trail (append only: nothing in the app edits or deletes these rows) ----------
_AUDIT_KEYS = ("at", "actor", "role", "sid", "action", "target", "detail", "ip")
def add_audit(rec):
    if AWS: _t("audit").put_item(Item=_dec({**{k: rec.get(k, "") for k in _AUDIT_KEYS}, "aid": f"{rec['at']}#{uuid.uuid4().hex[:8]}"})); return
    with _db() as c: c.execute("INSERT INTO audit(at,actor,role,sid,action,target,detail,ip) VALUES(?,?,?,?,?,?,?,?)", tuple(rec.get(k, "") for k in _AUDIT_KEYS))

def list_audit(limit=200):
    if AWS: return sorted((_py({k: x.get(k, "") for k in _AUDIT_KEYS}) for x in _scan(_t("audit"))), key=lambda r: r["at"], reverse=True)[:limit]
    with _db() as c: return [dict(r) for r in c.execute("SELECT at,actor,role,sid,action,target,detail,ip FROM audit ORDER BY id DESC LIMIT ?", (limit,))]

# ---------- snapshot ----------
def save_snapshot(data):
    if AWS:
        _s3().put_object(Bucket=SNAP_BUCKET, Key="data.json", Body=json.dumps({"created": _now(), "data": data}), ContentType="application/json")
        return
    with _db() as c:
        c.execute("INSERT INTO snapshots(created, body) VALUES(?,?)", (_now(), json.dumps(data)))
        c.execute("DELETE FROM snapshots WHERE id NOT IN (SELECT id FROM snapshots ORDER BY id DESC LIMIT 240)")

def latest_snapshot():
    """(created_iso, data) or None."""
    if AWS:
        try: j = json.loads(_s3().get_object(Bucket=SNAP_BUCKET, Key="data.json")["Body"].read())
        except Exception as e:
            if "NoSuchKey" in str(e): return None
            raise
        return j["created"], j["data"]
    with _db() as c:
        row = c.execute("SELECT created, body FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
    return (row["created"], json.loads(row["body"])) if row else None

def _sub(r):
    d = dict(r); d["profile"] = json.loads(d.get("profile") or "{}"); return d

# ---------- subscribers ----------
def get_sub(ch, ct):
    if AWS:
        it = _t("subscribers").get_item(Key={"sid": _sid(ch, ct)}).get("Item")
        return {**_py(it), "id": it["sid"]} if it else None
    with _db() as c:
        row = c.execute("SELECT * FROM subscribers WHERE channel=? AND contact=?", (ch, ct)).fetchone()
    return _sub(row) if row else None

def put_sub(s):
    """Insert or update by (channel, contact). s: created,name,role,channel,contact,lat,lon,radius_km,active,demo."""
    if AWS:
        old = get_sub(s["channel"], s["contact"])
        item = {**s, "sid": _sid(s["channel"], s["contact"]), "created": old["created"] if old else s["created"]}
        _t("subscribers").put_item(Item=_dec(item)); return
    with _db() as c:
        c.execute("""INSERT INTO subscribers(created,name,role,channel,contact,lat,lon,radius_km,active,demo,lang,share,profile) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(channel,contact) DO UPDATE SET name=excluded.name,role=excluded.role,lat=excluded.lat,lon=excluded.lon,
            radius_km=excluded.radius_km,active=excluded.active,demo=excluded.demo,lang=excluded.lang,share=excluded.share,profile=excluded.profile""",
            (s["created"], s["name"], s["role"], s["channel"], s["contact"], s["lat"], s["lon"], s["radius_km"], s["active"], s.get("demo", 0), s.get("lang", "en"), s.get("share", 0), json.dumps(s.get("profile") or {})))

def set_active(ch, ct, active):
    if AWS:
        try: _t("subscribers").update_item(Key={"sid": _sid(ch, ct)}, UpdateExpression="SET active=:a", ConditionExpression="attribute_exists(sid)",
                                           ExpressionAttributeValues={":a": active})
        except Exception as e:
            if "ConditionalCheckFailed" not in str(e): raise
        return
    with _db() as c: c.execute("UPDATE subscribers SET active=? WHERE channel=? AND contact=?", (active, ch, ct))

def delete_sub(ch, ct):
    if AWS: _t("subscribers").delete_item(Key={"sid": _sid(ch, ct)}); return
    with _db() as c: c.execute("DELETE FROM subscribers WHERE channel=? AND contact=?", (ch, ct))

def list_subs(active_only=False):
    if AWS:
        rows = [{**r, "id": r["sid"]} for r in _scan(_t("subscribers"))]
        rows.sort(key=lambda r: r.get("created", ""), reverse=True)
    else:
        with _db() as c: rows = [_sub(r) for r in c.execute("SELECT * FROM subscribers ORDER BY id DESC")]
    return [r for r in rows if r.get("active")] if active_only else rows

# ---------- fire history (counts per 0.1 degree cell per day), used to check whether fires fall after alerts ----------
def load_cells():
    if AWS:
        try: return json.loads(_s3().get_object(Bucket=SNAP_BUCKET, Key="cells.json")["Body"].read())
        except Exception as e:
            if "NoSuchKey" in str(e): return {}
            raise
    with _db() as c:
        r = c.execute("SELECT v FROM kv WHERE k='cells'").fetchone()
    return json.loads(r["v"]) if r else {}

def merge_cells(new, keep_days=60):
    cells = load_cells()
    for k, days in new.items(): cells.setdefault(k, {}).update(days)
    cut = (datetime.date.today() - datetime.timedelta(days=keep_days)).isoformat()
    cells = {k: {d: n for d, n in v.items() if d >= cut} for k, v in cells.items()}
    body = json.dumps({k: v for k, v in cells.items() if v})
    if AWS: _s3().put_object(Bucket=SNAP_BUCKET, Key="cells.json", Body=body, ContentType="application/json")
    else:
        with _db() as c: c.execute("INSERT INTO kv(k,v) VALUES('cells',?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (body,))

# ---------- alerts ----------
def add_alert(rec, deliveries):
    if AWS:
        aid = f"{rec['created']}#{uuid.uuid4().hex[:8]}"
        _t("alerts").put_item(Item=_dec({**rec, "day": rec["created"][:10], "aid": aid,
            "deliveries": [{"sid": d[0], "status": d[1], "error": d[2]} for d in deliveries[:500]]})); return aid
    with _db() as c:
        aid = c.execute("INSERT INTO alerts(created,lat,lon,priority,message,recipients,delivered,failed,mode) VALUES(?,?,?,?,?,?,?,?,?)",
            (rec["created"], rec["lat"], rec["lon"], rec["priority"], rec["message"], rec["recipients"], rec["delivered"], rec["failed"], rec["mode"])).lastrowid
        c.executemany("INSERT INTO deliveries(alert_id,subscriber_id,status,error) VALUES(?,?,?,?)", [(aid, *d) for d in deliveries])
    return aid

_ALERT_KEYS = ("created", "lat", "lon", "priority", "recipients", "delivered", "failed", "mode")
def list_alerts(limit=100):
    if AWS:
        from boto3.dynamodb.conditions import Key
        out, day = [], datetime.date.today()
        for i in range(30):
            r = _t("alerts").query(KeyConditionExpression=Key("day").eq((day - datetime.timedelta(days=i)).isoformat()),
                                   ScanIndexForward=False, Limit=limit - len(out))
            out += [{"id": x["aid"], **{k: _py(x.get(k)) for k in _ALERT_KEYS}} for x in r["Items"]]
            if len(out) >= limit: break
        return out
    with _db() as c:
        return [dict(r) for r in c.execute("SELECT id,created,lat,lon,priority,recipients,delivered,failed,mode FROM alerts ORDER BY id DESC LIMIT ?", (limit,))]

def recent_alert(lat, lon, hours):
    cut = (datetime.datetime.utcnow() - datetime.timedelta(hours=hours)).isoformat(timespec="seconds") + "Z"
    if AWS:
        from boto3.dynamodb.conditions import Key
        for d in {datetime.date.today(), datetime.date.today() - datetime.timedelta(days=1)}:
            for x in _py(_t("alerts").query(KeyConditionExpression=Key("day").eq(d.isoformat()))["Items"]):
                if x["created"] >= cut and abs(x["lat"] - lat) < .15 and abs(x["lon"] - lon) < .15 and (x["delivered"] > 0 or x["mode"] == "log"):
                    return True
        return False
    with _db() as c:
        return c.execute("SELECT 1 FROM alerts WHERE created>=? AND abs(lat-?)<.15 AND abs(lon-?)<.15 AND (delivered>0 OR mode='log') LIMIT 1",
                         (cut, lat, lon)).fetchone() is not None

# ---------- interventions and evidence ----------
def put_intervention(doc):
    if AWS:
        _t("interventions").put_item(Item=_dec({"iid": doc["iid"], "key": doc["key"], "status": doc["status"], "created": doc["created"], "updated": doc["updated"], "doc": doc})); return
    with _db() as c:
        c.execute("""INSERT INTO interventions(iid,key,status,created,updated,doc) VALUES(?,?,?,?,?,?) ON CONFLICT(iid) DO UPDATE SET
            status=excluded.status,updated=excluded.updated,doc=excluded.doc""", (doc["iid"], doc["key"], doc["status"], doc["created"], doc["updated"], json.dumps(doc)))

def get_intervention(iid):
    if AWS:
        it = _t("interventions").get_item(Key={"iid": iid}).get("Item"); return _py(it["doc"]) if it else None
    with _db() as c:
        r = c.execute("SELECT doc FROM interventions WHERE iid=?", (iid,)).fetchone()
    return json.loads(r["doc"]) if r else None

def delete_intervention(iid):
    if AWS: _t("interventions").delete_item(Key={"iid": iid}); return
    with _db() as c: c.execute("DELETE FROM interventions WHERE iid=?", (iid,))

def list_interventions(limit=300):
    if AWS:
        rows = sorted(_scan(_t("interventions")), key=lambda r: r["created"], reverse=True)[:limit]; return [r["doc"] for r in rows]
    with _db() as c:
        return [json.loads(r["doc"]) for r in c.execute("SELECT doc FROM interventions ORDER BY created DESC LIMIT ?", (limit,))]

EVID = os.getenv("EVIDENCE_DIR", os.path.join(os.path.dirname(DB), "evidence"))
def put_evidence(iid, name, data, ctype):
    if AWS: _s3().put_object(Bucket=SNAP_BUCKET, Key=f"evidence/{iid}/{name}", Body=data, ContentType=ctype); return
    os.makedirs(os.path.join(EVID, iid), exist_ok=True)
    with open(os.path.join(EVID, iid, name), "wb") as f: f.write(data)

def get_evidence(iid, name):
    if AWS:
        try: o = _s3().get_object(Bucket=SNAP_BUCKET, Key=f"evidence/{iid}/{name}"); return o["Body"].read(), o["ContentType"]
        except Exception: return None
    p = os.path.join(EVID, iid, os.path.basename(name))
    return (open(p, "rb").read(), "image/png" if name.endswith("png") else "image/jpeg") if os.path.exists(p) else None

# ---------- one-time codes ----------
_oid = lambda ch, ct, p: hashlib.sha256(f"{ch}|{ct}|{p}".encode()).hexdigest()[:32]
def otp_get(ch, ct, p):
    if AWS:
        it = _t("otps").get_item(Key={"oid": _oid(ch, ct, p)}).get("Item"); return _py(it) if it else None
    with _db() as c:
        r = c.execute("SELECT * FROM otps WHERE channel=? AND contact=? AND purpose=?", (ch, ct, p)).fetchone()
    return dict(r) if r else None

def otp_put(ch, ct, p, code_hash, expires, sent):
    if AWS:
        _t("otps").put_item(Item=_dec({"oid": _oid(ch, ct, p), "code": code_hash, "expires": expires, "attempts": 0, "sent": sent, "ttl": int(expires) + 3600})); return
    with _db() as c:
        c.execute("""INSERT INTO otps(channel,contact,purpose,code,expires,attempts,sent) VALUES(?,?,?,?,?,0,?)
            ON CONFLICT(channel,contact,purpose) DO UPDATE SET code=excluded.code,expires=excluded.expires,attempts=0,sent=excluded.sent""",
            (ch, ct, p, code_hash, expires, sent))

def otp_bump(ch, ct, p):
    if AWS: _t("otps").update_item(Key={"oid": _oid(ch, ct, p)}, UpdateExpression="ADD attempts :one", ExpressionAttributeValues={":one": 1}); return
    with _db() as c: c.execute("UPDATE otps SET attempts=attempts+1 WHERE channel=? AND contact=? AND purpose=?", (ch, ct, p))

def otp_del(ch, ct, p):
    if AWS: _t("otps").delete_item(Key={"oid": _oid(ch, ct, p)}); return
    with _db() as c: c.execute("DELETE FROM otps WHERE channel=? AND contact=? AND purpose=?", (ch, ct, p))
