import os

def parse_env(text):
    """Parse .env text: KEY=value lines, optional `export `, quotes around values, and `# comments` (whole-line, or after a space following the value)."""
    out = {}
    for line in text.lstrip("\ufeff").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        k, v = line.split("=", 1)
        k, v = k.strip().removeprefix("export ").strip(), v.strip()
        if not k or " " in k: continue
        if v[:1] in "\"'" and v[:1] and v.find(v[0], 1) > 0: v = v[1:v.find(v[0], 1)]      # quoted: keep everything inside the quotes
        else:
            for i, ch in enumerate(v):
                if ch == "#" and i > 0 and v[i - 1] in " \t": v = v[:i]; break              # inline comment
            v = v.strip()
        out[k] = v
    return out

def _load_env():
    f = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(f):
        for k, v in parse_env(open(f, encoding="utf-8").read()).items():
            os.environ.setdefault(k, v)          # real environment variables win over the file
_load_env()
BBOX = os.getenv("BBOX", "74.0,29.0,77.0,32.0")        # west,south,east,north of the farming region
CITY_LAT = float(os.getenv("CITY_LAT", "28.6"))         # target city
CITY_LON = float(os.getenv("CITY_LON", "77.2"))
ALERT_LANG = os.getenv("ALERT_LANG", "English")           # language of farmer alerts
FIRMS_KEY = os.getenv("FIRMS_KEY", "")
DAY_RANGE = int(os.getenv("DAY_RANGE", "3"))             # days of fire history to pull (1-5)
BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "us.meta.llama3-3-70b-instruct-v1:0")
BEDROCK_REGION = os.getenv("BEDROCK_REGION", "us-west-2")   # must match the region where you enabled the model
GRID = 0.1                                              # cluster cell size in degrees (~10 km)
ALT_MAX_KM = float(os.getenv("ALT_MAX_KM", "250" if os.getenv("SCOPE", "city").strip().lower() == "india" else "0"))   # drop alternatives farther than this (0 = no limit)
SCOPE = os.getenv("SCOPE", "city").strip().lower()      # city = one target city (default); india = all of India from NASA FIRMS
COUNTRY = os.getenv("COUNTRY", "IND")                  # FIRMS country code used when SCOPE=india
INDIA_BBOX = "68.1,6.7,97.4,37.1"                       # fallback box if the FIRMS country query fails (also covers parts of neighbouring countries)
MAX_CLUSTERS = int(os.getenv("MAX_CLUSTERS", "25" if SCOPE == "india" else "15"))
CITY_NAME = os.getenv("CITY_NAME", "")       # optional: name shown on the dashboard (otherwise looked up from coordinates)
REGION_NAME = os.getenv("REGION_NAME", "India" if SCOPE == "india" else "")
MIN_FRP = float(os.getenv("MIN_FRP", "0"))                    # drop detections with less fire radiative power (MW); 0 = keep all
STATIC_DAYS = int(os.getenv("STATIC_DAYS", "3"))               # a spot detected on this many different days is treated as industrial; 0 = off
SMOKE_REACH_KM = float(os.getenv("SMOKE_REACH_KM", "30"))      # smoke counts as reaching the city when within this distance
SMOKE_SPEED_FACTOR = float(os.getenv("SMOKE_SPEED_FACTOR", "0.8"))   # smoke drifts slower than the 10 m wind
FORECAST_HOURS = int(os.getenv("FORECAST_HOURS", "24"))
ALERT_WINDOW_UTC = os.getenv("ALERT_WINDOW_UTC", "0-24")   # automatic alerts only go out in this UTC hour range, e.g. 1-7 for mornings in UTC+5:30

if SCOPE == "india" and "BBOX" not in os.environ:
    BBOX = INDIA_BBOX
