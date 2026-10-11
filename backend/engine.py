"""Intervention engine: registry profiles, assessment (observed vs estimated), barriers, matching, coordination and verification."""
import datetime, hmac, hashlib, os, time, uuid
from collections import Counter
from pipeline import haversine
import impact, store

CROPS = {"paddy": "paddy_straw", "wheat": "wheat_straw", "sugarcane": "sugarcane_trash", "other": "other"}
HARVEST = ("harvested", "within_2_weeks", "not_yet")
NEEDS = ("seeder", "mulcher", "baler", "buyer", "decomposer")
MACHINES = ("seeder", "mulcher", "baler", "rake")
MACHINE_NEEDS = ("seeder", "mulcher", "baler")
AVAIL = ("available", "limited", "seasonal")
PRIO = {"high": 2, "medium": 1, "low": 0}
now = lambda: datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z"
prof = lambda s: s.get("profile") or {}
ckey = lambda c: f"{round(c['lat'], 1):.1f}|{round(c['lon'], 1):.1f}"
_txt = lambda v, n=60: str(v or "").strip()[:n]

def clean_profile(role, p):
    """Validate the role-specific registry fields. Raises ValueError with a message the form can show."""
    p = p or {}
    out = {"min_priority": p.get("min_priority") if p.get("min_priority") in ("high", "medium") else "high",
           "area": {k: _txt((p.get("area") or {}).get(k)) for k in ("state", "district", "village")}}
    if role == "farmer":
        try: acres = float(p.get("land_acres"))
        except (TypeError, ValueError): raise ValueError("Enter your land area in acres.")
        if not 0.1 <= acres <= 5000: raise ValueError("Land area must be between 0.1 and 5000 acres.")
        if p.get("crop") not in CROPS: raise ValueError("Choose your crop.")
        if p.get("harvest_status") not in HARVEST: raise ValueError("Choose your harvest status.")
        out.update(land_acres=acres, crop=p["crop"], harvest_status=p["harvest_status"], needs=[x for x in p.get("needs") or [] if x in NEEDS])
    elif role == "machine_provider":
        m = [x for x in p.get("machines") or [] if x in MACHINES]
        if not m: raise ValueError("Choose at least one machine you offer.")
        out.update(machines=m, availability=p.get("availability") if p.get("availability") in AVAIL else "available", rate_note=_txt(p.get("rate_note"), 80))
    elif role == "biomass_buyer":
        m = [x for x in p.get("materials") or [] if x in CROPS.values()]
        if not m: raise ValueError("Choose at least one residue type you buy.")
        try: cap = max(0.0, float(p.get("capacity_tpd") or 0))
        except (TypeError, ValueError): cap = 0.0
        out.update(materials=m, capacity_tpd=cap, rate_note=_txt(p.get("rate_note"), 80))
    elif role == "officer":
        out.update(designation=_txt(p.get("designation")))
    return out

def in_range(s, c): return haversine(c["lat"], c["lon"], s["lat"], s["lon"]) <= s["radius_km"]

def officer_covers(s, c):
    """Officers get interventions in their assigned district or state, or within their own radius. No assigned area means radius only, never everything."""
    a = prof(s).get("area") or {}; place = (c.get("place") or "").lower()
    names = [x.lower() for x in (a.get("district"), a.get("state")) if x]
    return any(n in place for n in names) or in_range(s, c)

def public_registry(r):
    """Small groups are not shown in detail: with fewer than 3 registered farmers in range, acres and needs would point at individuals."""
    return r if r["farmers"] >= 3 else {**r, "acres": None, "needs": {}}

def ok_to_contact(s, c, manual=False):
    """Active, consented and (for automatic messages) within the person's chosen alert level. Older rows without a profile were verified by one-time code."""
    p = prof(s)
    if not s.get("active") or (p and not p.get("consent")): return False
    return manual or PRIO[c["priority"]] >= PRIO[p.get("min_priority", "high")]

# ---------- assessment ----------
def _hist(cells, c):
    if not cells: return 0
    days = {d for n in impact._nbrs(impact._key(c["lat"], c["lon"])) for d, k in cells.get(n, {}).items() if k}
    return len([d for d in days if d >= (datetime.date.today() - datetime.timedelta(days=7)).isoformat()])

def assess(c, subs, cells=None, listings=None):
    rng = [s for s in subs if in_range(s, c)]
    farmers, provs, buyers = ([s for s in rng if s["role"] == r] for r in ("farmer", "machine_provider", "biomass_buyer"))
    needs = Counter(n for f in farmers for n in (prof(f).get("needs") or ["seeder", "baler"]))
    machines = Counter(m for p in provs for m in prof(p).get("machines", []))
    acres, hist = round(sum(prof(f).get("land_acres", 0) for f in farmers), 1), _hist(cells, c)
    want = [n for n in MACHINE_NEEDS if needs.get(n)]
    b = []
    if farmers and want and not any(machines.get(n) for n in want):
        b.append({"code": "no_provider", "basis": "registry", "text": "Farmers nearby need machinery that no registered provider in range offers."})
    elif provs and want and all(prof(p).get("availability") != "available" for p in provs):
        b.append({"code": "limited_supply", "basis": "registry", "text": "Registered providers in range are only partly available."})
    if farmers and (needs.get("buyer") or needs.get("baler")) and not buyers:
        b.append({"code": "no_buyer", "basis": "registry", "text": "Farmers want to sell or bale straw but no registered buyer covers this area."})
    if not farmers:
        b.append({"code": "no_farmers", "basis": "registry", "text": "No registered farmers in range yet, so the cause cannot be confirmed. Local officers should reach out."})
    if hist >= 3: b.append({"code": "recurring", "basis": "history", "text": f"Burning was detected here on {hist} of the last 7 days."})
    if listings is not None and not any(a["km"] <= 25 for a in listings):
        b.append({"code": "no_listing", "basis": "listings", "text": "No listed machinery shop or biomass facility within 25 km."})
    return {"observed": {"kind": "observed by satellite", "fires": c["fires"], "place": c.get("place"), "first_detected": c.get("first_detected"),
                         "last_detected": c.get("last_detected"), "days_with_fire_7d": hist},
            "estimated": {"kind": "estimated future risk (24-hour wind forecast)", "eta_hours": c.get("eta_hours"), "city_name": c.get("city_name"), "reach": c.get("reach"), "closest_km": c.get("closest_km")},
            "registry": {"farmers": len(farmers), "acres": acres, "needs": dict(needs), "providers": len(provs), "machines": dict(machines),
                         "buyers": len(buyers), "buyer_capacity_tpd": round(sum(prof(x).get("capacity_tpd", 0) for x in buyers), 1)},
            "barriers": b}

def plan_of(a):
    r, steps = a["registry"], []
    if r["providers"] and r["farmers"]: steps.append(f"Ask {min(r['providers'], 3)} registered machine provider(s) to serve {r['farmers']} farmer(s)" + (f" ({r['acres']} acres)." if r["acres"] is not None else "."))
    if r["buyers"] and (r["needs"].get("buyer") or r["needs"].get("baler")): steps.append(f"Ask {min(r['buyers'], 2)} registered biomass buyer(s) about collecting straw.")
    codes = {x["code"] for x in a["barriers"]}
    if codes & {"no_provider", "no_buyer", "no_listing"}: steps.append("Officer follow-up: recruit machinery or buyers for this area.")
    if "no_farmers" in codes: steps.append("Officer follow-up: reach farmers here and invite them to join NabhoNetra.")
    return steps or ["Monitor this cluster and re-check after the next refresh."]

def candidates(c, subs, a):
    need = {n for n in MACHINE_NEEDS if a["registry"]["needs"].get(n)} or set(MACHINE_NEEDS)
    mats = {CROPS[prof(f)["crop"]] for f in subs if f["role"] == "farmer" and in_range(f, c) and prof(f).get("crop")}
    pr, bu = [], []
    for s in subs:
        if s["role"] not in ("machine_provider", "biomass_buyer") or not in_range(s, c) or not ok_to_contact(s, c): continue
        p, km = prof(s), round(haversine(c["lat"], c["lon"], s["lat"], s["lon"]))
        base = {"sid": str(s["id"]), "role": s["role"], "name": s["name"], "km": km, "status": "suggested"}
        if s["role"] == "machine_provider" and need & set(p.get("machines", [])):
            pr.append({**base, "offers": sorted(need & set(p["machines"])), "availability": p.get("availability")})
        elif s["role"] == "biomass_buyer" and p.get("materials") and (not mats or mats & set(p["materials"])):
            bu.append({**base, "materials": p["materials"]})
    pr.sort(key=lambda m: (m["availability"] != "available", m["km"])); bu.sort(key=lambda m: m["km"])
    return pr[:3] + bu[:2]

# ---------- intervention records ----------
def ensure(c, subs, cells=None, listings=None):
    """Create the intervention for a cluster, or refresh its analysis and add newly registered candidates."""
    key, recent = ckey(c), (datetime.datetime.utcnow() - datetime.timedelta(days=7)).isoformat()
    a = assess(c, subs, cells, listings)
    iv = next((i for i in store.list_interventions(500) if i["key"] == key and (i["status"] in ("open", "coordinating", "accepted", "completed") or i["updated"] >= recent)), None)
    cl = {k: c.get(k) for k in ("id", "lat", "lon", "place", "priority", "fires", "eta_hours", "last_detected", "city_name")}
    if iv:
        iv.update(cluster=cl, analysis=a, plan=plan_of(a), updated=now())
    else:
        iv = {"iid": uuid.uuid4().hex[:12], "key": key, "status": "open", "created": now(), "updated": now(), "cluster": cl, "analysis": a, "plan": plan_of(a),
              "matches": [], "requests": [], "events": [{"at": now(), "text": "Intervention opened from satellite detections."}], "evidence": [], "satellite": None, "verification": None}
    have = {m["sid"] for m in iv["matches"]}
    for m in candidates(c, subs, a):
        if m["sid"] not in have: iv["matches"].append(m)
    by = {str(x["id"]): x for x in subs}
    for rq in iv.setdefault("requests", []):
        f = by.get(rq["fsid"])
        if f and rstatus(iv, rq) in ("open", "proposed"): propose(iv, rq, f, subs)
    store.put_intervention(iv)
    return iv

secret = lambda: os.getenv("TOKEN_SECRET") or os.getenv("ADMIN_TOKEN") or ""
def make_token(iid, sid): return f"{iid}.{sid}." + hmac.new(secret().encode(), f"{iid}.{sid}".encode(), hashlib.sha256).hexdigest()[:24]
def parse_token(t):
    p = (t or "").split(".")
    if len(p) != 3 or not secret() or not hmac.compare_digest(make_token(p[0], p[1]), t): return None
    return p[0], p[1]

def _sig(msg): return hmac.new(secret().encode(), msg.encode(), hashlib.sha256).hexdigest()[:32]
def make_session(sid, days=30):
    """Signed sign-in token for a verified registrant. Different shape from response links, so the two can never be swapped."""
    exp = int(time.time()) + int(days * 86400)
    return f"s.{sid}.{exp}.{_sig(f's.{sid}.{exp}')}"
def parse_session(t):
    p = (t or "").split(".")
    if len(p) != 4 or p[0] != "s" or not secret() or not p[2].isdigit() or int(p[2]) < time.time(): return None
    return p[1] if hmac.compare_digest(_sig(f"s.{p[1]}.{p[2]}"), p[3]) else None

def _event(iv, text): iv["events"].append({"at": now(), "text": text}); iv["updated"] = now()

def coordinate(iv, subs, send, base_url, links=None):
    """Ask matched providers and buyers (with a response link), tell relevant farmers and officers. Only consenting, active people are contacted."""
    c, a, by = iv["cluster"], iv["analysis"], {str(s["id"]): s for s in subs}
    where, r, asked = c.get("place") or "your area", public_registry(a["registry"]), 0
    for m in iv["matches"]:
        s = by.get(m["sid"])
        if m["status"] != "suggested" or not s or not ok_to_contact(s, c, manual=True): continue
        what = ", ".join(m.get("offers") or m.get("materials") or [])
        text = (f"NabhoNetra request: {c['fires']} crop fires near {where}. {r['farmers']} registered farmers" + (f" ({r['acres']} acres)" if r["acres"] is not None else "") + f" may need help ({what}). "
                f"Can you help? Respond here: {base_url}/#/respond/{make_token(iv['iid'], m['sid'])}")
        if send(s, text)[0] != "failed": m["status"], m["asked_at"] = "asked", now(); asked += 1; links is not None and links.append({"name": m["name"], "url": f"{base_url}/#/respond/{make_token(iv['iid'], m['sid'])}"})
    if asked:
        iv["status"] = "coordinating"; _event(iv, f"Requests sent to {asked} matched provider(s) or buyer(s).")
        shared = [m for m in iv["matches"] if m["status"] == "asked" and prof(by.get(m["sid"], {})).get("share")]
        for f in (s for s in subs if s["role"] == "farmer" and in_range(s, c) and ok_to_contact(s, c, manual=True)):
            tip = "".join(f" {m['name']} ({by[m['sid']]['contact']})." for m in shared[:2])
            send(f, f"NabhoNetra: registered service(s) near {where} have been asked to help farmers with residue.{tip} Please do not burn.")
    for o in (s for s in subs if s["role"] == "officer" and officer_covers(s, c) and ok_to_contact(s, c, manual=True)):
        send(o, f"[{c['priority'].upper()}] Intervention {iv['iid']} near {where}: {c['fires']} fires, {r['farmers']} farmers, {asked} request(s) sent. Open {base_url}/#/interventions")
    if not asked: _event(iv, "No consenting provider or buyer could be asked yet.")
    store.put_intervention(iv)
    return asked

def _derive(iv):
    """Intervention status from its matches: unverified completion claims come first, then work in progress, then requests out, then outcomes."""
    st = Counter(m["status"] for m in iv["matches"])
    iv["status"] = ("completed" if st["completed"] else "accepted" if st["accepted"] else "coordinating" if st["asked"] else
                    "verified" if st["verified"] else "rejected" if st["rejected"] else "open")

def apply(iv, sid, action, note=""):
    """A matched provider or buyer answers a request or reports their work done. Reporting is a claim: only an officer's verify() makes it a result."""
    m = next((x for x in iv["matches"] if x["sid"] == sid), None)
    if not m: raise ValueError("Request not found.")
    note = _txt(note, 500)
    if action == "accept" and m["status"] in ("asked", "suggested"):
        m["status"] = "accepted"; _event(iv, "A matched party accepted the request.")
    elif action == "decline" and m["status"] in ("asked", "suggested"):
        m["status"] = "declined"; _event(iv, "A matched party declined.")
    elif action == "complete" and m["status"] == "accepted":
        if len(note) < 10: raise ValueError("Add a short note on what was done (at least 10 characters).")
        m["status"], m["completed_at"], iv["completed_at"] = "completed", now(), now()
        iv["evidence"].append({"type": "note", "by": sid, "text": note, "at": now()}); _event(iv, "Completion reported with a note.")
    else: raise ValueError("That action is not available right now.")
    _derive(iv); store.put_intervention(iv)

def verify(iv, approve, note, cells, sid=None, by=""):
    """Officer decision on completion claims (one provider's, or every pending one). A claim needs its own evidence note.
    Adds a satellite re-check as supporting evidence."""
    pend = [m for m in iv["matches"] if m["status"] == "completed" and (sid is None or m["sid"] == str(sid))
            and any(e["type"] == "note" and e["by"] == m["sid"] for e in iv["evidence"])]
    if not pend: raise ValueError("Only completed work with evidence can be verified.")
    nb = impact._nbrs(impact._key(iv["cluster"]["lat"], iv["cluster"]["lon"]))
    for m in pend:
        done = (m.get("completed_at") or iv.get("completed_at") or now())[:10]
        dates = sorted({d for v in (cells or {}).values() for d in v if d > done})
        m["satellite"] = iv["satellite"] = {"days_checked": len(dates), "fires_after": sum(cells.get(n, {}).get(d, 0) for n in nb for d in dates), "checked_at": now()}
        m["verification"] = iv["verification"] = {"approved": bool(approve), "note": _txt(note, 300), "at": now(), "by": by}
        m["status"] = "verified" if approve else "rejected"
        _event(iv, "Officer verified the outcome." if approve else "Officer did not accept the evidence.")
    _derive(iv); store.put_intervention(iv)

def metrics(ivs):
    c = Counter(i["status"] for i in ivs)
    return {"opened": len(ivs), "coordinating": c["coordinating"], "accepted": c["accepted"], "completed_reported": c["completed"],
            "verified": c["verified"], "rejected": c["rejected"], "note": "Only verified outcomes count as results. Reported completions are shown separately."}

def public_view(iv):
    ms = Counter(m["status"] for m in iv["matches"])
    an, r = iv["analysis"], iv["analysis"]["registry"]; pr = public_registry(r)
    return {"id": iv["iid"], "status": iv["status"], "created": iv["created"], "updated": iv["updated"], "cluster": iv["cluster"],
            "analysis": an if pr is r else {**an, "registry": pr}, "plan": iv["plan"] if pr is r else plan_of({**an, "registry": pr}), "matches": dict(ms), "events": iv["events"], "evidence_count": len(iv["evidence"]),
            "satellite": iv["satellite"], "verified": iv["status"] == "verified", "demo": bool(iv.get("demo"))}

def registry_view(s, ivs, subs):
    """What a newly registered person sees: solutions, requests, opportunities or priority interventions that fit their role."""
    live = [i for i in ivs if i["status"] in ("open", "coordinating", "accepted")]
    near = [i for i in live if in_range(s, i["cluster"])]
    row = lambda i: {"id": i["iid"], "place": i["cluster"].get("place") or "this area", "priority": i["cluster"]["priority"], "status": i["status"],
                     "detail": f"{i['cluster']['fires']} fires, {i['analysis']['registry']['farmers']} registered farmers" + (f", {public_registry(i['analysis']['registry'])['acres']} acres" if public_registry(i["analysis"]["registry"])["acres"] is not None else "")}
    if s["role"] == "farmer":
        import agent
        return {"title": "Residue-management options near you", "kind": "solutions",
                "items": [{"id": a["name"], "place": a["type"], "detail": f"{a['km']} km, contact {a['contact']}" + (" (registered)" if a.get("registered") else "")} for a in agent.nearby_alternatives(s["lat"], s["lon"], 5)],
                "empty": "No listed options near you yet. NabhoNetra will contact you when a provider or buyer joins."}
    if s["role"] == "machine_provider":
        want = set(prof(s).get("machines", []))
        return {"title": "Service requests you could take", "kind": "requests", "items": [row(i) for i in near if want & {n for n in MACHINE_NEEDS if i["analysis"]["registry"]["needs"].get(n)}][:8],
                "empty": "No open requests in your range right now. You will get a message when one matches."}
    if s["role"] == "biomass_buyer":
        return {"title": "Residue opportunities in your range", "kind": "opportunities", "items": [row(i) for i in near if i["analysis"]["registry"]["farmers"]][:8],
                "empty": "No residue opportunities in your range right now."}
    mine = [i for i in live if officer_covers(s, i["cluster"])]
    mine.sort(key=lambda i: (-PRIO[i["cluster"]["priority"]], -i["cluster"]["fires"]))
    return {"title": "Priority interventions in your area", "kind": "interventions", "items": [row(i) for i in mine[:8]], "empty": "No open interventions in your area."}


# ---------- farmer requests: ask for help, accept a proposed solution, track it ----------
RQ_DONE = ("withdrawn", "verified", "rejected")
_match = lambda iv, sid: next((m for m in iv["matches"] if m["sid"] == str(sid)), None)

def rstatus(iv, rq):
    """Where a farmer's request stands, read from the provider's match. Nothing here is stored twice."""
    if rq.get("withdrawn"): return "withdrawn"
    ap = next((p for p in rq["proposals"] if p["status"] == "accepted"), None)
    if not ap: return "proposed" if any(p["status"] == "proposed" for p in rq["proposals"]) else "open"
    m = _match(iv, ap["sid"])
    return {"accepted": "in_progress", "declined": "provider_declined", "completed": "completed", "verified": "verified", "rejected": "rejected"}.get(m["status"] if m else "", "waiting_provider")

def propose(iv, rq, f, subs):
    """Add registered providers and buyers who fit this request and whose own service range covers this farmer. Contact details stay hidden."""
    needs = rq["needs"]; want_m = [n for n in needs if n in MACHINE_NEEDS]; want_b = "buyer" in needs or "baler" in needs; anything = not needs
    mat = CROPS.get(prof(f).get("crop")); have = {p["sid"] for p in rq["proposals"]}; pr, bu = [], []
    for s in subs:
        sid = str(s["id"])
        if sid in have or s["role"] not in ("machine_provider", "biomass_buyer") or not ok_to_contact(s, iv["cluster"], manual=True): continue
        km = round(haversine(f["lat"], f["lon"], s["lat"], s["lon"]))
        if km > s["radius_km"]: continue
        sp = prof(s); base = {"sid": sid, "role": s["role"], "name": s["name"], "km": km, "status": "proposed", "at": now()}
        offers = sorted(set(sp.get("machines", [])) & set(want_m or MACHINE_NEEDS))
        if s["role"] == "machine_provider" and (want_m or anything) and offers: pr.append({**base, "offers": offers, "availability": sp.get("availability")})
        elif s["role"] == "biomass_buyer" and (want_b or anything) and sp.get("materials") and (not mat or mat in sp["materials"]): bu.append({**base, "materials": sp["materials"]})
    pr.sort(key=lambda m: (m["availability"] != "available", m["km"])); bu.sort(key=lambda m: m["km"])
    room = max(0, 5 - sum(1 for p in rq["proposals"] if p["status"] == "proposed"))
    rq["proposals"] += (pr[:3] + bu[:2])[:room]
    return rq

def create_request(iv, f, needs, note, subs):
    reqs = iv.setdefault("requests", [])
    if any(r["fsid"] == str(f["id"]) and rstatus(iv, r) not in RQ_DONE for r in reqs): raise ValueError("You already have an open request for this cluster.")
    needs = [n for n in dict.fromkeys(needs or []) if n in NEEDS] or [n for n in prof(f).get("needs", []) if n in NEEDS]
    rq = {"rid": uuid.uuid4().hex[:10], "fsid": str(f["id"]), "needs": needs, "note": _txt(note, 200), "created": now(), "events": [{"at": now(), "text": "You asked for help."}], "proposals": []}
    reqs.append(rq); propose(iv, rq, f, subs)
    rq["events"].append({"at": now(), "text": f"{len(rq['proposals'])} option(s) proposed. Nothing about you is shared until you choose one." if rq["proposals"]
                         else "No registered provider or buyer covers your location yet. Officers in your area can see your request."})
    _event(iv, "A registered farmer asked for help."); store.put_intervention(iv); return rq

def accept_proposal(iv, rq, sid, share_location, provider):
    """The farmer chooses one proposed solution. That choice is the consent: it lets this one provider see their details, and nobody else."""
    if rstatus(iv, rq) not in ("open", "proposed", "provider_declined"): raise ValueError("You already chose an option for this request.")
    p = next((x for x in rq["proposals"] if x["sid"] == str(sid) and x["status"] == "proposed"), None)
    m = _match(iv, sid)
    if not p or (m and m["status"] in ("declined", "rejected")): raise ValueError("That option is not available.")
    for x in rq["proposals"]:
        if x["status"] == "accepted": x["status"] = "declined"
    p.update(status="accepted", share_location=bool(share_location), consent_at=now())
    if not m:
        m = {"sid": p["sid"], "role": p["role"], "name": p["name"], "km": round(haversine(iv["cluster"]["lat"], iv["cluster"]["lon"], provider["lat"], provider["lon"])),
             "status": "suggested", "by_request": True, **{k: p[k] for k in ("offers", "materials", "availability") if k in p}}
        iv["matches"].append(m)
    if m["status"] == "suggested": m["status"], m["asked_at"] = "asked", now()
    rids = m.setdefault("rids", [])
    if rq["rid"] not in rids: rids.append(rq["rid"])
    rq["events"].append({"at": now(), "text": f"You chose {p['name']}. They can now see your details" + (" and exact location." if share_location else " (not your exact location).")})
    _event(iv, "A farmer accepted a proposed solution."); _derive(iv); store.put_intervention(iv); return m

def decline_proposal(iv, rq, sid):
    p = next((x for x in rq["proposals"] if x["sid"] == str(sid) and x["status"] == "proposed"), None)
    if not p: raise ValueError("That option is not available.")
    p["status"] = "declined"; rq["events"].append({"at": now(), "text": f"You turned down {p['name']}."}); store.put_intervention(iv)

def withdraw_request(iv, rq):
    """Withdrawing takes back the consent: the provider stops seeing this farmer's details straight away."""
    if rstatus(iv, rq) in RQ_DONE: raise ValueError("This request is already closed.")
    ap = next((p for p in rq["proposals"] if p["status"] == "accepted"), None); m = _match(iv, ap["sid"]) if ap else None
    rq["withdrawn"] = True; rq["events"].append({"at": now(), "text": "You withdrew this request."})
    if m:
        m["rids"] = [r for r in m.get("rids", []) if r != rq["rid"]]
        if m.get("by_request") and not m["rids"] and m["status"] == "asked": iv["matches"].remove(m)
    _event(iv, "A farmer withdrew a request."); _derive(iv); store.put_intervention(iv)

def request_view(iv, rq, by):
    """What the farmer sees. A provider's contact appears only if they chose to be listed, or once they have taken the job."""
    ps = []
    for p in rq["proposals"]:
        m, sub = _match(iv, p["sid"]), by.get(p["sid"], {}); st = p["status"]
        if st == "accepted" and m and m["status"] == "declined": st = "declined_by_provider"
        elif st == "proposed" and m and m["status"] in ("declined", "rejected"): st = "unavailable"
        engaged = p["status"] == "accepted" and m and m["status"] in ("accepted", "completed", "verified")
        ps.append({**{k: p.get(k) for k in ("sid", "role", "name", "km", "offers", "materials", "availability", "share_location")}, "status": st,
                   "contact": sub.get("contact") if (engaged or sub.get("share")) else None})
    ap = next((p for p in rq["proposals"] if p["status"] == "accepted"), None); m = _match(iv, ap["sid"]) if ap else None
    outcome = None
    if m and m["status"] in ("completed", "verified", "rejected"):
        v = m.get("verification") or {}
        outcome = {"status": m["status"], "note": next((e["text"] for e in reversed(iv["evidence"]) if e["type"] == "note" and e["by"] == m["sid"]), ""),
                   "decision_note": v.get("note"), "decided_at": v.get("at")}
    return {"rid": rq["rid"], "iid": iv["iid"], "status": rstatus(iv, rq), "needs": rq["needs"], "note": rq["note"], "created": rq["created"], "events": rq["events"], "proposals": ps, "outcome": outcome}

def my_requests(s, ivs, by):
    """A farmer's own requests across clusters, newest first."""
    out = [{**request_view(i, r, by), "place": i["cluster"].get("place"), "priority": i["cluster"]["priority"], "lat": i["cluster"]["lat"], "lon": i["cluster"]["lon"]}
           for i in ivs for r in i.get("requests", []) if r["fsid"] == str(s["id"])]
    return sorted(reversed(out), key=lambda r: r["created"], reverse=True)   # same-second requests keep newest first

def _near5(km): return max(5, 5 * round(km / 5))

def jobs_for(iv, m, by, provider):
    """Farmers who chose this provider. Before the provider accepts: needs, crop, acres and a rough area only. After: name and contact,
    and the exact location only if that farmer agreed to share it. A withdrawn request or a deleted registration removes the farmer here."""
    revealed, out = m["status"] in ("accepted", "completed", "verified"), []
    for rq in iv.get("requests", []):
        p = next((x for x in rq["proposals"] if x["sid"] == m["sid"] and x["status"] == "accepted"), None)
        f = by.get(rq["fsid"])
        if not p or rq.get("withdrawn") or rq["rid"] not in m.get("rids", []) or not f or not f.get("active"): continue
        fp = prof(f); area = fp.get("area") or {}
        job = {"rid": rq["rid"], "needs": rq["needs"], "note": rq["note"], "crop": fp.get("crop"), "land_acres": fp.get("land_acres"),
               "area": {"district": area.get("district"), "state": area.get("state")}, "approx_km": _near5(haversine(provider["lat"], provider["lon"], f["lat"], f["lon"]))}
        if revealed:
            job.update(name=f["name"], contact=f["contact"], area=area)
            if p.get("share_location"): job.update(lat=f["lat"], lon=f["lon"])
        out.append(job)
    return out

def claims_view(iv):
    """Completion claims for an officer to review: who says what was done, the evidence they attached, and any decision so far."""
    out = []
    for m in iv["matches"]:
        if m["status"] not in ("completed", "verified", "rejected"): continue
        ev = [e for e in iv["evidence"] if e["by"] == m["sid"]]
        out.append({"sid": m["sid"], "name": m["name"], "role": m["role"], "status": m["status"], "completed_at": m.get("completed_at"),
                    "note": next((e["text"] for e in reversed(ev) if e["type"] == "note"), ""), "photos": [e["name"] for e in ev if e["type"] == "photo"],
                    "verification": m.get("verification"), "satellite": m.get("satellite")})
    return out

def staff_requests(iv, by):
    """Farmer requests for an officer in this area, with the farmer's name, contact and area so they can help when no provider covers them."""
    out = []
    for rq in iv.get("requests", []):
        f = by.get(rq["fsid"])
        if not f or not f.get("active"): continue
        fp = prof(f)
        out.append({"rid": rq["rid"], "status": rstatus(iv, rq), "needs": rq["needs"], "note": rq["note"], "created": rq["created"],
                    "farmer": {"name": f["name"], "contact": f["contact"], "land_acres": fp.get("land_acres"), "crop": fp.get("crop"), "area": fp.get("area") or {}},
                    "proposals": [{"name": p["name"], "role": p["role"], "km": p["km"], "status": p["status"]} for p in rq["proposals"]]})
    return out

FARMER_LABEL = {"open": "Request open: looking for options", "proposed": "Choose an option for your request", "waiting_provider": "Waiting for the provider to reply",
                "provider_declined": "Your provider declined: choose another", "in_progress": "Work in progress", "completed": "Work reported, waiting for an officer to check",
                "verified": "Outcome verified", "rejected": "An officer did not accept the evidence", "withdrawn": "Request withdrawn"}
MY_STATUS = {"suggested": "You are a suggested match", "asked": "A request is waiting for you", "accepted": "You accepted this", "completed": "You reported it done",
             "declined": "You declined", "verified": "Your work was verified", "rejected": "An officer did not accept your evidence"}

def mine(s, ivs):
    """Interventions that matter to one signed-in person: why, and whether they have something to do. Scoped by role and location."""
    out = []
    for i in ivs:
        c, role = i["cluster"], s["role"]; m = _match(i, s["id"])
        if role == "officer":
            if not officer_covers(s, c): continue
            waiting = any(rstatus(i, r) == "open" and not r["proposals"] for r in i.get("requests", []))
            why, act = (("Needs your verification", True) if i["status"] == "completed" else ("A farmer request has no provider yet", True) if waiting
                        else ("No requests sent yet", True) if i["status"] == "open" else ("In your area", False))
        elif role in ("machine_provider", "biomass_buyer"):
            if not m and not in_range(s, c): continue
            why, act = (MY_STATUS.get(m["status"], "Matched to you"), m["status"] in ("asked", "suggested")) if m else ("In your service range", False)
        else:
            rs = [rstatus(i, r) for r in i.get("requests", []) if r["fsid"] == str(s["id"]) and rstatus(i, r) != "withdrawn"]
            if rs: why, act = FARMER_LABEL[rs[-1]], rs[-1] in ("proposed", "provider_declined")
            elif in_range(s, c): why, act = "Near your land. You can ask for help", False
            else: continue
        out.append({"id": i["iid"], "why": why, "act": act, "my_status": m["status"] if m else None})
    return out
