"""Adds DEMO data so the dashboard can be shown working: six demo subscribers around the current fire clusters and five demo interventions
at every stage (open, requests sent, accepted, completed, verified). Everything is flagged demo: demo people are never messaged, and demo data is
hidden (and never counted in results) unless INCLUDE_DEMO=1, which is ignored in live mode.
Usage: python seed_demo.py            (add)      python seed_demo.py --remove     (delete it all)"""
import datetime, sys
import config as C, engine, store

PROFILES = {"farmer": {"land_acres": 8, "crop": "paddy", "harvest_status": "harvested", "needs": ["seeder"]}, "machine_provider": {"machines": ["seeder", "baler"], "availability": "available"},
            "biomass_buyer": {"materials": ["paddy_straw"], "capacity_tpd": 20}, "officer": {"designation": "Demo officer"}}
STAGES = ["open", "coordinating", "accepted", "completed", "verified"]
now = lambda: datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z"

def _clusters():
    snap = store.latest_snapshot()
    if snap and snap[1]["clusters"]: return snap[1]["clusters"][:3]
    w, s, e, n = map(float, C.BBOX.split(","))
    return [{"id": "D1", "lat": (s + n) / 2, "lon": (w + e) / 2, "priority": "high", "fires": 12, "place": "Demo area", "eta_hours": 8, "reach": 1.0, "last_detected": now(), "first_detected": now()}]

def seed():
    """A demo farmer, machine provider and biomass buyer near each of the top clusters, plus one officer. Returns how many demo subscribers were added."""
    pts, rows = [(c["lat"], c["lon"]) for c in _clusters()], []
    for k, (la, lo) in enumerate(pts, 1):
        rows += [(f"Demo farmer {k}", "farmer", la + .02, lo + .01, 12), (f"Demo machine provider {k}", "machine_provider", la + .05, lo - .02, 25),
                 (f"Demo biomass buyer {k}", "biomass_buyer", la - .04, lo - .03, 30)]
    rows.append(("Demo officer", "officer", pts[0][0], pts[0][1], 50))
    for i, (name, role, la, lo, rad) in enumerate(rows, 1):
        store.put_sub({"created": now(), "name": name, "role": role, "channel": "email", "contact": f"demo-{i}@example.com", "lat": round(la, 4), "lon": round(lo, 4),
                       "radius_km": rad, "active": 1, "demo": 1, "lang": "en", "share": 1 if role != "officer" else 0,
                       "profile": {**engine.clean_profile(role, PROFILES[role]), "consent": {"at": now(), "channel": "email", "version": 1}}})
    seed_interventions()
    return len(rows)

def seed_interventions():
    subs, clusters = [s for s in store.list_subs(True) if s.get("demo")], _clusters()
    for i, stage in enumerate(STAGES):
        c = dict(clusters[i % len(clusters)], priority="high")
        a = engine.assess(c, subs, {}, [])
        iv = {"iid": f"demo{i + 1}", "key": f"demo|{i}|{engine.ckey(c)}", "status": "open", "demo": True, "created": now(), "updated": now(),
              "cluster": {k: c.get(k) for k in ("id", "lat", "lon", "place", "priority", "fires", "eta_hours", "last_detected")}, "analysis": a, "plan": engine.plan_of(a),
              "matches": engine.candidates(c, subs, a), "events": [{"at": now(), "text": "Demo: intervention opened from satellite detections."}], "evidence": [], "satellite": None, "verification": None}
        n = STAGES.index(stage)
        if n >= 1:
            for m in iv["matches"]: m["status"] = "asked"
            iv["status"] = "coordinating"; iv["events"].append({"at": now(), "text": "Demo: requests sent to matched parties."})
        if n >= 2 and iv["matches"]:
            iv["matches"][0]["status"] = "accepted"; iv["status"] = "accepted"; iv["events"].append({"at": now(), "text": "Demo: a matched party accepted the request."})
        if n >= 3 and iv["matches"]:
            iv["matches"][0]["status"] = "completed"; iv["status"] = "completed"; iv["completed_at"] = now()
            iv["evidence"].append({"type": "note", "by": iv["matches"][0]["sid"], "text": "Demo: sowed through residue on 8 acres.", "at": now()})
            iv["events"].append({"at": now(), "text": "Demo: completion reported with a note."})
        if n >= 4 and iv["matches"]:
            iv["status"] = "verified"; iv["satellite"] = {"days_checked": 3, "fires_after": 0, "checked_at": now()}
            iv["verification"] = {"approved": True, "note": "Demo verification", "at": now()}; iv["events"].append({"at": now(), "text": "Demo: officer verified the outcome."})
        store.put_intervention(iv)

def remove():
    n = 0
    for s in store.list_subs():
        if s.get("demo"): store.delete_sub(s["channel"], s["contact"]); n += 1
    for iv in store.list_interventions(500):
        if iv.get("demo"): store.delete_intervention(iv["iid"])
    return n

if __name__ == "__main__":
    store.init()
    print(f"Removed {remove()} demo subscribers and their interventions" if "--remove" in sys.argv
          else f"Added {seed()} demo subscribers and 5 demo interventions (hidden unless INCLUDE_DEMO=1, and only in test mode)")
