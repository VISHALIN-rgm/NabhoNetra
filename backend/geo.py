"""Names the monitored region and target city from coordinates (OpenStreetMap Nominatim), cached. Override with CITY_NAME / REGION_NAME."""
import json, os
import requests
import config as C

CACHE = os.path.join(os.path.dirname(__file__), "place_cache.json")
HEADERS = {"User-Agent": "NabhoNetra/1.0 (crop-fire monitoring; " + os.getenv("CONTACT_EMAIL", "set CONTACT_EMAIL") + ")"}

def _rev(lat, lon, zoom, region):
    key = f"{lat:.2f},{lon:.2f},{zoom}"
    try: cache = json.load(open(CACHE, encoding="utf-8"))
    except Exception: cache = {}
    if cache.get(key): return cache[key]
    try:
        a = requests.get("https://nominatim.openstreetmap.org/reverse", timeout=15, headers=HEADERS,
            params={"format": "jsonv2", "lat": lat, "lon": lon, "zoom": zoom, "accept-language": "en"}).json().get("address", {})
        parts = [a.get("state"), a.get("country")] if region else [
            a.get("city") or a.get("town") or a.get("village") or a.get("state_district") or a.get("county"), a.get("state"), a.get("country")]
        name = ", ".join(p for p in parts if p)
        if name:
            cache[key] = name
            try: json.dump(cache, open(CACHE, "w", encoding="utf-8"))
            except Exception: pass
        return name
    except Exception as e:
        print("place lookup failed:", type(e).__name__)
        return ""

def locate(lat, lon, network=True):
    """Place name for a fire cluster (village, district, state), cached per ~11 km cell. Empty string if unknown."""
    import time
    key = f"loc:{lat:.1f},{lon:.1f}"
    try: cache = json.load(open(CACHE, encoding="utf-8"))
    except Exception: cache = {}
    if cache.get(key) or not network: return cache.get(key, "")
    try:
        time.sleep(1.1)   # Nominatim allows 1 request per second
        a = requests.get("https://nominatim.openstreetmap.org/reverse", timeout=15, headers=HEADERS,
            params={"format": "jsonv2", "lat": lat, "lon": lon, "zoom": 12, "accept-language": "en"}).json().get("address", {})
        parts = [a.get("village") or a.get("hamlet") or a.get("town") or a.get("suburb") or a.get("city"), a.get("state_district") or a.get("county"), a.get("state")]
        name = ", ".join(dict.fromkeys(p for p in parts if p))
        if name:
            cache[key] = name
            try: json.dump(cache, open(CACHE, "w", encoding="utf-8"))
            except Exception: pass
        return name
    except Exception as e:
        print("place lookup failed:", type(e).__name__)
        return ""

def names():
    w, s, e, n = map(float, C.BBOX.split(","))
    return {"city": C.CITY_NAME or _rev(C.CITY_LAT, C.CITY_LON, 10, False),
            "region": C.REGION_NAME or _rev((s + n) / 2, (w + e) / 2, 6, True)}

_last = {"t": 0.0}
def search(q):
    """Find places by free text (village, district, state) with OpenStreetMap Nominatim. Cached; at most one request per second."""
    import time
    key = "q:" + q.lower()
    try: cache = json.load(open(CACHE, encoding="utf-8"))
    except Exception: cache = {}
    if key in cache: return cache[key]
    try:
        time.sleep(max(0, 1.1 - (time.time() - _last["t"]))); _last["t"] = time.time()
        rows = requests.get("https://nominatim.openstreetmap.org/search", timeout=15, headers=HEADERS,
            params={"q": q, "format": "jsonv2", "limit": 5, "accept-language": "en"}).json()
        out = [{"name": r["display_name"][:120], "lat": float(r["lat"]), "lon": float(r["lon"])} for r in rows]
        if out:
            cache[key] = out
            try: json.dump(cache, open(CACHE, "w", encoding="utf-8"))
            except Exception: pass
        return out
    except Exception as e:
        print("place search failed:", type(e).__name__)
        return []
