import datetime as dt, os, re
from pipeline import haversine
import config as C
import places

LANGS = {"en": "English", "hi": "Hindi", "pa": "Punjabi"}
extra_providers = lambda: []     # server.py sets this to registered providers who agreed to be listed
_failed = False
_cache, _tcache = {}, {}

def nearby_alternatives(lat, lon, n=3):
    pool = [{**p, "registered": False} for p in places.get()[0]] + extra_providers()
    rows = [{"name": p["name"], "type": p["type"], "km": round(haversine(lat, lon, p["lat"], p["lon"])), "contact": p["contact"],
             "registered": bool(p.get("registered"))} for p in pool]
    if C.ALT_MAX_KM: rows = [r for r in rows if r["km"] <= C.ALT_MAX_KM]
    return sorted(rows, key=lambda r: r["km"] - (10 if r["registered"] else 0))[:n]   # contact-verified providers get a 10 km head start

def _when(c):
    try: return dt.datetime.fromisoformat(c.get("last_detected", "").rstrip("Z")).strftime("%d %b %H:%M UTC").lstrip("0")
    except Exception: return "time unknown"

def _where(c):
    if c.get("place"): return c["place"]
    return f"{abs(c['lat']):.2f}{'N' if c['lat'] >= 0 else 'S'}, {abs(c['lon']):.2f}{'E' if c['lon'] >= 0 else 'W'}"

def _city(c): return c.get("city_name") or "the city"

def _eta(c):
    return f" Smoke may reach {_city(c)} in about {c['eta_hours']} hours." if c.get("eta_hours") else ""

def _template(c, alts):
    tag = {"high": "URGENT", "medium": "Notice", "low": "Advisory"}[c["priority"]]
    msg = (f"{tag} ({c['id']}): {c['fires']} crop-fire detections near {_where(c)} (latest detection {_when(c)}), {c['distance_km']} km from {_city(c)}, "
           f"wind {c['wind_speed']} km/h.{_eta(c)} Please do not burn the residue.")
    if alts:
        a = alts[0]
        msg += f" Nearest option: {a['type']} - {a['name']}, {a['km']} km away, contact {a['contact']}."
        if len(alts) > 1: msg += f" Also: {alts[1]['name']} ({alts[1]['km']} km)."
    return msg

def _model():
    prov = os.getenv("MODEL_PROVIDER", "bedrock").lower(); mid = os.getenv("MODEL_ID")
    if prov == "openai":
        from strands.models.openai import OpenAIModel
        return OpenAIModel(client_args={"api_key": os.environ["MODEL_API_KEY"], "base_url": os.getenv("MODEL_BASE_URL") or None}, model_id=mid, params={"temperature": 0.5})
    if prov == "ollama":
        from strands.models.ollama import OllamaModel
        return OllamaModel(host=os.getenv("MODEL_BASE_URL", "http://localhost:11434"), model_id=mid or "llama3.1", temperature=0.5)
    from strands.models import BedrockModel
    return BedrockModel(model_id=mid or C.BEDROCK_MODEL_ID, region_name=os.getenv("AWS_REGION") or C.BEDROCK_REGION, temperature=0.5)

def check_alert(text, c, alts):
    """Facts the alert must contain. Returns a list of problems (empty = fine to send)."""
    t, bad = (text or "").strip(), []
    if not t: return ["empty"]
    if len(t) > 400 or len(t.split()) > 70: bad.append("too long")
    if re.search(r"[\[\]{}<>]|N/A|TODO|lorem", t, re.I): bad.append("contains placeholder text")
    if str(c["fires"]) not in t: bad.append(f"must state the fire count {c['fires']}")
    place = (c.get("place") or "").split(",")[0].strip()
    if place and place.lower() not in t.lower(): bad.append(f"must name the place {place}")
    if alts:
        a = alts[0]
        if a["name"].lower() not in t.lower() and not (any(ch.isdigit() for ch in a["contact"]) and a["contact"] in t): bad.append("must name the nearest alternative")
    if C.ALERT_LANG.lower() == "english" and sum(ord(ch) > 127 for ch in t) > 0.1 * len(t): bad.append("must be in English")
    return bad

def _ask(system, prompt):
    from strands import Agent
    return re.sub(r"<think>.*?</think>", "", str(Agent(model=_model(), callback_handler=None, system_prompt=system)(prompt)), flags=re.S).strip()

SYSTEM = (f"You write short SMS alerts for farmers in {C.ALERT_LANG}. Max 45 words. Calm, practical tone. Every alert must be specific to the cluster facts given: "
          "mention the fire count, the place name and when it was detected, and the nearest alternative with its distance and contact. If a smoke arrival time is given, mention it. "
          "Match urgency to priority (high = act today, medium = avoid burning this week, low = advisory). Do not promise availability, prices or subsidies. Reply with the message text only.")

def write_alert(c):
    """AI-written alert, checked against the facts; retries once, then falls back to the plain template. Low-priority clusters use the template (saves cost)."""
    global _failed
    alts = nearby_alternatives(c["lat"], c["lon"])
    text, source = _template(c, alts), "template"
    if os.getenv("USE_AGENT", "1") == "1" and not _failed and c["priority"] != "low":
        key = (round(c["lat"], 1), round(c["lon"], 1), c["fires"], c["priority"], c.get("place"), c.get("eta_hours"), alts[0]["name"] if alts else "")
        if key in _cache:
            return {"text": _cache[key], "alternatives": alts, "source": "model"}
        options = "; ".join(f"{a['type']}: {a['name']}, {a['km']} km, {a['contact']}" for a in alts)
        eta = f" Forecast: smoke may reach {_city(c)} in about {c['eta_hours']} hours." if c.get("eta_hours") else f" Forecast: smoke is not expected to reach {_city(c)} soon."
        prompt = (f"Cluster {c['id']}, priority {c['priority']}. {c['fires']} fire detections near {_where(c)}, latest detection {_when(c)}, "
                  f"{c['distance_km']} km from {_city(c)}, wind {c['wind_speed']} km/h.{eta} Nearest alternatives to burning: {options}. Write the alert in {C.ALERT_LANG}.")
        try:
            reply = _ask(SYSTEM, prompt); problems = check_alert(reply, c, alts)
            if problems:
                reply = _ask(SYSTEM, prompt + " Your previous attempt was rejected: " + "; ".join(problems) + ". Fix this."); problems = check_alert(reply, c, alts)
            if not problems:
                text, source = reply, "model"; _cache[key] = reply
            else:
                print(f"Alert {c['id']}: model text failed checks ({'; '.join(problems)}), using template")
        except Exception as e:
            _failed = True   # stop retrying so the error shows once
            print("AI model unavailable, using template for all alerts:", e)
    return {"text": text, "alternatives": alts, "source": source}

def translate(text, lang):
    """Translate an alert. Falls back to the English original if no model is available or any number changes."""
    if lang == "en" or lang not in LANGS or os.getenv("USE_AGENT", "1") != "1" or _failed: return text
    if (text, lang) in _tcache: return _tcache[(text, lang)]
    out = text
    try:
        r = _ask(f"Translate SMS alerts into {LANGS[lang]}. Keep every number, name, phone number and email exactly as written, using digits 0-9 only. Reply with the translation only.", text)
        if r and len(r) < 700 and sorted(re.findall(r"\d+", r)) == sorted(re.findall(r"\d+", text)): out = r
    except Exception as e:
        print("translation unavailable:", e)
    _tcache[(text, lang)] = out
    return out
