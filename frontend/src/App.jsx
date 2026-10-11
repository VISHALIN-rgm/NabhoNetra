import { useEffect, useState } from "react";
import { House, Map as MapIcon, Sparkles, ShieldCheck, BookOpen, TrendingUp, UserPlus, Bell, Globe, Flame, Users, RefreshCw,
  Send, Factory, Tractor, Sprout, Recycle, Zap, Wind, Gauge, ArrowRight, Activity, Info, CalendarDays, MapPin, Clock } from "lucide-react";
import MapPage from "./MapPage.jsx";
import Logo from "./Logo.jsx";
import Subscribe from "./Subscribe.jsx";
import Interventions from "./Interventions.jsx";
import { AccountButton, SignInModal } from "./Account.jsx";
import Respond from "./Respond.jsx";
import { Badge, Ring, Spark } from "./ui.jsx";
import { api, getMe, getSession, clearSession } from "./api.js";
import { COLORS, LABEL, riskOf, reasonsOf, compass, placeOf, fmtTime , smokeLine, nearbyLine, sourceLine } from "./shared.js";
import "./styles.css";

const TABS = [["home", "Home", House], ["map", "Live map", MapIcon], ["ai", "AI analysis", Sparkles], ["interventions", "Interventions", ShieldCheck],
  ["resources", "Resources", BookOpen], ["impact", "Impact", TrendingUp]];
const useHash = () => {
  const get = () => (location.hash.replace("#/", "") || "home");
  const [h, setH] = useState(get);
  useEffect(() => { const f = () => setH(get()); addEventListener("hashchange", f); return () => removeEventListener("hashchange", f); }, []);
  return h;
};
const Head = ({ title, sub, children }) => (
  <div className="pagehead"><div><h1>{title}</h1><p>{sub}</p></div><div className="headact">{children}</div></div>);
const Kpi = ({ icon: I, label, value, tone = "green", spark }) => (
  <div className="kpi"><span className={"kico " + tone}><I size={20} /></span><div><b>{value ?? 0}</b><small>{label}</small></div>{spark && <Spark values={spark} />}</div>);
function Daily({ daily }) {
  if (!daily?.length) return <p className="none">Run a refresh to add daily counts.</p>;
  const dm = Math.max(...daily.map((d) => d.count), 1), w = 460 / daily.length;
  return (
    <svg viewBox="0 0 460 210" className="chart" role="img" aria-label="Fires detected per day">
      {[0, 0.5, 1].map((t) => <line key={t} x1="0" x2="460" y1={170 - t * 140} y2={170 - t * 140} stroke="#E2E8F0" />)}
      {daily.map((d, i) => { const h = (d.count / dm) * 140; return (
        <g key={d.date}><rect x={i * w + w * 0.2} y={170 - h} width={w * 0.6} height={h} rx="5" fill="#0E9F6E" />
          <text x={i * w + w / 2} y={164 - h} textAnchor="middle" fontSize="12" fontWeight="600" fill="#0B1233">{d.count}</text>
          <text x={i * w + w / 2} y="192" textAnchor="middle" fontSize="11" fill="#64748B">{d.date.slice(5)}</text></g>); })}
    </svg>);
}

export default function App() {
  const route = useHash();
  const [page, arg] = route.split("/");
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");
  const [sel, setSel] = useState(null);
  const [log, setLog] = useState([]);
  const [effect, setEffect] = useState(null);
  useEffect(() => { if (page === "impact") api("/api/impact").then(setEffect).catch(() => {}); }, [page]);
  const [toast, setToast] = useState("");
  const [me, setMe] = useState(getMe()); const [signIn, setSignIn] = useState(false);
  const admin = me?.role === "admin";      // set by the server when an administrator signs in; there is no token in the browser
  const [audit, setAudit] = useState([]);
  useEffect(() => { if (admin && page === "interventions") api("/api/audit").then(setAudit).catch(() => setAudit([])); else setAudit([]); }, [admin, page, data]);
  useEffect(() => { const f = () => setMe(getMe()); addEventListener("nn-session", f); return () => removeEventListener("nn-session", f); }, []);
  useEffect(() => { if (getSession()) api("/api/me").then(setMe).catch((e) => { if (/sign in/i.test(e.message)) clearSession(); }); }, []);
  const joinNow = () => { location.hash = "#/home"; setTimeout(() => document.getElementById("join")?.scrollIntoView({ behavior: "smooth" }), 200); };

  const load = () => (import.meta.env.VITE_DATA_URL ? fetch(import.meta.env.VITE_DATA_URL).then((r) => r.json()) : api("/api/data"))
    .then((d) => { setData(d); setSel((s) => s || d.clusters[0]?.id); setErr(""); })
    .catch((e) => {
      if (/no data yet|in progress/i.test(e.message)) { setErr("The first data run is still loading, which can take a minute or two. This page will retry by itself."); setTimeout(load, 5000); }
      else setErr("We could not load live data right now. " + e.message);
    });
  useEffect(() => { load(); }, []);
  useEffect(() => { if (["interventions", "impact"].includes(page)) api("/api/alerts").then(setLog).catch(() => {}); }, [page, data]);
  useEffect(() => { if (data?.refreshing) { const t = setTimeout(load, 5000); return () => clearTimeout(t); } }, [data]);

  const flash = (m) => { setToast(m); setTimeout(() => setToast(""), 2400); };
  const send = (id) => {
    if (!admin) return flash("Sending alerts is for administrators. Sign in as an administrator.");
    const c = data.clusters.find((x) => x.id === id); if (!c) return;
    api("/api/alerts/send", { method: "POST", body: JSON.stringify({ lat: c.lat, lon: c.lon }) })
      .then((r) => { flash(r.recipients ? `Alert sent to ${r.recipients} subscriber(s)${r.mode === "log" ? " (log mode, not delivered)" : ""}` : "No subscribers within range yet"); load(); })
      .catch((e) => flash(e.message));
  };
  const refresh = () => api("/api/refresh", { method: "POST" }).then(() => { flash("Refresh started, new data in a minute or two"); setTimeout(load, 4000); }).catch((e) => flash(e.message));
  const copy = (t) => { navigator.clipboard?.writeText(t); flash("Alert copied"); };
  const go = (id, p) => { setSel(id); location.hash = "#/" + p; };

  const cl = data?.clusters || [];
  const max = Math.max(...cl.map((c) => c.score), 1);
  const isSent = (c) => c.status === "sent";
  const high = cl.filter((c) => c.priority === "high");
  const pending = high.filter((c) => !isSent(c));
  const cur = cl.find((c) => c.id === sel) || cl[0];
  const ranked = [...cl].sort((a, b) => riskOf(b, max) - riskOf(a, max));
  const fresh = data?.updated && Date.now() - new Date(data.updated).getTime() < 6 * 3600e3;
  const ai = !data ? ["off", "Connecting"] : data.refreshing ? ["work", "AI working"] : fresh ? ["on", "AI active"] : ["idle", "AI idle"];
  const today = new Date().toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
  const coords = (la, lo) => `${Math.abs(la).toFixed(2)}°${la >= 0 ? "N" : "S"}, ${Math.abs(lo).toFixed(2)}°${lo >= 0 ? "E" : "W"}`;
  const notes = data ? [data.mock && "Sample fires", data.demo_subscribers > 0 && "Demo subscribers included", data.wind_source === "assumed" && !data.mock && "Wind assumed", data.alternatives_source === "sample" && "Sample alternatives", data.alternatives_source === "none" && "No listed alternatives found yet"].filter(Boolean) : [];
  const daily = data?.daily || [];
  const delivered = log.reduce((s, x) => s + (x.delivered || 0), 0), failed = log.reduce((s, x) => s + (x.failed || 0), 0);
  const nearby = Object.values(cl.flatMap((c) => c.alert?.alternatives || []).reduce((m, a) => { const k = a.type + a.name; if (!m[k] || a.km < m[k].km) m[k] = a; return m; }, {})).sort((a, b) => a.km - b.km).slice(0, 12);
  const Ic = (t) => (/biomass/i.test(t) ? Factory : Tractor);

  return (
    <div className={"shell" + (admin ? " admin" : "")}>
      <nav className="top" aria-label="Main">
        <a className="brand" href="#/home"><Logo /><span className="bname">NabhoNetra<small>Crop-fire intelligence</small></span></a>
        <div className="tabs">{TABS.map(([id, t, I]) => <a key={id} href={"#/" + id} title={t} aria-current={page === id ? "page" : undefined} className={page === id ? "on" : ""}><I size={16} /><span>{t}</span></a>)}</div>
        <div className="right">
          <label className="country" title="Country"><Globe size={16} /><select aria-label="Country" defaultValue="IN"><option value="IN">India</option><option disabled>Bangladesh (soon)</option><option disabled>Pakistan (soon)</option><option disabled>Nepal (soon)</option></select></label>
          <a className="iconbtn" href="#/interventions" title="Pending high-priority alerts" aria-label={`Alerts, ${pending.length} pending`}><Bell size={18} />{pending.length > 0 && <sup>{pending.length}</sup>}</a>
          <AccountButton me={me} onSignIn={() => setSignIn(true)} flash={flash} />
          <span className={"aipill " + ai[0]} title={data?.updated ? "Last update " + data.updated : ""}><i />{ai[1]}</span>
          {admin && <button className="iconbtn" onClick={refresh} title="Refresh data (admin)" aria-label="Refresh data"><RefreshCw size={17} /></button>}
        </div>
      </nav>

      {err && <p className="empty">{err}</p>}
      {!err && !data && <p className="empty">Loading live fire data</p>}

      {page === "respond" && <Respond token={arg} />}

      {data && page === "home" && (
        <section className="page">
          {notes.length > 0 && <div className="notice"><Info size={16} /> Data notice: {notes.join(", ")}.</div>}
          <div className="hero card">
            <div><div className="metarow"><span><CalendarDays size={14} /> {today}</span>{data.place?.region && <span><MapPin size={14} /> Monitoring: {data.place.region}</span>}
                {data.scope === "india" ? <span><MapPin size={14} /> Scope: all of India (NASA FIRMS)</span> : <span><MapPin size={14} /> Target city: {data.place?.city || coords(data.city.lat, data.city.lon)}</span>}<span><Clock size={14} /> Updated {new Date(data.updated).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}</span></div>
              <h1>{data.scope === "india" ? "Track crop fires across India before smoke reaches cities" : "Stop crop-fire smoke before it reaches the city"}</h1>
              <p>Satellite fire detections, wind and distance are combined to rank the riskiest clusters. An AI agent writes the alert and names the nearest alternative to burning, then registered farmers and officials are notified.</p>
              <div className="ctas"><a className="btn primary" href="#/map">Open live map <ArrowRight size={16} /></a><button className="btn" onClick={() => document.getElementById("join")?.scrollIntoView({ behavior: "smooth" })}><UserPlus size={16} /> Join NabhoNetra</button></div></div>
            {cl[0] && <div className="focus"><small>Top priority now</small><div className="focusrow"><Ring v={riskOf(cl[0], max)} color={COLORS[cl[0].priority]} /><div><b>Cluster {cl[0].id}</b><span>{cl[0].fires} fires, {cl[0].distance_km} km from {cl[0].city_name || "city"}</span><button className="btn" onClick={() => go(cl[0].id, "map")}>See on map</button></div></div></div>}
          </div>
          <div className="kpis">
            <Kpi icon={Flame} label="Fires detected" value={data.fires_total} tone="red" spark={daily.map((d) => d.count)} />
            <Kpi icon={Activity} label="High-priority clusters" value={high.length} tone="amber" />
            <Kpi icon={Send} label="Alerts sent" value={cl.filter(isSent).length} tone="green" />
            <Kpi icon={Users} label="Subscribers" value={data.subscribers_count} tone="blue" />
            {data.scope === "india"
              ? <Kpi icon={Gauge} label="Cities in smoke path" value={new Set(cl.filter((c) => c.city_name && (c.eta_hours || c.reach >= 0.5)).map((c) => c.city_name)).size} tone="slate" />
              : <Kpi icon={Gauge} label="City AQI" value={data.city.aqi ?? "n/a"} tone="slate" />}
          </div>
          <div className="cols">
            <div className="card"><div className="cardhead"><h2>Highest-risk clusters</h2><a href="#/ai" className="link">AI analysis</a></div>
              <ul className="mini">{ranked.slice(0, 6).map((c) => (
                <li key={c.id} onClick={() => go(c.id, "map")}><span className="dot" style={{ background: COLORS[c.priority] }} /><b>{c.id}</b><span>{c.fires} fires, {placeOf(c)}</span><strong>{riskOf(c, max)}%</strong><Badge tone={isSent(c) ? "ok" : "warn"}>{isSent(c) ? "Sent" : "Pending"}</Badge></li>))}</ul></div>
            <div className="card"><div className="cardhead"><h2>Fires per day</h2></div><Daily daily={daily} /></div>
          </div>
          <section className="flowsec"><h2>How NabhoNetra works</h2>
            <ol className="flowgrid">{[["Detect", "Use NASA FIRMS satellite observations to identify fire hotspots and group nearby detections."],
              ["Analyze", "Combine fire observations with wind, weather, historical patterns, and available local information. Distinguish observed fires from estimated future risk."],
              ["Find the cause and solution", "Assess possible barriers, such as machinery shortages, and match registered providers or biomass buyers when suitable options are available."],
              ["Coordinate", "Create an intervention and send relevant alerts to the farmer, provider, buyer, or officer, subject to their preferences and consent."],
              ["Verify", "Track acceptance and completion, collect supporting evidence, and update impact metrics only when the outcome is adequately verified."]]
              .map(([t, d], n) => <li className="card" key={t}><span className="flown">{String(n + 1).padStart(2, "0")}</span><h3>{t}</h3><p>{d}</p></li>)}</ol></section>
          <section className="joinsec" id="join">
            <span className="eyebrow"><Users size={14} /> Join NabhoNetra</span>
            <h2>Join NabhoNetra</h2>
            <p className="muted">One registration for everyone in the stubble-burning chain. Choose your role, set your location and radius, and get alerts that fit what you do. {data.subscribers_count} registered so far.</p>
            <div className="rolegrid">{[[Sprout, "Farmer", "Early warning and the nearest alternative to burning."], [Tractor, "Machine provider", "Know where fires cluster so you can offer seeders, balers or mulchers."],
              [Factory, "Biomass buyer", "Know where straw is likely to be available for collection."], [ShieldCheck, "Officer", "Receive every high-priority alert and send alerts to a district."]]
              .map(([I, t, d]) => <div className="card rolecard" key={t}><span className="kico green"><I size={18} /></span><b>{t}</b><p>{d}</p></div>)}</div>
            <Subscribe data={data} me={me} />
          </section>
        </section>)}

      {data && page === "map" && <MapPage {...{ data, sel, setSel, isSent, send, copy, max }} />}

      {data && page === "ai" && cur && (
        <section className="page">
          <Head title="AI analysis" sub="How the agent ranks clusters and why each one matters. Risk index is an estimate from wind, distance and fire count." />
          {notes.length > 0 && <div className="notice"><Info size={16} /> Data notice: {notes.join(", ")}.</div>}
          <div className="cols aicols">
            <div className="card"><div className="cardhead"><h2>Risk ranking</h2><span className="muted">{cl.length} clusters</span></div>
              <ul className="rank">{ranked.map((c) => (
                <li key={c.id}><button className={c.id === cur.id ? "row on" : "row"} onClick={() => setSel(c.id)}>
                  <span className="dot" style={{ background: COLORS[c.priority] }} /><span className="txt"><b>{c.id}</b><small>wind toward city {Math.round(c.alignment * 100)}%</small>
                    <span className="bar"><span style={{ width: `${riskOf(c, max)}%`, background: COLORS[c.priority] }} /></span></span><strong>{riskOf(c, max)}%</strong></button></li>))}</ul></div>
            <div className="card"><div className="dhead"><div><Badge tone={cur.priority}>{LABEL[cur.priority]} priority</Badge><h2>Why cluster {cur.id}?</h2>
              <small className="muted"><MapPin size={13} /> {placeOf(cur)}, latest detection {fmtTime(cur.last_detected)}</small>
              <small className="muted"><Wind size={13} /> Wind from {compass(cur.wind_from)} at {cur.wind_speed} km/h. {smokeLine(cur)}</small><small className="muted">{nearbyLine(cur)}</small></div><Ring v={riskOf(cur, max)} color={COLORS[cur.priority]} /></div>
              <h3>Reasons</h3><ul className="why">{reasonsOf(cur).map((r) => <li key={r}>{r}</li>)}</ul>
              <h3>Message the agent wrote</h3><div className="bubble">{cur.alert.text || "No alert written yet."}</div><small className="fine">{sourceLine(cur)}</small>
              <div className="btnrow"><button className="btn primary" onClick={() => go(cur.id, "map")}>Open on map</button><button className="btn" onClick={() => go(cur.id, "interventions")}>Go to interventions</button></div></div>
          </div>
          <div className="cols">
            <div className="card"><div className="cardhead"><h2>Fires per day</h2></div><Daily daily={daily} /></div>
            <div className="card"><div className="cardhead"><h2>How the AI decides</h2></div>{data.fires_raw > 0 && <p className="fine"><Info size={14} /> Filtered out {data.fires_raw - data.fires_total} of {data.fires_raw} detections (low satellite confidence {data.filtered?.low_confidence ?? 0}, weak {data.filtered?.weak ?? 0}, repeating heat sources {data.filtered?.static_source ?? 0}).</p>}
              <ol className="steps">{[["Detect", "NASA FIRMS reports fire hotspots; nearby detections are grouped into clusters."], ["Add wind", "Open-Meteo gives wind speed and direction at each cluster."],
                ["Rank", "Score = fire count, distance to the city and whether the 24-hour wind forecast carries smoke toward it."], ["Write", "The agent drafts a short alert naming the nearest alternative to burning."]]
                .map(([t, d], i) => <li key={t}><span className="n">{i + 1}</span><div><b>{t}</b><p>{d}</p></div></li>)}</ol></div>
          </div>
        </section>)}

      {data && page === "interventions" && (
        <section className="page">
          <Interventions data={data} me={me} isAdmin={admin} flash={flash} focus={arg} onJoin={joinNow} onSignIn={() => setSignIn(true)}>
            <button className="btn primary adminonly" disabled={!pending.length} onClick={() => pending.forEach((c) => send(c.id))}><Send size={16} />{pending.length ? `Send all high-priority (${pending.length})` : "All high-priority sent"}</button></Interventions>
          <details className="logdetails"><summary>Alert log and delivery history</summary>
          <h2 className="logh">Cluster alerts</h2>
          <div className="card tablecard"><table>
            <thead><tr><th>Cluster</th><th>Place and time</th><th>Priority</th><th>Risk</th><th>Nearest alternative</th><th>Message</th><th>Status</th><th /></tr></thead>
            <tbody>{ranked.map((c) => { const a = c.alert.alternatives?.[0]; return (
              <tr key={c.id}><td><b>{c.id}</b><small>{c.fires} fires</small></td><td>{placeOf(c)}<small>{fmtTime(c.last_detected)}</small></td><td><Badge tone={c.priority}>{LABEL[c.priority]}</Badge></td><td><strong>{riskOf(c, max)}%</strong></td>
                <td>{a ? <>{a.type}<small>{a.name}, {a.km} km</small></> : "n/a"}</td><td className="msg">{c.alert.text}</td>
                <td><Badge tone={isSent(c) ? "ok" : "warn"}>{isSent(c) ? "Sent" : "Pending"}</Badge></td>
                <td className="acts"><button className="btn sm" onClick={() => go(c.id, "map")}>View</button><button className="btn sm adminonly" disabled={isSent(c)} onClick={() => send(c.id)}>Send</button></td></tr>); })}</tbody></table></div>
          <h2 className="logh">Delivery log</h2>
          <div className="card tablecard"><table>
            <thead><tr><th>Time (UTC)</th><th>Priority</th><th>Recipients</th><th>Delivered</th><th>Failed</th><th>Mode</th></tr></thead>
            <tbody>{log.map((x) => <tr key={x.id}><td>{x.created.replace("T", " ").replace("Z", "")}</td><td>{x.priority}</td><td>{x.recipients}</td><td>{x.delivered}</td><td>{x.failed}</td><td><Badge tone="muted">{x.mode}</Badge></td></tr>)}
              {!log.length && <tr><td colSpan="6" className="none">No alerts sent yet.</td></tr>}</tbody></table></div>
          {admin && <><h2 className="logh">Audit trail (administrators only)</h2>
            <div className="card tablecard"><table>
              <thead><tr><th>Time (UTC)</th><th>Who</th><th>Role</th><th>Action</th><th>Target</th><th>Detail</th></tr></thead>
              <tbody>{audit.map((x, n) => <tr key={n}><td>{x.at.replace("T", " ").replace("Z", "")}</td><td>{x.actor}</td><td>{x.role}</td><td>{x.action.replaceAll("_", " ")}</td><td>{x.target}</td><td>{x.detail}</td></tr>)}
                {!audit.length && <tr><td colSpan="6" className="none">No entries yet.</td></tr>}</tbody></table></div></>}
          </details>
        </section>)}

      {data && page === "resources" && (
        <section className="page">
          <Head title="Resources" sub="Practical alternatives to burning, and the nearest listed support around active clusters." />
          <h2 className="logh">Alternatives to burning</h2>
          <div className="guides">{[[Tractor, "Sow through residue", "Happy Seeder and zero-till drills sow the next crop directly into straw, so nothing needs burning."],
            [Sprout, "Bio-decomposer", "Microbial sprays speed up decomposition of stubble in the field over a few weeks."],
            [Recycle, "Bale and sell", "Balers pack straw for fuel, fodder or industrial feedstock, which buyers collect."],
            [Zap, "Biomass energy", "Straw can feed biomass power and compressed biogas plants."]]
            .map(([I, t, d]) => <div className="card guide" key={t}><span className="kico green"><I size={20} /></span><h3>{t}</h3><p>{d}</p></div>)}</div>
          <div className="cardhead pad"><h2 className="logh">Nearest listed support</h2><Badge tone="muted">{data.alternatives_source === "OpenStreetMap" ? "OpenStreetMap listings, availability not verified" : "Sample data"}</Badge></div>
          <div className="guides">{nearby.map((a) => { const I = Ic(a.type); return (
            <div className="card guide" key={a.type + a.name}><span className="kico blue"><I size={20} /></span><h3>{a.name}</h3><p>{a.type}</p><small>{a.km} km from the nearest cluster</small><small>{a.contact}</small></div>); })}
            {!nearby.length && <p className="none">No listings loaded yet.</p>}</div>
          <div className="card" style={{ marginTop: 16 }}><div className="cardhead"><h2><ShieldCheck size={18} /> Privacy and your data</h2></div>
            <p className="fine">If you join, we store your name, role, contact, chosen location and alert radius, only to send fire alerts. Your contact is confirmed with a one-time code
              and is passed to Amazon SNS (SMS) or the email provider only to deliver messages. You can delete your data at any time from the Join form on the home page.
              Satellite fires come from NASA FIRMS, wind and air quality from Open-Meteo, and place names and listings from OpenStreetMap.</p></div>
        </section>)}

      {data && page === "impact" && (
        <section className="page">
          <Head title="Impact" sub="What NabhoNetra has measured: detections, alerts and delivery. It does not claim fires prevented." />
          <div className="kpis">
            <Kpi icon={Flame} label="Fires detected" value={data.fires_total} tone="red" spark={daily.map((d) => d.count)} />
            <Kpi icon={Activity} label="High-priority clusters" value={high.length} tone="amber" />
            <Kpi icon={Send} label="Alert batches logged" value={log.length} tone="green" />
            <Kpi icon={ShieldCheck} label="Messages delivered" value={delivered} tone="green" />
            <Kpi icon={Users} label="Subscribers" value={data.subscribers_count} tone="blue" />
          </div>
          <div className="cols">
            <div className="card"><div className="cardhead"><h2>Fires per day</h2></div><Daily daily={daily} /></div>
            <div className="card"><div className="cardhead"><h2>Delivery</h2></div>
              {[["Delivered", delivered, "#0E9F6E"], ["Failed", failed, "#F0443A"]].map(([l, v, c]) => (
                <div className="meter" key={l}><span>{l}</span><span className="bar"><span style={{ width: `${(v / Math.max(delivered + failed, 1)) * 100}%`, background: c }} /></span><b>{v}</b></div>))}
              <p className="fine"><Info size={14} /> Delivery counts come from the alert log. In log mode alerts are recorded but not sent.</p></div>
          </div>
          <div className="card" style={{ marginTop: 16 }}><div className="cardhead"><h2>Interventions and verified outcomes</h2></div>
            <div className="rolecount">{[["opened", "Opened"], ["coordinating", "Requests sent"], ["accepted", "Accepted"], ["completed_reported", "Reported complete, not yet verified"], ["verified", "Verified results"]]
              .map(([k, t]) => <div key={k}><b>{effect?.interventions?.[k] ?? 0}</b><small>{t}</small></div>)}</div>
            <p className="fine"><Info size={14} /> Only verified outcomes count as results. A completion becomes verified after an officer reviews the evidence, with a satellite re-check shown alongside.</p></div>
          <div className="card" style={{ marginTop: 16 }}><div className="cardhead"><h2>Did fires fall after alerts?</h2></div>
            {effect?.enough ? (<div className="rolecount"><div><b>{effect.alerted.median_change_pct}%</b><small>Median change in fire counts near alerted areas ({effect.alerted.n} cases)</small></div>
              <div><b>{effect.other.median_change_pct}%</b><small>Median change in other active areas ({effect.other.n} cases)</small></div></div>)
              : <p className="muted">Not enough data yet. This needs alerts followed by at least two days of fire data.</p>}
            <p className="fine"><Info size={14} /> {effect?.note} Negative means fewer fires. A difference is an association, not proof that the alerts caused it.</p></div>
          <div className="card" style={{ marginTop: 16 }}><div className="cardhead"><h2>Who has joined</h2></div>
            <div className="rolecount">{[["farmer", "Farmers"], ["machine_provider", "Machine providers"], ["biomass_buyer", "Biomass buyers"], ["officer", "Officers"]]
              .map(([k, t]) => <div key={k}><b>{data.subscribers_by_role?.[k] ?? 0}</b><small>{t}</small></div>)}</div></div>
        </section>)}

      <footer className="foot"><span>Fire detections: NASA FIRMS. Wind and air quality: Open-Meteo. Maps: Esri and OpenStreetMap contributors.</span>
        {!me && <button type="button" className="linkbtn" onClick={() => setSignIn(true)}>Sign in</button>}</footer>
      {signIn && <SignInModal onClose={() => setSignIn(false)} flash={flash} />}
      {toast && <div className="toast" role="status">{toast}</div>}
    </div>
  );
}
