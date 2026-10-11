"""Did fires fall after alerts? Compares fire counts in the 2 days after an alert with the 2 days up to it, for areas that were alerted
versus other active areas on the same days. This shows an association only; fires also fall naturally as the burning season ends."""
import datetime, statistics

def _key(lat, lon): return f"{round(lat, 1):.1f},{round(lon, 1):.1f}"
def _nbrs(k):
    la, lo = map(float, k.split(","))
    return [f"{round(la + a, 1):.1f},{round(lo + b, 1):.1f}" for a in (-.1, 0, .1) for b in (-.1, 0, .1)]

def _empty(note): return {"enough": False, "alerted": {"n": 0, "median_change_pct": None}, "other": {"n": 0, "median_change_pct": None}, "note": note}

def effect(cells, alerts, min_before=3, min_cases=3):
    """cells: {"lat,lon": {date: fire_count}} per 0.1 degree cell. alerts: rows with created, lat, lon, delivered, mode."""
    dates = sorted({d for v in cells.values() for d in v})
    if len(dates) < 4: return _empty("Needs at least 4 days of fire data. Check back in a few days.")
    one, last = datetime.timedelta(days=1), datetime.date.fromisoformat(dates[-1])
    total = lambda k, days: sum(cells.get(n, {}).get(d.isoformat(), 0) for n in _nbrs(k) for d in days)
    sent = {(_key(a["lat"], a["lon"]), a["created"][:10]) for a in alerts if a.get("lat") is not None and (a.get("delivered", 0) > 0 or a.get("mode") == "log")}
    ever = {k for k, _ in sent}   # areas that were alerted at any time are not used as the comparison group
    hit, other = [], []
    for k in cells:
        for ds in dates:
            day = datetime.date.fromisoformat(ds)
            if day + 2 * one > last: continue
            before = total(k, [day - one, day])
            if before < min_before: continue
            change = (total(k, [day + one, day + 2 * one]) - before) / before * 100
            if (k, ds) in sent: hit.append(change)
            elif not any(n in ever for n in _nbrs(k)): other.append(change)
    med = lambda v: round(statistics.median(v), 1) if v else None
    return {"enough": len(hit) >= min_cases and len(other) >= min_cases, "alerted": {"n": len(hit), "median_change_pct": med(hit)},
            "other": {"n": len(other), "median_change_pct": med(other)},
            "note": "Compares fire counts in the 2 days after an alert with the 2 days up to it, for alerted areas and for other active areas on the same days."}
