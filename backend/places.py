"""Real nearby alternatives from OpenStreetMap (Overpass API), fetched in small 1-degree tiles and cached.
Falls back to alternatives.csv (sample data) only if nothing real is available."""
import csv, json, math, os, time, requests

CACHE = os.path.join("/tmp" if os.getenv("AWS_LAMBDA_FUNCTION_NAME") else os.path.dirname(__file__), "alternatives_cache.json")
MIRRORS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
           "https://overpass.private.coffee/api/interpreter"]
HEADERS = {"User-Agent": "NabhoNetra/1.0 (hackathon crop-fire project)", "Accept": "application/json"}
BUDGET_S = 150          # stop fetching new tiles after this many seconds; cached tiles still load next run
_result = None
ALLOW_SAMPLE = False   # sample listings are only for mock mode, never shown to real users

def _parse(elements):
    out = []
    for el in elements:
        t = el.get("tags", {})
        lat = el.get("lat") or el.get("center", {}).get("lat"); lon = el.get("lon") or el.get("center", {}).get("lon")
        if lat is None or lon is None:
            continue
        bio = "plant:source" in t or "generator:source" in t
        out.append({"name": t.get("name") or ("Biomass power plant" if bio else "Agri shop (unnamed)"),
                    "type": "Biomass power plant" if bio else "Agri machinery / supplies shop",
                    "lat": float(lat), "lon": float(lon),
                    "contact": t.get("phone") or t.get("contact:phone") or "no phone listed"})
    return out

def _fetch_tile(la, lo):
    b = f"{la},{lo},{la+1},{lo+1}"
    q = (f'[out:json][timeout:30];(nwr["shop"~"^(agrarian|tractor)$"]({b});nwr["power"="plant"]["plant:source"="biomass"]({b});'
         f'nwr["power"="generator"]["generator:source"="biomass"]({b}););out center tags;')
    for url in MIRRORS:
        try:
            r = requests.post(url, data={"data": q}, headers=HEADERS, timeout=35)
            if r.status_code == 200:
                return _parse(r.json().get("elements", []))
            print(f"  tile {la},{lo}: {url.split('/')[2]} HTTP {r.status_code}")
        except Exception as e:
            print(f"  tile {la},{lo}: {url.split('/')[2]} {type(e).__name__}")
    return None

def _read_cache():
    try:
        if os.getenv("DATA_BUCKET"):
            import boto3
            return json.loads(boto3.client("s3").get_object(Bucket=os.environ["DATA_BUCKET"], Key="alternatives_cache.json")["Body"].read())
        return json.load(open(CACHE, encoding="utf-8"))
    except Exception:
        return {}

def _write_cache(cache):
    try:
        if os.getenv("DATA_BUCKET"):
            import boto3
            boto3.client("s3").put_object(Bucket=os.environ["DATA_BUCKET"], Key="alternatives_cache.json", Body=json.dumps(cache))
        else:
            json.dump(cache, open(CACHE, "w", encoding="utf-8"))
    except Exception as e:
        print("could not save listings cache:", e)

def _sample():
    rows = list(csv.DictReader(open(os.path.join(os.path.dirname(__file__), "alternatives.csv"), encoding="utf-8")))
    return ([{**r, "lat": float(r["lat"]), "lon": float(r["lon"])} for r in rows], "sample")

def load(points, network=True):
    """points: [(lat, lon)] of fire clusters. Fetches only the tiles near them, then merges every cached tile."""
    global _result
    cache = {"tiles": {}}
    d = _read_cache()
    if isinstance(d.get("tiles"), dict):
        cache = d
    if network:
        need = {(math.floor(la + a), math.floor(lo + b)) for la, lo in points for a in (-.4, 0, .4) for b in (-.4, 0, .4)}
        need = [t for t in sorted(need) if f"{t[0]},{t[1]}" not in cache["tiles"]]
        start = time.time()
        if need:
            print(f"Fetching OpenStreetMap listings for {len(need)} area tile(s)...")
        for la, lo in need:
            if time.time() - start > BUDGET_S:
                print("Time budget reached; remaining tiles will load on the next run.")
                break
            res = _fetch_tile(la, lo)
            if res is not None:
                cache["tiles"][f"{la},{lo}"] = res
                _write_cache(cache)
            time.sleep(1)
    merged, seen = [], set()
    for tile in cache["tiles"].values():
        for p in tile:
            k = (p["name"], round(p["lat"], 4), round(p["lon"], 4))
            if k not in seen:
                seen.add(k); merged.append(p)
    if merged:
        print(f"Using {len(merged)} real alternatives from OpenStreetMap")
        _result = (merged, "OpenStreetMap")
    else:
        print("No OpenStreetMap listings available yet, using sample list (run again to retry).")
        _result = _sample() if ALLOW_SAMPLE else ([], "none")

def get():
    global _result
    if _result is None:
        _result = _sample() if ALLOW_SAMPLE else ([], "none")
    return _result
