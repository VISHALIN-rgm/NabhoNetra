import { useEffect, useMemo, useRef, useState } from "react";
import { MapContainer, TileLayer, CircleMarker, Marker, Tooltip, ZoomControl, useMap } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { MapPin, Sprout, Radar, Brain, Link2, Users, BadgeCheck, ArrowRight, Sparkles, Tractor, Recycle, Navigation, Wind, Info } from "lucide-react";
import { Badge } from "./ui.jsx";
import { api } from "./api.js";
import { COLORS, LABEL, compass, fmtTime, smokeLine, sourceLine } from "./shared.js";
import { STAGES, STATUS, ROLE_LABEL, stageOf, buildItems, where } from "./ivutil.js";
import RolePanel from "./RolePanel.jsx";

const ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/";
const STREET = [{ u: ESRI + "World_Street_Map/MapServer/tile/{z}/{y}/{x}", a: "&copy; Esri" }, { u: "https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png", a: "&copy; OpenStreetMap &copy; CARTO" }];
const SAT = ESRI + "World_Imagery/MapServer/tile/{z}/{y}/{x}", LABELS = ESRI + "Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}";
const windIcon = (from) => L.divIcon({ className: "wind", iconSize: [20, 20], html: `<div style="transform:rotate(${(from + 180) % 360 - 90}deg)">&#10148;</div>` });
const HOW = [[Radar, "Detect", "Satellites spot fire and group nearby detections."], [Brain, "Analyze", "AI checks wind, forecast and local data."], [Link2, "Find a solution", "Match with registered providers or biomass buyers."],
  [Users, "Coordinate", "Officers notify and connect the right people."], [BadgeCheck, "Verify", "An officer confirms the outcome before it counts."]];

function Fit({ points }) {
  const map = useMap(); const n = points.length;
  useEffect(() => { const fit = () => { map.invalidateSize(); if (n) map.fitBounds(L.latLngBounds(points).pad(0.3), { animate: false, maxZoom: 9 }); }; fit(); const t = setTimeout(fit, 300); return () => clearTimeout(t); }, [n]);
  return null;
}
function Fly({ to }) {
  const map = useMap(); const first = useRef(true);
  useEffect(() => { if (first.current) { first.current = false; return; } if (to) map.flyTo(to, Math.max(map.getZoom(), 9), { duration: 0.7 }); }, [to?.[0], to?.[1]]);
  return null;
}
function Tiles({ sat }) {
  const [i, setI] = useState(0); const errs = useRef(0);
  const onErr = () => { if (++errs.current >= 4 && i < STREET.length - 1) { errs.current = 0; setI(i + 1); } };
  return <>{sat ? <TileLayer attribution="&copy; Esri" url={SAT} /> : <TileLayer key={i} attribution={STREET[i].a} url={STREET[i].u} eventHandlers={{ tileerror: onErr, tileload: () => { errs.current = 0; } }} />}
    {sat && <TileLayer url={LABELS} />}</>;
}

function Resource({ a, src }) {
  const [open, setOpen] = useState(false);
  const Icon = /biomass|straw|pellet|power|plant|recycl|bio|brick/i.test(a.type) ? Recycle : Tractor;
  return (
    <li className="iv2res"><span className="resico"><Icon size={18} /></span>
      <div><b>{a.name}</b><small>{a.type}{a.registered ? " (registered on NabhoNetra)" : ""}</small><small>{a.km} km away</small>
        {open && <div className="resmore"><span>Contact: <b>{a.contact || "not listed"}</b></span><small>{a.registered ? "Registered and agreed to be listed." : src === "OpenStreetMap" ? "OpenStreetMap listing. Availability is not verified." : "Sample listing."}</small></div>}</div>
      <button type="button" className="btn sm" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? "Hide" : "View"}</button></li>);
}

export default function Interventions({ data, me, isAdmin, flash, focus, onJoin, onSignIn, children }) {
  const [list, setList] = useState(null); const [mine, setMine] = useState({}); const [sel, setSel] = useState(focus || null); const [filter, setFilter] = useState("all"); const [sat, setSat] = useState(false);
  const load = () => api("/api/interventions").then((r) => setList(Array.isArray(r) ? r : [])).catch(() => setList((l) => l || []));
  const loadMine = () => (me ? api("/api/me/interventions").then((r) => setMine(Object.fromEntries(r.map((x) => [x.id, x])))).catch(() => setMine({})) : setMine({}));
  const reload = () => { load(); loadMine(); };
  useEffect(() => { load(); }, [data?.updated]);
  useEffect(() => { loadMine(); setFilter(me ? "mine" : "all"); }, [me?.name, me?.role]);

  const items = useMemo(() => buildItems(list, data?.clusters), [list, data]);
  const shown = items.filter((x) => filter === "all" || (filter === "mine" ? mine[x.key] : x.c.priority === filter));
  const cur = shown.find((x) => x.key === sel) || shown[0] || null;
  useEffect(() => { if (cur && cur.key !== sel) setSel(cur.key); }, [cur?.key]);
  useEffect(() => { if (cur) history.replaceState(null, "", "#/interventions/" + cur.key); }, [cur?.key]);
  const pts = shown.map((x) => [x.c.lat, x.c.lon]);
  const c = cur?.c, iv = cur?.iv, st = stageOf(iv), res = c?.alert?.alternatives || [], reg = iv?.analysis?.registry;
  const todo = Object.values(mine).filter((m) => m.act).length;
  const t = c ? where(c) : null;

  return (
    <div className="iv2">
      <div className="iv2head"><span className="iv2logo"><Sprout size={26} /></span>
        <div><h1>Interventions</h1><p>From detection to real-world action: helping farmers choose safer, greener alternatives to stubble burning.</p></div>
        <div className="iv2who">{me ? <Badge tone="ok">Signed in: {ROLE_LABEL[me.role]}</Badge> : <Badge tone="muted">Public view</Badge>}
          {me && todo > 0 && <Badge tone="warn">{todo} need{todo === 1 ? "s" : ""} your action</Badge>}{children}</div></div>

      <ol className="iv2how" aria-label="How NabhoNetra works">{HOW.map(([I, h, p], n) => <li key={h}><span className="howico"><I size={18} /></span><div><b>{n + 1}. {h}</b><small>{p}</small></div></li>)}</ol>

      {list === null ? <div className="card"><p className="muted">Loading interventions</p></div> : !items.length ?
        <div className="card empty"><p>No fire detections in the latest data{data?.mock ? " (sample data mode)" : ""}, so there is nothing to act on right now.</p><a className="btn" href="#/map">Open the live map</a></div> : (
        <div className="iv2grid">
          <aside className="card iv2list">
            <div className="cardhead"><h2>Recent intervention alerts</h2></div>
            <p className="iv2live"><i className={data?.mock ? "mock" : ""} />{data?.mock ? "Sample data (test mode)" : "Live data"}{data?.updated ? <small> Updated {fmtTime(data.updated)}</small> : null}</p>
            <div className="chips">{[...(me ? [["mine", "For me"]] : []), ["all", "All"], ["high", "High"], ["medium", "Medium"], ["low", "Low"]].map(([k, l]) => <button key={k} className={filter === k ? "on" : ""} onClick={() => setFilter(k)}>{l}</button>)}</div>
            <ul className="list">
              {shown.map((x) => { const p = where(x.c); return (
                <li key={x.key}><button className={"iv2row" + (x.key === cur?.key ? " on" : "")} onClick={() => setSel(x.key)}>
                  <MapPin size={16} style={{ color: COLORS[x.c.priority] }} /><span className="txt"><b>{p.title}</b><small>{p.sub}</small><small>{fmtTime(x.c.last_detected)} · {x.c.fires} detections</small>
                    {mine[x.key] && <small className="why">{mine[x.key].why}</small>}</span>
                  <span className="rt"><Badge tone={x.c.priority}>{LABEL[x.c.priority]}</Badge>{mine[x.key]?.act && <Badge tone="warn">Action</Badge>}</span></button></li>); })}
              {!shown.length && <li className="none">{filter === "mine" ? <>Nothing needs you right now. <button type="button" className="linkbtn" onClick={() => setFilter("all")}>Show all alerts</button></> : "No alerts at this priority."}</li>}
            </ul>
            <a className="link" href="#/map">View all detections <ArrowRight size={14} /></a>
          </aside>

          <main className="iv2map">
            <MapContainer center={pts[0] || [22.9, 79]} zoom={7} scrollWheelZoom zoomControl={false}>
              <ZoomControl position="bottomright" /><Tiles sat={sat} /><Fit points={pts} /><Fly to={c ? [c.lat, c.lon] : null} />
              {shown.map((x) => { const on = x.key === cur?.key; return (
                <CircleMarker key={x.key} center={[x.c.lat, x.c.lon]} radius={on ? 10 + Math.sqrt(x.c.fires) * 2 : 6 + Math.sqrt(x.c.fires) * 1.6}
                  pathOptions={{ color: COLORS[x.c.priority], fillColor: COLORS[x.c.priority], fillOpacity: on ? 0.9 : 0.55, weight: on ? 3 : 1 }} eventHandlers={{ click: () => setSel(x.key) }}>
                  <Tooltip permanent={on} direction="top">{where(x.c).title}{on ? ` · ${LABEL[x.c.priority]} priority` : ""}</Tooltip></CircleMarker>); })}
              {shown.filter((x) => x.c.wind_from != null).map((x) => <Marker key={"w" + x.key} position={[x.c.lat, x.c.lon]} icon={windIcon(x.c.wind_from)} interactive={false} />)}
            </MapContainer>
            <div className="seg"><button className={!sat ? "on" : ""} onClick={() => setSat(false)}>Map</button><button className={sat ? "on" : ""} onClick={() => setSat(true)}>Satellite</button></div>
            {c?.wind_speed != null && <div className="windcard"><small>Wind</small><Navigation size={20} style={{ transform: `rotate(${((c.wind_from + 180) % 360) - 45}deg)` }} aria-hidden="true" /><b>{c.wind_speed} km/h</b><small>from {compass(c.wind_from)}</small></div>}
            <div className="legend"><span><i style={{ background: COLORS.high }} />High priority</span><span><i style={{ background: COLORS.medium }} />Medium</span><span><i style={{ background: COLORS.low }} />Low</span><span><Wind size={13} /> Arrow = wind direction</span></div>
          </main>

          <aside className="card iv2detail">{c && (<>
            <div className="iv2dhead"><MapPin size={20} style={{ color: COLORS[c.priority] }} /><div><h2>{t.title}</h2><small>{t.sub}</small></div>
              <span className="rt">{iv?.demo ? <Badge tone="muted">Demo record</Badge> : data?.mock ? <Badge tone="muted">Sample data</Badge> : <Badge tone="ok">Live</Badge>}<Badge tone={c.priority}>{LABEL[c.priority]} priority</Badge></span></div>
            <p className="fine"><Info size={12} /> {fmtTime(c.last_detected)} · {c.fires} satellite detections{iv ? ` · ${STATUS[iv.status]}` : ""}</p>

            <h3><Sparkles size={13} /> AI recommendation</h3>
            <div className="iv2ai">{c.alert?.text || iv?.plan?.[0] || "No recommendation has been written for this cluster yet."}</div>{c.alert && <small className="fine">{sourceLine(c)}</small>}

            <h3>What we know</h3>
            <p className="kv"><b>Observed by satellite:</b> {c.fires} fires, latest {fmtTime(c.last_detected)}{iv ? `. Burning seen on ${iv.analysis.observed.days_with_fire_7d} of the last 7 days.` : "."}</p>
            <p className="kv"><b>Estimated risk:</b> {smokeLine(c).replace("Forecast: ", "")}.</p>
            {iv?.analysis?.barriers?.length > 0 && <><h3>Why help is needed</h3><ul className="bul">{iv.analysis.barriers.map((b) => <li key={b.code}>{b.text}</li>)}</ul></>}
            {iv?.plan?.length > 0 && <><h3>Next steps</h3><ul className="bul">{iv.plan.map((s) => <li key={s}>{s}</li>)}</ul></>}
            {reg && <p className="fine">Registered within range: {reg.farmers} farmer{reg.farmers === 1 ? "" : "s"}{reg.acres != null ? ` (${reg.acres} acres)` : ""}, {reg.providers} machine providers, {reg.buyers} biomass buyers.</p>}

            <h3>Suggested resources</h3>
            {res.length ? <ul>{res.slice(0, 3).map((a) => <Resource key={a.name + a.km} a={a} src={data?.alternatives_source} />)}</ul> : <p className="fine">No listed machinery or biomass facility found near this cluster.</p>}

            <h3>Intervention timeline</h3>
            <ol className="iv2tl">{STAGES.map((s, n) => <li key={s} className={n < st.done ? "done" : n === st.done ? "now" : ""}><span>{n < st.done ? "✓" : n + 1}</span><small>{s}</small>
              {n === 0 && <small className="d">{new Date(iv?.created || c.first_detected || c.last_detected).toLocaleDateString("en-IN", { day: "2-digit", month: "short" })}</small>}</li>)}</ol>
            <p className="fine">{st.note}</p>

            <RolePanel item={cur} me={me} flash={flash} reload={reload} onJoin={onJoin} onSignIn={onSignIn} />
          </>)}</aside>
        </div>)}
    </div>);
}
