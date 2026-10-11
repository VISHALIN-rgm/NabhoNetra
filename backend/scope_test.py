"""Checks SCOPE=india offline: FIRMS country query (and fallback), clusters paired with nearest cities, alert wording."""
import os
os.environ.update(SCOPE="india", FIRMS_KEY="TESTKEY", USE_AGENT="0")
os.environ.pop("BBOX", None)
import config as C, pipeline, agent
from unittest import mock

assert C.SCOPE == "india" and C.BBOX == C.INDIA_BBOX and C.REGION_NAME == "India" and C.MAX_CLUSTERS == 25

CSV = "latitude,longitude,acq_date,acq_time,confidence,frp\n30.1,75.2,2026-10-09,0732,n,12.5\n19.0,73.0,2026-10-09,0100,h,5\n"
class R:
    def __init__(s, t): s.text = t
urls = []
def get_ok(url, **k): urls.append(url); return R(CSV)
with mock.patch.object(pipeline.requests, "get", get_ok):
    f = pipeline.fetch_fires()
assert len(f) == 2 and "/api/country/csv/TESTKEY/VIIRS_SNPP_NRT/IND/" in urls[0], urls

urls.clear()
def get_fallback(url, **k): urls.append(url); return R("Invalid MAP_KEY" if "/country/" in url else CSV)
with mock.patch.object(pipeline.requests, "get", get_fallback):
    f = pipeline.fetch_fires()
assert len(f) == 2 and "/api/area/csv/" in urls[1] and C.INDIA_BBOX in urls[1], urls

def get_bad(url, **k): return R("Invalid MAP_KEY")
with mock.patch.object(pipeline.requests, "get", get_bad):
    try: pipeline.fetch_fires(); raise SystemExit("should have raised")
    except RuntimeError: pass

d = pipeline.run(mock=True, alert_fn=agent.write_alert)
cl = d["clusters"]
assert d["scope"] == "india" and d["city"]["scope"] == "india" and d["fires_total"] > 0 and cl
assert all(c["city_name"] and c["city_lat"] and c["distance_km"] >= 0 for c in cl)
assert len(cl) <= 25 and len({c["city_name"] for c in cl}) > 1, "clusters should map to different cities"
assert any(c["city_name"] in c["alert"]["text"] for c in cl if c["priority"] == "high"), "alert should name the city"
print("India scope checks passed:", len(cl), "clusters,", len({c['city_name'] for c in cl}), "different cities")
