"""End-to-end check of the server API using sample data (no network, no messages sent). Run: python smoke_test.py"""
import json, os, re, tempfile, time
for k, v in dict(ADMIN_TOKEN="test_token_1234567890", PIPELINE_MOCK="1", DELIVERY="log", USE_AGENT="0", PUBLIC_URL="https://example.test",
                 DB_PATH=os.path.join(tempfile.mkdtemp(), "t.db"), CORS_ORIGINS="https://main.d123abc.amplifyapp.com, http://localhost:5173, *, http://evil.example").items():
    os.environ.setdefault(k, v)
from fastapi.testclient import TestClient
import server, agent, store

ADMIN = {"x-admin-token": os.environ["ADMIN_TOKEN"]}
PROFILES = {"farmer": {"land_acres": 10, "crop": "paddy", "harvest_status": "harvested", "needs": ["seeder"]},
            "machine_provider": {"machines": ["seeder", "baler"], "availability": "available"},
            "biomass_buyer": {"materials": ["paddy_straw"], "capacity_tpd": 15}, "officer": {"designation": "District officer"}}
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64

with TestClient(server.app) as c:
    for _ in range(60):
        r = c.get("/api/data")
        if r.status_code == 200: break
        time.sleep(2)
    d = r.json(); k = d["clusters"][0]
    assert k["last_detected"] and k["first_detected"], "clusters need detection times"
    base = dict(name="Test", role="farmer", channel="sms", contact="+911234567890", lat=k["lat"], lon=k["lon"], radius_km=20, consent=True, profile=PROFILES["farmer"])
    mk = lambda **kw: {**base, **kw}
    send = lambda: c.post("/api/alerts/send", json={"lat": k["lat"], "lon": k["lon"]}, headers=ADMIN).json()["recipients"]
    def reg(role, contact, headers=None, **kw):
        r = c.post("/api/subscribers", json=mk(role=role, contact=contact, profile=PROFILES[role], **kw), headers=headers or {}); assert r.status_code == 200, r.text
        if not r.json()["verify"]: return r.json()
        v = c.post("/api/subscribers/verify", json={"channel": kw.get("channel", "sms"), "contact": contact, "code": r.json()["dev_code"]}); assert v.status_code == 200, v.text
        return v.json()

    # --- registration: channels, consent, role profiles, verification
    assert {"sms", "email", "whatsapp"} <= set(c.get("/api/config").json()["channels"])
    assert c.post("/api/subscribers", json=mk(consent=False)).status_code == 400, "consent is required"
    assert c.post("/api/subscribers", json=mk(profile={"crop": "paddy"})).status_code == 400, "farmer profile needs land area and harvest status"
    assert c.post("/api/subscribers", json=mk(role="machine_provider", profile={})).status_code == 400, "provider must list machines"
    r = c.post("/api/subscribers", json=mk()).json(); assert r["verify"] and r["dev_code"]
    assert send() == 0, "unverified contacts must not get alerts"
    assert c.post("/api/subscribers/verify", json={"channel": "sms", "contact": base["contact"], "code": "000000"}).status_code == 400
    v = c.post("/api/subscribers/verify", json={"channel": "sms", "contact": base["contact"], "code": r["dev_code"]}); assert v.status_code == 200
    assert v.json()["registry"]["kind"] == "solutions", "farmers see nearby solutions after joining"
    assert send() == 1, "verified, consented contact should get the alert"
    assert c.post("/api/subscribers", json=mk(lat=1.0)).json()["verify"] is False, "active contacts cannot be overwritten"
    assert c.post("/api/subscribers", json=mk(role="officer", contact="+911111111111", profile=PROFILES["officer"])).status_code == 401, "officers need the admin token"
    assert c.post("/api/alerts/send", json={"lat": 0, "lon": 0}).status_code == 401, "sending needs the admin token"
    assert base["contact"] not in c.get("/api/data").text and base["contact"] not in c.get("/api/interventions").text, "public data must not contain contacts"
    o = c.post("/api/subscribers/optout", json={"channel": "sms", "contact": base["contact"]}).json()
    assert c.post("/api/subscribers/optout/confirm", json={"channel": "sms", "contact": base["contact"], "code": o["dev_code"]}).status_code == 200
    assert send() == 0, "deleted contacts must not get alerts"
    assert c.get("/api/geocode").status_code == 400 and c.get("/api/geocode?village=x").status_code == 200

    # --- registry, matching, coordination, response, verification
    server.hits.clear()
    reg("farmer", "+912000000010", share=True)
    reg("farmer", "+912000000013", channel="whatsapp")
    assert reg("machine_provider", "+912000000011", name="Test Provider", share=True)["registry"]["kind"] == "requests"
    assert reg("biomass_buyer", "+912000000012", name="Test Buyer")["registry"]["kind"] == "opportunities"
    assert reg("officer", "+912000000014", headers=ADMIN)["registry"]["kind"] == "interventions"
    iv = c.post("/api/interventions/plan", json={"lat": k["lat"], "lon": k["lon"]}, headers=ADMIN).json()
    a = iv["analysis"]; assert a["registry"]["farmers"] >= 2 and a["registry"]["providers"] >= 1 and a["registry"]["buyers"] >= 1
    assert a["observed"]["kind"] != a["estimated"]["kind"], "observed fires and estimated risk are kept apart"
    assert iv["matches"].get("suggested", 0) >= 2 and iv["plan"]
    got, real = [], server.deliver
    server.deliver = lambda s, subject, body: (got.append((s["contact"], body)), ("sent", ""))[1]
    pub = c.get("/api/interventions").json()
    assert all(i["analysis"]["registry"]["acres"] is None and not i["analysis"]["registry"]["needs"] and "acres" not in " ".join(i["plan"]) for i in pub if i["analysis"]["registry"]["farmers"] < 3), "fewer than 3 farmers: no acres or needs in public data"
    out = c.post(f"/api/interventions/{iv['id']}/coordinate", headers=ADMIN).json()
    server.deliver = real
    msgs = dict(got); assert out["asked"] >= 2 and out["status"] == "coordinating", out

    # --- sign-in and role-based access: each role sees and does only what fits it
    server.hits.clear()
    def login(contact, channel="sms"):
        cap, prev = [], server.deliver
        server.deliver = lambda sub, subject, text: (cap.append(text), ("sent", ""))[1]
        try: st = c.post("/api/session/start", json={"channel": channel, "contact": contact}).json()
        finally: server.deliver = prev
        st["dev_code"] = st.get("dev_code") or re.search(r"\b(\d{6})\b", cap[-1]).group(1)
        assert c.post("/api/session/verify", json={"channel": channel, "contact": contact, "code": "000000"}).status_code == 400, "wrong code"
        r = c.post("/api/session/verify", json={"channel": channel, "contact": contact, "code": st["dev_code"]}); assert r.status_code == 200, r.text
        return {"x-session": r.json()["session"]}, r.json()["me"]
    assert "dev_code" not in c.post("/api/session/start", json={"channel": "sms", "contact": "+919999999999"}).json(), "unknown contacts get no code"
    BUY, bme = login("+912000000012"); assert bme["role"] == "biomass_buyer" and bme["role_label"] == "Biomass buyer"
    FAR, _fme = login("+912000000010"); OFF, ome = login("+912000000014"); assert ome["role"] == "officer"
    assert c.get("/api/me").status_code == 401 and c.get("/api/me", headers={"x-session": BUY["x-session"] + "x"}).status_code == 401, "missing or tampered session"
    assert c.get("/api/me", headers=BUY).json()["name"] == "Test Buyer"
    rid = f"/api/interventions/{iv['id']}"
    mine_b = {x["id"]: x for x in c.get("/api/me/interventions", headers=BUY).json()}
    assert mine_b[iv["id"]]["act"] and mine_b[iv["id"]]["my_status"] == "asked", "the buyer sees the request waiting for them"
    assert all(x["act"] is False for x in c.get("/api/me/interventions", headers=FAR).json()), "farmers have nothing to accept"
    assert c.get(rid + "/role", headers=BUY).json()["mine"]["status"] == "asked"
    fv = c.get(rid + "/role", headers=FAR).json(); assert fv["role"] == "farmer" and fv["in_range"] and "matches" not in fv, "farmers never get the contact list"
    ov = c.get(rid + "/role", headers=OFF).json(); assert ov["covered"] and ov["matches"] and any(x["contact"] for x in ov["matches"])
    assert c.get(rid + "/role").status_code == 401, "role view needs sign-in"
    assert c.get(rid, headers=BUY).status_code == 401 and c.post(rid + "/coordinate", headers=FAR).status_code == 401, "only officers use staff actions"
    assert c.post(rid + "/act", json={"action": "accept"}, headers=FAR).status_code == 403, "farmers cannot answer provider requests"
    assert c.post(rid + "/act", json={"action": "complete", "note": "x" * 12}, headers=BUY).status_code == 400, "accept before completing"
    assert c.post(rid + "/act", json={"action": "accept"}, headers=BUY).status_code == 200
    assert c.post(rid + "/evidence", files={"file": ("a.png", PNG, "image/png")}, headers=BUY).status_code == 200
    assert c.post(rid + "/evidence", files={"file": ("a.png", PNG, "image/png")}).status_code == 401, "photo upload needs sign-in"
    assert c.post(rid + "/act", json={"action": "complete", "note": "Collected paddy straw from 6 acres."}, headers=BUY).status_code == 200
    assert c.get(rid + "/role", headers=BUY).json()["mine"]["status"] == "completed"

    # --- farmer: ask for help, choose a proposed solution, withdraw (consent ends), choose again
    ptoken = re.search(r"/#/respond/(\S+)", msgs["+912000000011"]).group(1)
    assert c.get(rid + "/role", headers=FAR).json()["can_request"] and c.get("/api/me/requests", headers=FAR).json() == []
    assert c.post(rid + "/requests", json={"needs": ["baler"]}, headers=BUY).status_code == 403, "only farmers ask for help"
    assert c.post(rid + "/requests", json={"needs": ["baler"]}).status_code == 401 and c.get("/api/me/requests", headers=BUY).status_code == 403
    rq = c.post(rid + "/requests", json={"needs": ["seeder", "buyer"], "note": "Need help with 10 acres of paddy straw"}, headers=FAR).json()
    assert rq["status"] == "proposed" and {p["name"] for p in rq["proposals"]} >= {"Test Provider", "Test Buyer"}
    pv = next(p for p in rq["proposals"] if p["name"] == "Test Provider"); bv = next(p for p in rq["proposals"] if p["name"] == "Test Buyer")
    assert pv["contact"] == "+912000000011" and bv["contact"] is None, "a contact shows only if that provider chose to be listed, or once they take the job"
    assert c.post(rid + "/requests", json={}, headers=FAR).status_code == 400, "one open request at a time"
    FAR2, _ = login("+912000000013", "whatsapp")
    assert c.get(rid + "/role", headers=FAR2).json()["requests"] == [], "other farmers never see this request"
    assert c.post(f"{rid}/requests/{rq['rid']}/accept", json={"sid": pv["sid"]}, headers=FAR2).status_code == 404 and c.post(f"{rid}/requests/{rq['rid']}/withdraw", headers=FAR2).status_code == 404
    assert c.get("/api/respond/" + ptoken).json()["jobs"] == [], "nothing is shared before the farmer chooses"
    ch = c.post(f"{rid}/requests/{rq['rid']}/accept", json={"sid": pv["sid"], "share_location": False}, headers=FAR).json(); assert ch["status"] == "waiting_provider"
    jb = c.get("/api/respond/" + ptoken).json(); j0 = jb["jobs"][0]
    assert jb["leads"] == [] and "contact" not in j0 and "name" not in j0 and j0["approx_km"] % 5 == 0, "before accepting, the provider sees the need and a rough area, not the farmer"
    assert c.get(rid + "/role", headers=BUY).json()["mine"]["status"] == "completed" and c.get(rid + "/role", headers=BUY).json()["jobs"] == [], "other providers see none of it"
    assert c.post(f"{rid}/requests/{rq['rid']}/withdraw", headers=FAR).json()["status"] == "withdrawn"
    assert c.get("/api/respond/" + ptoken).json()["jobs"] == [], "withdrawing ends the sharing at once"
    rq = c.post(rid + "/requests", json={"needs": ["seeder", "buyer"], "note": "Asking again"}, headers=FAR).json()
    assert c.post(f"{rid}/requests/{rq['rid']}/accept", json={"sid": pv["sid"], "share_location": False}, headers=FAR).json()["status"] == "waiting_provider"
    assert c.post(f"{rid}/requests/{rq['rid']}/accept", json={"sid": bv["sid"]}, headers=FAR).status_code == 400, "one chosen option at a time"
    staff_rq = c.get(rid + "/role", headers=OFF).json()["requests"]; assert any(r["farmer"]["contact"] == "+912000000010" and r["status"] == "waiting_provider" for r in staff_rq), "officers in the area see farmer requests"
    assert any("/#/respond/" in l["url"] for l in out["links"]), "test mode shows the response links"
    assert "+912000000014" in msgs and "+912000000010" in msgs, "officers and farmers are told too"
    token = re.search(r"/#/respond/(\S+)", msgs["+912000000011"]).group(1)
    assert c.get("/api/respond/" + token + "x").status_code == 404, "tampered links are rejected"
    assert c.get("/api/respond/" + token).json()["leads"] == []
    assert c.post("/api/respond/" + token, json={"action": "complete", "note": "x" * 12}).status_code == 400, "must accept before completing"
    assert c.post("/api/respond/" + token, json={"action": "accept"}).status_code == 200
    leads = c.get("/api/respond/" + token).json()["leads"]
    assert any(l["contact"] == "+912000000010" for l in leads) and not any(l["contact"] == "+912000000013" for l in leads), "only farmers who chose this provider are shared"
    assert leads[0]["lat"] is None and leads[0]["lon"] is None, "exact location stays private unless the farmer ticked share"
    assert c.get("/api/me/requests", headers=FAR).json()[0]["status"] == "in_progress"
    assert c.post("/api/respond/" + token, json={"action": "complete", "note": "short"}).status_code == 400
    assert c.post("/api/respond/" + token + "/evidence", files={"file": ("a.txt", b"hello", "text/plain")}).status_code == 400, "only photos are accepted"
    assert c.post("/api/respond/" + token + "/evidence", files={"file": ("a.png", PNG, "image/png")}).status_code == 200
    assert c.post("/api/respond/" + token, json={"action": "complete", "note": "Sowed wheat through residue on 10 acres."}).status_code == 200
    assert c.get("/api/impact").json()["interventions"]["verified"] == 0, "reported completions are not verified results"
    assert c.post(f"/api/interventions/{iv['id']}/verify", json={"approve": True}).status_code == 401
    assert c.post(f"/api/interventions/{iv['id']}/verify", json={"approve": True}, headers=FAR).status_code == 401, "farmers cannot verify"
    cl = c.get(rid + "/role", headers=OFF).json()["claims"]
    assert {x["name"] for x in cl} == {"Test Buyer", "Test Provider"} and all(x["status"] == "completed" and x["note"] for x in cl), "each completion is a claim with its own note"
    assert c.get("/api/me/requests", headers=FAR).json()[0]["status"] == "completed", "reported is not verified"
    bsid = next(x["sid"] for x in cl if x["name"] == "Test Buyer")
    part = c.post(f"/api/interventions/{iv['id']}/verify", json={"approve": True, "note": "Buyer checked", "sid": bsid}, headers=OFF).json()
    assert part["status"] == "completed" and not part["verified"], "one claim decided, the provider's is still waiting"
    ver = c.post(f"/api/interventions/{iv['id']}/verify", json={"approve": True, "note": "Checked with the farmer"}, headers=OFF).json()   # an officer signs in, no admin token needed
    assert c.get("/api/me/requests", headers=FAR).json()[0]["outcome"]["status"] == "verified"
    assert ver["status"] == "verified" and ver["satellite"] is not None
    m = c.get("/api/impact").json()["interventions"]; assert m["verified"] == 1 and m["completed_reported"] == 0
    det = c.get(f"/api/interventions/{iv['id']}", headers=ADMIN).json(); photo = next(e for e in det["evidence"] if e["type"] == "photo")
    assert c.get(f"/api/evidence/{iv['id']}/{photo['name']}", headers=ADMIN).status_code == 200 and c.get(f"/api/evidence/{iv['id']}/{photo['name']}").status_code == 401
    assert c.get(rid + "/role", headers=OFF).json()["verification"]["by"] == "Test", "the officer who verified is recorded"
    c.post("/api/subscribers", json=mk(role="officer", contact="+912000000015", lat=0.0, lon=0.0, name="Far Officer", profile={"designation": "Other district", "area": {"district": "Nowhere", "state": "Nowhere"}}), headers=ADMIN)
    OFF2, _ome2 = login("+912000000015")
    assert c.get(rid + "/role", headers=OFF2).json()["covered"] is False and "matches" not in c.get(rid + "/role", headers=OFF2).json(), "officers outside the area get no details"
    assert c.get(rid, headers=OFF2).status_code == 403 and c.post(rid + "/verify", json={"approve": True}, headers=OFF2).status_code == 403
    assert c.get(f"/api/evidence/{iv['id']}/{photo['name']}", headers=OFF).status_code == 200 and c.get(f"/api/evidence/{iv['id']}/{photo['name']}", headers=OFF2).status_code == 403
    c.post("/api/subscribers", json=mk(role="officer", contact="+912000000016", lat=0.0, lon=0.0, name="No Area Officer", profile={"designation": "No area set"}), headers=ADMIN)
    OFF3, _ = login("+912000000016")
    assert c.get(rid + "/role", headers=OFF3).json()["covered"] is False and c.get(rid, headers=OFF3).status_code == 403, "an officer with no area set gets their own radius, never everything"
    assert OFF3["x-session"] and c.get("/api/me/interventions", headers=OFF3).json() == []

    # --- administrators: sign in with a code, short session, never in public counts, every sensitive change audited
    server.store.put_sub({"created": "2026-01-01T00:00:00Z", "name": "Test Admin", "role": "admin", "channel": "email", "contact": "admin@example.com", "lat": 0.0, "lon": 0.0,
                          "radius_km": 50, "active": 1, "demo": 0, "lang": "en", "share": 0, "profile": {"designation": "Administrator", "consent": {"at": "x", "channel": "email", "version": 1}}})
    assert "dev_code" not in c.post("/api/session/start", json={"channel": "email", "contact": "admin@example.com"}).json(), "staff codes are never shown on the page"
    server.hits.clear(); server.store.otp_put("email", "admin@example.com", "login", "x", 0, 0)    # clear the one-minute wait so the helper can ask again
    ADM, am = login("admin@example.com", "email"); assert am["role"] == "admin" and am["role_label"] == "Administrator"
    exp = int(ADM["x-session"].split(".")[2]); assert exp - time.time() < 8 * 3600 + 5, "administrator sessions last 8 hours"
    assert not any(x["role"] == "admin" for x in server.visible_subs()), "administrators are not in matching, counts or alerts"
    assert c.post("/api/subscribers", json=mk(contact="admin@example.com", channel="email")).json()["verify"] is False and server.store.get_sub("email", "admin@example.com")["role"] == "admin", "an administrator account cannot be overwritten"
    assert c.get("/api/subscribers", headers=ADM).status_code == 200
    for who in (OFF, FAR, BUY):
        assert c.get("/api/subscribers", headers=who).status_code == 403 and c.post("/api/refresh", headers=who).status_code == 403 and c.get("/api/audit", headers=who).status_code == 403, "admin-only means admin only"
        assert c.post("/api/alerts/send", json={"lat": k["lat"], "lon": k["lon"]}, headers=who).status_code == 403
    assert c.get("/api/subscribers").status_code == 401 and c.get("/api/audit").status_code == 401
    assert c.get("/api/audit", headers={"x-admin-token": "wrong"}).status_code == 401
    assert c.get(rid + "/role", headers=ADM).json()["covered"] is True and c.get(rid, headers=ADM).status_code == 200
    au = c.get("/api/audit", headers=ADM).json(); acts = {a["action"] for a in au}
    need = {"login", "login_failed", "officer_registered", "request_created", "proposal_accepted", "request_withdrawn", "provider_accept", "claim_verified", "evidence_viewed", "admin_token_rejected", "denied_outside_area", "denied_admin_only", "farmer_requests_viewed"}
    assert need <= acts, need - acts
    dump = json.dumps(au); assert "+9120000" not in dump and "admin@example.com" not in dump, "the audit trail holds no contact details"

    # --- alerts: personalised, translated, language and provider sharing
    server.hits.clear(); server._prov["t"] = 0
    assert any(p["name"] == "Test Provider" and p["registered"] for p in agent.nearby_alternatives(k["lat"], k["lon"], 10)), "consenting providers are offered to farmers"
    got = []; server.deliver = lambda s, subject, body: (got.append((s["contact"], body)), ("sent", ""))[1]
    c.post("/api/alerts/send", json={"lat": k["lat"], "lon": k["lon"]}, headers=ADMIN); server.deliver = real
    msgs = dict(got); assert "km from you" in msgs["+912000000010"] and "Nearest option to you" in msgs["+912000000010"], msgs["+912000000010"]
    assert c.post("/api/subscribers", json=mk(contact="+912000000099", lang="xx")).status_code == 400, "unknown language rejected"
    nb = c.get("/api/data").json()["clusters"][0]["nearby"]; assert nb["farmer"] >= 2 and nb["machine_provider"] >= 1 and "_cells" not in c.get("/api/data").text
    imp = c.get("/api/impact").json(); assert "enough" in imp and "note" in imp and server.in_window()

    # --- website on another address (Amplify): CORS lets in only the listed sites and only the headers the website uses
    ok_o, bad_o = "https://main.d123abc.amplifyapp.com", "https://evil.example"
    pf = lambda o, h: c.options("/api/me", headers={"Origin": o, "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": h})
    r = pf(ok_o, "x-session"); assert r.status_code == 200 and r.headers.get("access-control-allow-origin") == ok_o, "listed website allowed"
    assert pf("http://localhost:5173", "content-type").headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "access-control-allow-origin" not in pf(bad_o, "x-session").headers, "unlisted website refused"
    assert "access-control-allow-origin" not in pf("http://evil.example", "x-session").headers, "plain http (non-local) is never accepted"
    assert pf(ok_o, "x-admin-token").status_code == 400, "the admin token header is not allowed from any web page"
    assert c.get("/api/health", headers={"Origin": ok_o}).headers.get("access-control-allow-origin") == ok_o
    assert server.cors_origins() == [ok_o, "http://localhost:5173"], "wildcards and insecure origins are dropped"

# --- demo subscribers stay hidden and are never messaged
    base_n = send()
    import seed_demo
    n_demo = seed_demo.seed(); assert n_demo >= 4
    assert c.get("/api/data").json()["demo_subscribers"] == 0 and send() == base_n
    assert not [i for i in c.get("/api/interventions").json() if i.get("demo")], "demo interventions are hidden by default"
    before = c.get("/api/impact").json()["interventions"]["verified"]
    server.INCLUDE_DEMO = True
    shown = [i for i in c.get("/api/interventions").json() if i.get("demo")]
    assert {i["status"] for i in shown} == {"open", "coordinating", "accepted", "completed", "verified"}, "demo covers every stage"
    assert c.get("/api/impact").json()["interventions"]["verified"] == before + 1
    assert c.get("/api/data").json()["demo_subscribers"] >= 1
    r = c.post("/api/alerts/send", json={"lat": k["lat"], "lon": k["lon"]}, headers=ADMIN).json()
    assert r["recipients"] > base_n and r["demo"] >= 1 and r["delivered"] == 0, "demo subscribers are matched but never messaged"
    server.INCLUDE_DEMO = False; assert seed_demo.remove() == n_demo
    assert not [i for i in store.list_interventions(500) if i.get("demo")], "removing demo data also removes demo interventions"

    # --- abuse limits
    server.hits.clear()
    codes = {c.post("/api/subscribers", json=mk(contact=f"+9188888{i:05d}")).status_code for i in range(12)}
    assert 429 in codes, "sign-up must be rate limited"
    assert c.get("/api/health").json()["ok"]
print("All checks passed")
