import { useEffect, useState } from "react";
import { MapContainer, TileLayer, Marker, useMap, useMapEvents } from "react-leaflet";
import L from "leaflet";
import { Locate, Search, ShieldCheck, Sprout, Tractor, Factory } from "lucide-react";
import { api, setSession } from "./api.js";

const pin = L.divIcon({ className: "city", iconSize: [14, 14] });
function Pick({ onPick }) { useMapEvents({ click: (e) => onPick([e.latlng.lat, e.latlng.lng]) }); return null; }
function Fly({ to }) { const map = useMap(); useEffect(() => { if (to) map.flyTo(to, Math.max(map.getZoom(), 11), { duration: 0.6 }); }, [to]); return null; }

const ROLES = [["farmer", "Farmer", Sprout, "Get nearby residue-management solutions."], ["machine_provider", "Machine provider", Tractor, "See service requests you can take."],
  ["biomass_buyer", "Biomass buyer", Factory, "See residue opportunities in your range."], ["officer", "Officer", ShieldCheck, "Track priority interventions in your area. Only an administrator can add officers."]];
const CROPS = [["paddy", "Paddy (rice)"], ["wheat", "Wheat"], ["sugarcane", "Sugarcane"], ["other", "Other"]];
const HARVEST = [["harvested", "Already harvested"], ["within_2_weeks", "Harvest within 2 weeks"], ["not_yet", "Not yet"]];
const NEEDS = [["seeder", "Sow through residue (seeder)"], ["mulcher", "Mulcher or chopper"], ["baler", "Baler"], ["buyer", "A buyer for the straw"], ["decomposer", "Bio-decomposer"]];
const MACH = [["seeder", "Happy Seeder or zero-till drill"], ["mulcher", "Mulcher or chopper"], ["baler", "Baler"], ["rake", "Rake or collector"]];
const MATS = [["paddy_straw", "Paddy straw"], ["wheat_straw", "Wheat straw"], ["sugarcane_trash", "Sugarcane trash"], ["other", "Other residue"]];
const CH = { sms: "SMS", email: "Email", whatsapp: "WhatsApp" };
const SHARE = { machine_provider: "List my name and contact to farmers near me as a registered option (optional).", biomass_buyer: "List my name and contact to farmers near me as a registered option (optional)." };

const Seg = ({ value, onChange, options }) => (
  <div className="segctl" role="group">{options.map(([v, t]) => <button type="button" key={v} className={value === v ? "on" : ""} onClick={() => onChange(v)}>{t}</button>)}</div>);
const Chips = ({ options, value, onChange }) => (
  <div className="chips">{options.map(([v, t]) => <button type="button" key={v} className={value.includes(v) ? "on" : ""} aria-pressed={value.includes(v)}
    onClick={() => onChange(value.includes(v) ? value.filter((x) => x !== v) : [...value, v])}>{t}</button>)}</div>);

export default function Subscribe({ data, me }) {
  const [f, setF] = useState({ name: "", role: "farmer", channel: "sms", contact: "", radius_km: 10, lang: "en", min_priority: "high", share: false, consent: false });
  const [p, setP] = useState({ crop: "paddy", land_acres: "", harvest_status: "harvested", needs: [], machines: [], availability: "available", materials: [], capacity_tpd: "", rate_note: "", designation: "" });
  const [area, setArea] = useState({ state: "", district: "", village: "" });
  const [pos, setPos] = useState(null); const [focus, setFocus] = useState(null); const [hits, setHits] = useState([]); const [where, setWhere] = useState("");
  const [channels, setChannels] = useState(["sms", "email"]);
  const [msg, setMsg] = useState(null); const [step, setStep] = useState("form"); const [code, setCode] = useState(""); const [reg, setReg] = useState(null);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const setp = (k) => (e) => setP({ ...p, [k]: e.target.value });
  const say = (ok, t) => setMsg({ ok, t });
  const ref = () => ({ channel: f.channel, contact: f.contact });
  const test = (r) => (r.dev_code ? ` Test mode code: ${r.dev_code}` : "");
  const officer = f.role === "officer";

  useEffect(() => { api("/api/config").then((c) => Array.isArray(c.channels) && setChannels(c.channels)).catch(() => {}); }, []);
  useEffect(() => { if (pos) api(`/api/reverse?lat=${pos[0]}&lon=${pos[1]}`).then((r) => setWhere(r.area || "")).catch(() => setWhere("")); }, [pos]);

  const search = async () => {
    try { const r = await api("/api/geocode?" + new URLSearchParams(area)); setHits(r.results || []); if (!(r.results || []).length) say(false, "No match found. Try fewer words, or click the map."); else setMsg(null); }
    catch (e) { say(false, e.message); }
  };
  const choose = (h) => { setPos([h.lat, h.lon]); setFocus([h.lat, h.lon]); setHits([]); };
  const locate = () => navigator.geolocation
    ? navigator.geolocation.getCurrentPosition((x) => { const q = [x.coords.latitude, x.coords.longitude]; setPos(q); setFocus(q); }, () => say(false, "Could not get your location. Search or click the map instead."))
    : say(false, "Location is not available. Search or click the map instead.");
  const profile = () => ({ min_priority: f.min_priority, area, ...({
    farmer: { crop: p.crop, land_acres: Number(p.land_acres), harvest_status: p.harvest_status, needs: p.needs },
    machine_provider: { machines: p.machines, availability: p.availability, rate_note: p.rate_note },
    biomass_buyer: { materials: p.materials, capacity_tpd: Number(p.capacity_tpd) || 0, rate_note: p.rate_note }, officer: { designation: p.designation } })[f.role] });

  const submit = async (e) => {
    e.preventDefault();
    if (!pos) return say(false, "Set your location first: search for it or click the map.");
    try {
      const r = await api("/api/subscribers", { method: "POST", body: JSON.stringify({ ...f, radius_km: Number(f.radius_km), lat: pos[0], lon: pos[1], profile: profile() }) });
      if (r.verify) { setStep("code"); say(true, `We sent a 6-digit code to ${f.contact}. Enter it to confirm.` + test(r)); }
      else { setReg(r.registry || null); say(true, r.detail || "You are registered."); }
    } catch (err) { say(false, err.message); }
  };
  const confirm = async () => {
    try {
      const r = await api(step === "code" ? "/api/subscribers/verify" : "/api/subscribers/optout/confirm", { method: "POST", body: JSON.stringify({ ...ref(), code }) });
      if (step === "code" && r.session) setSession(r.session, r.me);
      say(true, step === "code" ? "Confirmed. You are now in the NabhoNetra registry" + (r.session ? " and signed in." : ".") : "Done. Your details are deleted and you will get no more messages.");
      setReg(step === "code" ? r.registry : null); setStep("form"); setCode("");
    } catch (err) { say(false, err.message); }
  };
  const optout = async () => {
    if (!f.contact) return say(false, "Enter the phone or email you registered with.");
    try { const r = await api("/api/subscribers/optout", { method: "POST", body: JSON.stringify(ref()) }); setStep("optcode"); say(true, "If that contact is registered, we sent a code to it." + test(r)); }
    catch (err) { say(false, err.message); }
  };

  return (
    <div className="joingrid">
      <form className="card form" onSubmit={submit}>
        <div className="cardhead"><h2>Join NabhoNetra</h2></div>
        <p className="fine">Register your role and location. You are added to the registry, and the intervention engine matches you with relevant requests, opportunities or solutions.</p>
        <label className="field">Full name<input value={f.name} onChange={set("name")} maxLength="80" placeholder="Your name" required /></label>
        <div className="field">I am a<Seg value={f.role} onChange={(v) => setF({ ...f, role: v, share: false })} options={ROLES.filter(([v]) => v !== "officer" || me?.role === "admin").map(([v, t]) => [v, t])} />
          <small className="fine">{ROLES.find((r) => r[0] === f.role)[3]}</small></div>

        {f.role === "farmer" && <>
          <div className="two"><label className="field">Land area (acres)<input type="number" min="0.1" step="0.1" value={p.land_acres} onChange={setp("land_acres")} required /></label>
            <label className="field">Main crop<select value={p.crop} onChange={setp("crop")}>{CROPS.map(([v, t]) => <option key={v} value={v}>{t}</option>)}</select></label></div>
          <div className="field">Harvest status<Seg value={p.harvest_status} onChange={(v) => setP({ ...p, harvest_status: v })} options={HARVEST} /></div>
          <div className="field">What help do you need?<Chips options={NEEDS} value={p.needs} onChange={(v) => setP({ ...p, needs: v })} /></div></>}
        {f.role === "machine_provider" && <>
          <div className="field">Machines you offer<Chips options={MACH} value={p.machines} onChange={(v) => setP({ ...p, machines: v })} /></div>
          <div className="field">Availability<Seg value={p.availability} onChange={(v) => setP({ ...p, availability: v })} options={[["available", "Available now"], ["limited", "Limited"], ["seasonal", "Seasonal"]]} /></div>
          <label className="field">Rates or terms (optional)<input value={p.rate_note} onChange={setp("rate_note")} maxLength="80" placeholder="For example: per acre, fuel extra" /></label></>}
        {f.role === "biomass_buyer" && <>
          <div className="field">Residue you buy<Chips options={MATS} value={p.materials} onChange={(v) => setP({ ...p, materials: v })} /></div>
          <label className="field">Capacity (tonnes per day, optional)<input type="number" min="0" value={p.capacity_tpd} onChange={setp("capacity_tpd")} /></label>
          <label className="field">Price or terms (optional)<input value={p.rate_note} onChange={setp("rate_note")} maxLength="80" /></label></>}
        {officer && <label className="field">Designation<input value={p.designation} onChange={setp("designation")} maxLength="60" placeholder="For example: District agriculture officer" /></label>}

        <div className="field">Where are you?
          <div className="two"><input placeholder="State" value={area.state} onChange={(e) => setArea({ ...area, state: e.target.value })} />
            <input placeholder="District" value={area.district} onChange={(e) => setArea({ ...area, district: e.target.value })} /></div>
          <input placeholder="Village or town" value={area.village} onChange={(e) => setArea({ ...area, village: e.target.value })} />
          <div className="btnrow"><button type="button" className="btn" onClick={search}><Search size={16} /> Find on map</button><button type="button" className="btn" onClick={locate}><Locate size={16} /> Use my location</button></div>
          {hits.length > 0 && <ul className="hits">{hits.map((h) => <li key={h.name}><button type="button" onClick={() => choose(h)}>{h.name}</button></li>)}</ul>}
          <small className="fine">{pos ? `Pinned: ${where || pos.map((x) => x.toFixed(3)).join(", ")}` : "Search above, or click the map to pin your location."}{officer && " Your district and state decide which interventions you see."}</small></div>
        <label className="field">{officer ? "Area radius" : "Alert and matching radius"} <b>{f.radius_km} km</b><input type="range" min="2" max="50" value={f.radius_km} onChange={set("radius_km")} /></label>

        <div className="field">Contact me by<Seg value={f.channel} onChange={(v) => setF({ ...f, channel: v })} options={channels.map((c) => [c, CH[c] || c])} /></div>
        <label className="field">{f.channel === "email" ? "Email address" : f.channel === "whatsapp" ? "WhatsApp number (with country code)" : "Phone (with country code)"}
          <input value={f.contact} onChange={set("contact")} placeholder={f.channel === "email" ? "name@example.com" : "+91XXXXXXXXXX"} required /></label>
        <div className="two"><label className="field">Alert me for<select value={f.min_priority} onChange={set("min_priority")}><option value="high">High priority only</option><option value="medium">High and medium</option></select></label>
          <label className="field">Language<select value={f.lang} onChange={set("lang")}><option value="en">English</option><option value="hi">Hindi</option><option value="pa">Punjabi</option></select></label></div>
        <small className="fine">Non-English messages are machine-translated; numbers and contacts stay exact, and English is sent if a translation cannot be verified.</small>
        <label className="check"><input type="checkbox" checked={f.consent} onChange={(e) => setF({ ...f, consent: e.target.checked })} /> I agree to be contacted on this channel about crop-fire alerts and interventions. I can stop at any time.</label>
        {f.role === "farmer" && <p className="fine">Your name, contact and location are never shared automatically. When you ask for help and choose a provider, only that provider sees your details, and your exact location only if you tick it. You can withdraw a request at any time.</p>}
        {SHARE[f.role] && <label className="check"><input type="checkbox" checked={f.share} onChange={(e) => setF({ ...f, share: e.target.checked })} /> {SHARE[f.role]}</label>}

        {step !== "form" && (
          <div className="field">Verification code<input value={code} onChange={(e) => setCode(e.target.value)} inputMode="numeric" maxLength="6" placeholder="6-digit code" autoComplete="one-time-code" />
            <div className="btnrow"><button type="button" className="btn primary" onClick={confirm}>{step === "code" ? "Confirm" : "Delete my data"}</button>
              <button type="button" className="btn" onClick={() => { setStep("form"); setCode(""); }}>Cancel</button></div></div>)}
        {step === "form" && <div className="btnrow"><button className="btn primary">Join NabhoNetra</button></div>}
        {msg && <p className={msg.ok ? "fmsg ok" : "fmsg"} role="status">{msg.t}</p>}
        <p className="fine"><ShieldCheck size={14} /> We confirm your contact with a code before sending anything. Your details are used only for fire alerts and interventions.{" "}
          <button type="button" className="linkbtn" onClick={optout}>Stop messages and delete my data</button></p>
      </form>
      <div className="stack">
        <div className="card joinmap">
          <div className="cardhead"><h2>Your location</h2><span className="muted">{pos ? where || `${pos[0].toFixed(3)}, ${pos[1].toFixed(3)}` : "Search or click the map"}</span></div>
          <MapContainer center={[data.city.lat, data.city.lon]} zoom={6} scrollWheelZoom>
            <TileLayer attribution="&copy; Esri" url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}" />
            <Pick onPick={(q) => setPos(q)} /><Fly to={focus} />{pos && <Marker position={pos} icon={pin} />}
          </MapContainer>
        </div>
        {reg && (
          <div className="card regcard"><div className="cardhead"><h2>{reg.title}</h2></div>
            {reg.items.length ? <ul>{reg.items.map((i) => <li key={i.id + i.place}><b>{i.place}</b><span>{i.id.length > 14 && reg.kind !== "solutions" ? "" : i.id}</span><small>{i.detail}</small></li>)}</ul> : <p className="muted">{reg.empty}</p>}
            <div className="btnrow"><a className="btn primary" href="#/interventions">Open your interventions</a></div>
          </div>)}
      </div>
    </div>
  );
}
