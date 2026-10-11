"""Offline checks for the agent's decision logic. Run: python eval_agent.py   (add --live to also try the configured AI model)"""
import os, sys, datetime, tempfile
os.environ.update(DB_PATH=os.path.join(tempfile.mkdtemp(), "e.db"), TOKEN_SECRET="eval-secret")
import agent, config as C, impact, pipeline, engine, store

C.STATIC_DAYS, C.MIN_FRP = 3, 5.0
cluster = dict(id="C1", priority="high", lat=30.1, lon=75.2, fires=12, distance_km=240, wind_speed=14, place="Sample Village, Sample District",
               last_detected="2026-10-07T09:30:00Z", eta_hours=9)
alts = [dict(name="Sample Agri Shop", type="Agri machinery / supplies shop", km=6, contact="+910000000001")]

# 1. the template always passes the alert checker; broken texts do not
assert agent.check_alert(agent._template(cluster, alts), cluster, alts) == [], agent.check_alert(agent._template(cluster, alts), cluster, alts)
for bad, why in [("Fire near you.", "fire count"), ("12 fires near Sample Village. Call Sample Agri Shop. [name]", "placeholder"),
                 ("12 fires near Sample Village. " + "word " * 80, "too long"), ("", "empty"), ("12 fires near Sample Village. Sample Agri Shop. " + "आग" * 20, "english")]:
    assert agent.check_alert(bad, cluster, alts), f"checker should reject: {why}"

# 2. smoke forecast: wind from the west carries smoke to a city in the east; wind from the east does not
assert pipeline.trajectory(30.0, 75.0, [(270, 25.0)] * 24, city=(30.0, 76.0))[0] is not None
assert pipeline.trajectory(30.0, 75.0, [(90, 25.0)] * 24, city=(30.0, 76.0))[0] is None

# 3. filters: low confidence, weak fires and repeating heat sources are dropped; a fresh strong fire is kept
d = lambda n: (datetime.date.today() - datetime.timedelta(days=n)).isoformat()
fires = [dict(lat=30.0, lon=75.0, date=d(0), conf="n", frp=20), dict(lat=30.5, lon=75.5, date=d(0), conf="l", frp=20), dict(lat=30.6, lon=75.6, date=d(0), conf="n", frp=1)]
fires += [dict(lat=31.0, lon=76.0, date=d(i), conf="h", frp=30) for i in range(3)]
kept, report = pipeline.filter_fires(fires)
assert len(kept) == 1 and report == {"low_confidence": 1, "weak": 1, "static_source": 3}, (len(kept), report)

# 4. impact comparison: alerted areas fall, other areas stay flat
today = datetime.date.today()
days = [(today - datetime.timedelta(days=i)).isoformat() for i in range(8, 0, -1)]
cells = {"30.0,75.0": {x: (10 if i < 4 else 4) for i, x in enumerate(days)}, **{f"3{k}.0,76.0": {x: 10 for x in days} for k in range(1, 5)}}
alerts = [dict(lat=30.0, lon=75.0, created=days[i] + "T08:00:00Z", delivered=1, mode="live") for i in (2, 3)]
eff = impact.effect(cells, alerts, min_cases=1)
assert eff["alerted"]["n"] == 2 and eff["alerted"]["median_change_pct"] < -30 and eff["other"]["median_change_pct"] == 0, eff
assert not impact.effect({}, [])["enough"]

# 5. intervention engine: barriers, matching, consent and preferences, signed links, verification gating
store.init()
cl = dict(cluster, lat=30.1, lon=75.2, id="C1", place="Sample Village, Sample District", eta_hours=9, reach=1.0)
person = lambda i, role, **p: dict(id=i, role=role, name=f"P{i}", lat=30.1, lon=75.2, radius_km=20, active=1, profile={"consent": {"at": "x"}, "min_priority": "high", **p})
farmer = person(1, "farmer", land_acres=10, crop="paddy", needs=["seeder"])
baler_only = person(2, "machine_provider", machines=["baler"], availability="available")
seeder = person(3, "machine_provider", machines=["seeder"], availability="available")
assert any(b["code"] == "no_provider" for b in engine.assess(cl, [farmer, baler_only])["barriers"]), "missing machine type is reported as a barrier"
assert not any(b["code"] == "no_provider" for b in engine.assess(cl, [farmer, seeder])["barriers"])
assert [m["sid"] for m in engine.candidates(cl, [farmer, baler_only, seeder], engine.assess(cl, [farmer, baler_only, seeder]))] == ["3"], "only providers with the needed machine are matched"
assert engine.assess(cl, [])["observed"]["kind"] != engine.assess(cl, [])["estimated"]["kind"]
assert not engine.ok_to_contact(dict(farmer, profile={"min_priority": "high"}), cl), "profiles without consent are not contacted"
assert not engine.ok_to_contact(farmer, dict(cl, priority="medium")) and engine.ok_to_contact(farmer, dict(cl, priority="medium"), manual=True), "alert level applies to automatic messages only"
assert engine.parse_token(engine.make_token("abc", "1")) == ("abc", "1") and engine.parse_token(engine.make_token("abc", "1") + "0") is None
for role, bad in (("farmer", {"crop": "paddy"}), ("machine_provider", {}), ("biomass_buyer", {"materials": ["gold"]})):
    try: engine.clean_profile(role, bad); raise AssertionError("profile should be rejected")
    except ValueError: pass
iv = engine.ensure(cl, [farmer, seeder], {}, [])
try: engine.verify(iv, True, "", {}); raise AssertionError("verification needs a completed intervention")
except ValueError: pass
engine.apply(iv, "3", "accept")
try: engine.apply(iv, "3", "complete", "short"); raise AssertionError("completion needs a proper note")
except ValueError: pass
engine.apply(iv, "3", "complete", "Sowed through residue on ten acres.")
assert engine.metrics([iv])["verified"] == 0 and engine.metrics([iv])["completed_reported"] == 1, "reported completion is not a verified result"
engine.verify(iv, True, "Checked", {}); assert engine.metrics([iv])["verified"] == 1

print("All agent checks passed")
if "--live" in sys.argv:
    kinds = [agent.write_alert(dict(cluster))["source"] for _ in range(3)]
    print("Live model results:", {k: kinds.count(k) for k in set(kinds)}, "(model = text passed the checks)")
