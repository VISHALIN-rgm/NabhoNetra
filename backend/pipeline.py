import csv, io, math, time, random, datetime, requests
from collections import defaultdict, Counter
import config as C
import places
import geo
from cities import CITIES

def haversine(a, b, c, d):
    p = math.pi / 180
    x = math.sin((c - a) * p / 2) ** 2 + math.cos(a * p) * math.cos(c * p) * math.sin((d - b) * p / 2) ** 2
    return 12742 * math.asin(math.sqrt(x))

def bearing(a, b, c, d):
    p = math.pi / 180
    y = math.sin((d - b) * p) * math.cos(c * p)
    x = math.cos(a * p) * math.sin(c * p) - math.sin(a * p) * math.cos(c * p) * math.cos((d - b) * p)
    return (math.degrees(math.atan2(y, x)) + 360) % 360

def _ts(r):
    d, t = r.get("acq_date", ""), str(r.get("acq_time", "")).zfill(4)
    return f"{d}T{t[:2]}:{t[2:]}:00Z" if d and t.isdigit() else ""

def _f(v):
    try: return float(v)
    except (TypeError, ValueError): return 0.0

def _is_csv(t): return t.lstrip().lower().startswith("latitude")

def fetch_fires():
    base = "https://firms.modaps.eosdis.nasa.gov/api"
    area = f"{base}/area/csv/{C.FIRMS_KEY}/VIIRS_SNPP_NRT/{C.BBOX}/{C.DAY_RANGE}"
    if C.SCOPE == "india":
        text = requests.get(f"{base}/country/csv/{C.FIRMS_KEY}/VIIRS_SNPP_NRT/{C.COUNTRY}/{C.DAY_RANGE}", timeout=90).text
        if not _is_csv(text):
            print("FIRMS country query failed, using the India bounding box instead. Response:", text[:120])
            text = requests.get(area, timeout=90).text
    else:
        text = requests.get(area, timeout=30).text
    if not _is_csv(text):
        raise RuntimeError("FIRMS did not return fire data. Response: " + text[:200])
    fires = [{"lat": float(r["latitude"]), "lon": float(r["longitude"]), "date": r.get("acq_date", ""), "ts": _ts(r),
              "conf": (r.get("confidence") or "").strip().lower()[:1], "frp": _f(r.get("frp"))} for r in csv.DictReader(io.StringIO(text))]
    print(f"FIRMS returned {len(fires)} fires over the last {C.DAY_RANGE} day(s)")
    return fires

def filter_fires(fires):
    """Drop detections unlikely to be crop burning: low satellite confidence, very weak fires, and spots seen on many different days
    (industrial heat sources such as kilns). Returns (kept, report)."""
    weak = lambda f: f.get("frp", 99) < C.MIN_FRP
    low = [f for f in fires if f.get("conf") == "l"]
    kept = [f for f in fires if f.get("conf") != "l" and not weak(f)]
    days = defaultdict(set)
    for f in kept: days[(round(f["lat"], 3), round(f["lon"], 3))].add(f.get("date"))
    static = {k for k, d in days.items() if C.STATIC_DAYS and len(d) >= C.STATIC_DAYS}
    final = [f for f in kept if (round(f["lat"], 3), round(f["lon"], 3)) not in static]
    return final, {"low_confidence": len(low), "weak": sum(1 for f in fires if f.get("conf") != "l" and weak(f)), "static_source": len(kept) - len(final)}

def cells_of(fires):
    """Fire counts per 0.1 degree cell per day: the history used to check whether fires fall after alerts."""
    out = defaultdict(lambda: defaultdict(int))
    for f in fires:
        if f.get("date"): out[f"{round(f['lat'], 1):.1f},{round(f['lon'], 1):.1f}"][f["date"]] += 1
    return {k: dict(v) for k, v in out.items()}

def mock_fires(n=140):
    random.seed(7)
    w, s, e, nn = map(float, C.BBOX.split(","))
    hubs = [(random.uniform(s, nn), random.uniform(w, e)) for _ in range(9)]
    out, today = [], datetime.date.today()
    for _ in range(n):
        la, lo = random.choice(hubs)
        dd = (today - datetime.timedelta(days=random.randint(0, 4))).isoformat()
        out.append({"lat": la + random.gauss(0, .06), "lon": lo + random.gauss(0, .06), "date": dd, "frp": round(random.uniform(2, 40), 1),
                    "conf": "l" if random.random() < .08 else random.choice("nh"), "ts": f"{dd}T{random.randint(0, 23):02d}:{random.randint(0, 59):02d}:00Z"})
    for i in range(4):   # a kiln-like heat source that burns every day
        dd = (today - datetime.timedelta(days=i)).isoformat()
        out.append({"lat": round((s + nn) / 2, 3), "lon": round((w + e) / 2, 3), "date": dd, "frp": 30.0, "conf": "h", "ts": f"{dd}T02:00:00Z"})
    return out

state = {"wind": "Open-Meteo", "forecast": "Open-Meteo forecast"}

def fetch_winds(points):
    """One batched Open-Meteo request for all clusters, with retries. Never raises."""
    params = {"latitude": ",".join(f"{p[0]:.3f}" for p in points), "longitude": ",".join(f"{p[1]:.3f}" for p in points),
              "current": "wind_speed_10m,wind_direction_10m"}
    last = ""
    for attempt in range(4):
        try:
            j = requests.get("https://api.open-meteo.com/v1/forecast", params=params, timeout=30).json()
            items = j if isinstance(j, list) else [j]
            if len(items) == len(points) and all("current" in it for it in items):
                state["wind"] = "Open-Meteo"
                return [(it["current"]["wind_direction_10m"], it["current"]["wind_speed_10m"]) for it in items]
            last = str(j)[:160]
        except Exception as e:
            last = str(e)
        time.sleep(1.5 * (attempt + 1))
    print("Open-Meteo wind unavailable, using an assumed north-westerly wind instead:", last)
    state["wind"] = "assumed"
    return [(305.0, 11.0)] * len(points)

def mock_winds(points):
    state["wind"] = "sample"
    return [(305.0, 11.0)] * len(points)

def fetch_forecasts(points):
    """Hourly wind forecast for each point: a list of [(direction_from_deg, speed_kmh)], or None if unavailable."""
    params = {"latitude": ",".join(f"{p[0]:.3f}" for p in points), "longitude": ",".join(f"{p[1]:.3f}" for p in points),
              "hourly": "wind_speed_10m,wind_direction_10m", "forecast_hours": C.FORECAST_HOURS, "timezone": "UTC"}
    for attempt in range(3):
        try:
            j = requests.get("https://api.open-meteo.com/v1/forecast", params=params, timeout=30).json()
            items = j if isinstance(j, list) else [j]
            if len(items) == len(points) and all("hourly" in it for it in items):
                state["forecast"] = "Open-Meteo forecast"
                return [list(zip(it["hourly"]["wind_direction_10m"], it["hourly"]["wind_speed_10m"])) for it in items]
        except Exception as e:
            print("forecast request failed:", type(e).__name__)
        time.sleep(1.5 * (attempt + 1))
    return None

def mock_forecasts(points):
    state["forecast"] = "sample"
    return [[(305.0 + h * 1.5, 11.0 + (h % 5)) for h in range(C.FORECAST_HOURS)] for _ in points]

def trajectory(lat, lon, hourly, city=None):
    """Move a smoke parcel hour by hour with the forecast wind. Returns (hours until it is within SMOKE_REACH_KM of the city or None, closest approach km)."""
    city = city or (C.CITY_LAT, C.CITY_LON)
    la, lo, eta = lat, lon, None
    closest = haversine(la, lo, *city)
    for h, (wfrom, spd) in enumerate(hourly, start=1):
        to, km = math.radians((wfrom + 180) % 360), spd * C.SMOKE_SPEED_FACTOR
        la += math.degrees(km * math.cos(to) / 6371)
        lo += math.degrees(km * math.sin(to) / (6371 * max(math.cos(math.radians(la)), 0.01)))
        d = haversine(la, lo, *city); closest = min(closest, d)
        if eta is None and d <= C.SMOKE_REACH_KM: eta = h
    return eta, round(closest, 1)

def fetch_city_aqi():
    try:
        r = requests.get("https://air-quality-api.open-meteo.com/v1/air-quality", timeout=20, params={
            "latitude": C.CITY_LAT, "longitude": C.CITY_LON, "current": "us_aqi"}).json()
        return r["current"]["us_aqi"]
    except Exception:
        return None

def _target(lat, lon):
    """(city_lat, city_lon, city_name) the smoke is judged against: the one target city, or the nearest major city in india scope."""
    if C.SCOPE != "india": return C.CITY_LAT, C.CITY_LON, None
    n, la, lo = min(CITIES, key=lambda c: haversine(lat, lon, c[1], c[2]))
    return la, lo, n

def build_clusters(fires, wind_fn, forecast_fn=None):
    cells = defaultdict(list)
    for f in fires:
        cells[(round(f["lat"] / C.GRID), round(f["lon"] / C.GRID))].append(f)
    groups = sorted(cells.values(), key=len, reverse=True)[:C.MAX_CLUSTERS]
    cents = [(sum(p["lat"] for p in g) / len(g), sum(p["lon"] for p in g) / len(g)) for g in groups]
    winds = wind_fn(cents) if cents else []
    fcs = forecast_fn(cents) if cents and forecast_fn else None
    if cents and fcs is None: state["forecast"] = "current wind held constant"
    out = []
    for i, (pts, (lat, lon), (wfrom, wspd)) in enumerate(zip(groups, cents, winds)):
        tla, tlo, tname = _target(lat, lon)
        dist = haversine(lat, lon, tla, tlo)
        ts = [q["ts"] for q in pts if q.get("ts")]
        to_city = bearing(lat, lon, tla, tlo)
        align = max(0.0, math.cos(math.radians(to_city - (wfrom + 180) % 360)))   # 1 = current wind blows straight at the city
        eta, closest = trajectory(lat, lon, fcs[i] if fcs else [(wfrom, wspd)] * C.FORECAST_HOURS, city=(tla, tlo))
        reach = 1.0 if eta is not None or dist <= C.SMOKE_REACH_KM else max(0.0, 1 - closest / dist)
        frps = [q.get("frp", 0) for q in pts]
        heat = 1.0 if not any(frps) else 0.8 + 0.4 * min(1, (sum(frps) / len(frps)) / 15)
        score = round(len(pts) * (0.3 + reach) * (300 / (dist + 100)) * heat, 1)
        out.append({"lat": round(lat, 4), "lon": round(lon, 4), "fires": len(pts), "distance_km": round(dist),
                    "wind_from": round(wfrom), "wind_speed": round(wspd), "alignment": round(align, 2), "score": score,
                    "reach": round(reach, 2), "eta_hours": eta, "closest_km": closest, "frp_total": round(sum(frps), 1),
                    "first_detected": min(ts, default=""), "last_detected": max(ts, default=""),
                    "city_name": tname, "city_lat": tla, "city_lon": tlo})
    out.sort(key=lambda c: c["score"], reverse=True)
    for i, c in enumerate(out):
        c["id"] = f"C{i+1}"
        c["priority"] = "high" if i < 3 else "medium" if i < 8 else "low"
    return out

def config_key(mock=False):
    """Identifies the settings a snapshot was built with; a different key means the saved snapshot is out of date."""
    return f"{C.SCOPE}|{C.BBOX}|{C.CITY_LAT},{C.CITY_LON}|{C.DAY_RANGE}|{C.MAX_CLUSTERS}|{'mock' if mock else 'live'}"

def run(mock=False, alert_fn=None, notify_fn=None):
    raw = mock_fires() if mock else fetch_fires()
    fires, filtered = filter_fires(raw)
    clusters = build_clusters(fires, mock_winds if mock else fetch_winds, mock_forecasts if mock else fetch_forecasts)
    places.ALLOW_SAMPLE = mock
    places.load([(c["lat"], c["lon"]) for c in clusters], network=not mock)
    for c in clusters:
        c["place"] = geo.locate(c["lat"], c["lon"], network=not mock)
    for c in clusters:
        c["alert"] = alert_fn(c) if alert_fn else {"text": "", "alternatives": []}
        c["status"] = "pending"
        if c["priority"] == "high" and notify_fn:
            c["status"] = notify_fn(c) or "pending"
    return {"updated": datetime.datetime.utcnow().isoformat(timespec="minutes") + "Z",
            "scope": C.SCOPE, "cfg": config_key(mock),
            "city": ({"lat": 22.9, "lon": 79.0, "aqi": None, "scope": "india"} if C.SCOPE == "india"
                     else {"lat": C.CITY_LAT, "lon": C.CITY_LON, "aqi": None if mock else fetch_city_aqi(), "scope": "city"}),
            "fires_total": len(fires), "fires_raw": len(raw), "filtered": filtered, "place": geo.names(),
            "alternatives_source": places.get()[1], "wind_source": state["wind"], "forecast_source": state["forecast"],
            "daily": [{"date": d, "count": n} for d, n in sorted(Counter(f.get("date", "") for f in fires).items())],
            "mock": mock, "clusters": clusters, "_cells": cells_of(fires)}
