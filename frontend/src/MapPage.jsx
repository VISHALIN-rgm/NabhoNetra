import { Fragment, useEffect, useRef, useState } from "react";
import { MapContainer, TileLayer, CircleMarker, Marker, Polyline, Tooltip, useMap } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { Send, Copy, CheckCircle2, MapPin, Wind, Flame, Ruler } from "lucide-react";
import { COLORS, LABEL, riskOf, reasonsOf, compass , cityOf, placeOf, fmtTime , smokeLine, nearbyLine, sourceLine } from "./shared.js";
import { Badge, Ring } from "./ui.jsx";

const windIcon = (from) => L.divIcon({ className: "wind", iconSize: [20, 20], html: `<div style="transform:rotate(${(from + 180) % 360 - 90}deg)">&#10148;</div>` });
const cityIcon = L.divIcon({ className: "city", iconSize: [14, 14] });
const ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/";
const PROVIDERS = [
  { u: ESRI + "World_Street_Map/MapServer/tile/{z}/{y}/{x}", a: "&copy; Esri" },
  { u: ESRI + "World_Topo_Map/MapServer/tile/{z}/{y}/{x}", a: "&copy; Esri" },
  { u: "https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png", a: "&copy; OpenStreetMap &copy; CARTO" },
];
const SAT = ESRI + "World_Imagery/MapServer/tile/{z}/{y}/{x}";
const LABELS = ESRI + "Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}";
function Fly({ to }) {
  const map = useMap(); const first = useRef(true);
  const lat = to?.[0], lon = to?.[1];
  useEffect(() => { if (first.current) { first.current = false; return; } if (lat != null && lon != null) map.flyTo([lat, lon], Math.max(map.getZoom(), 8), { duration: 0.8 }); }, [lat, lon]);
  return null;
}
function Fit({ points }) {
  const map = useMap();
  useEffect(() => {
    const fit = () => { map.invalidateSize(); if (points.length) map.fitBounds(L.latLngBounds(points).pad(0.25), { animate: false }); };
    fit(); const t = setTimeout(fit, 300);
    return () => clearTimeout(t);
  }, []);
  return null;
}

export default function MapPage({ data, sel, setSel, isSent, send, copy, max }) {
  const [filter, setFilter] = useState("all");
  const [base, setBase] = useState("map");
  const [pi, setPi] = useState(0);
  const errs = useRef(0);
  const [noTiles, setNoTiles] = useState(false);
  const onErr = () => {
    errs.current++;
    if (errs.current < 4) return;
    errs.current = 0;
    if (base === "map" && pi < PROVIDERS.length - 1) setPi(pi + 1); else setNoTiles(true);
  };
  const onLoad = () => { errs.current = 0; if (noTiles) setNoTiles(false); };
  const india = data.scope === "india";
  const pts = india && data.clusters.length ? data.clusters.map((c) => [c.lat, c.lon]) : [...data.clusters.map((c) => [c.lat, c.lon]), [data.city.lat, data.city.lon]];
  const tgt = (c) => (india ? [c.city_lat, c.city_lon] : [data.city.lat, data.city.lon]);
  const cities = india ? [...new Map(data.clusters.filter((c) => c.priority !== "low" && c.city_name).map((c) => [c.city_name, c])).values()] : [];
  const list = data.clusters.filter((c) => filter === "all" || c.priority === filter);
  const cur = data.clusters.find((c) => c.id === sel);
  const best = cur?.alert.alternatives?.[0];
  const mid = pts.reduce((s, p) => [s[0] + p[0] / pts.length, s[1] + p[1] / pts.length], [0, 0]);

  return (
    <div className="mapgrid">
      <aside className="card panel">
        <div className="chips">{["all", "high", "medium", "low"].map((f) => <button key={f} className={filter === f ? "on" : ""} onClick={() => setFilter(f)}>{f === "all" ? "All" : LABEL[f]}</button>)}</div>
        <ul className="list">
          {list.map((c) => (
            <li key={c.id}><button className={c.id === sel ? "row on" : "row"} onClick={() => setSel(c.id)}>
              <span className="dot" style={{ background: COLORS[c.priority] }} />
              <span className="txt"><b>{c.id}</b><small>{c.fires} fires, {placeOf(c)}</small>
                <span className="bar"><span style={{ width: `${(c.score / max) * 100}%`, background: COLORS[c.priority] }} /></span></span>
              <Badge tone={isSent(c) ? "ok" : "warn"}>{isSent(c) ? "Sent" : "Pending"}</Badge>
            </button></li>))}
          {!list.length && <li className="none">No clusters at this priority.</li>}
        </ul>
      </aside>

      <main className="mapwrap">
        <MapContainer center={india && !data.clusters.length ? [22.9, 79.0] : mid} zoom={india ? 5 : 7} scrollWheelZoom>
          <TileLayer key={base + pi} attribution={base === "sat" ? "&copy; Esri" : PROVIDERS[pi].a} url={base === "sat" ? SAT : PROVIDERS[pi].u} eventHandlers={{ tileerror: onErr, tileload: onLoad }} />
          {base === "sat" && <TileLayer url={LABELS} />}
          <Fit points={pts} />
          <Fly to={cur ? [cur.lat, cur.lon] : null} />
          {!india && <Marker position={[data.city.lat, data.city.lon]} icon={cityIcon}><Tooltip permanent direction="right">Target city</Tooltip></Marker>}
          {cities.map((c) => <Marker key={c.city_name} position={[c.city_lat, c.city_lon]} icon={cityIcon}><Tooltip direction="right">{c.city_name}</Tooltip></Marker>)}
          {data.clusters.filter((c) => c.priority !== "low").map((c) => (
            <Polyline key={"t" + c.id} positions={[[c.lat, c.lon], tgt(c)]}
              pathOptions={{ color: COLORS[c.priority], dashArray: "2 9", lineCap: "round", weight: 1 + (c.score / max) * 4, opacity: c.id === sel ? 0.95 : 0.4 }} />))}
          {data.clusters.map((c) => (
            <Fragment key={c.id}>
              <CircleMarker center={[c.lat, c.lon]} radius={6 + Math.sqrt(c.fires) * 2.2}
                pathOptions={{ color: COLORS[c.priority], fillColor: COLORS[c.priority], fillOpacity: c.id === sel ? 0.85 : 0.5, weight: c.id === sel ? 3 : 1 }}
                eventHandlers={{ click: () => setSel(c.id) }}><Tooltip>{c.id}: {c.fires} fires</Tooltip></CircleMarker>
              <Marker position={[c.lat, c.lon]} icon={windIcon(c.wind_from)} interactive={false} />
            </Fragment>))}
        </MapContainer>
        {noTiles && <div className="tilewarn">Map background could not load (no connection to the tile server, or it is blocked). Fire markers and smoke paths still work. Try the {base === "map" ? "Satellite" : "Map"} view, or check your connection and ad-blocker.</div>}
        <div className="seg"><button className={base === "map" ? "on" : ""} onClick={() => setBase("map")}>Map</button><button className={base === "sat" ? "on" : ""} onClick={() => setBase("sat")}>Satellite</button></div>
        <div className="legend"><b>Smoke paths to city</b>
          {["high", "medium", "low"].map((p) => <span key={p}><i style={{ borderColor: COLORS[p] }} />{LABEL[p]} priority</span>)}
          <small>Arrows show wind heading. Dot size shows fire count.</small></div>
      </main>

      <aside className="card detail">
        {cur && (<>
          <div className="dhead">
            <div><Badge tone={cur.priority}>{LABEL[cur.priority]} priority</Badge><h2>Cluster {cur.id}</h2>
              <small className="muted"><MapPin size={13} /> {placeOf(cur)} ({cur.lat.toFixed(3)}, {cur.lon.toFixed(3)})</small>
              <small className="muted">Latest detection: {fmtTime(cur.last_detected)}</small><small className="muted">First detection: {fmtTime(cur.first_detected)}</small>
              <small className="muted">{smokeLine(cur)}</small><small className="muted">{nearbyLine(cur)}</small></div>
            <Ring v={riskOf(cur, max)} color={COLORS[cur.priority]} />
          </div>
          <div className="mgrid">
            <div><Flame size={15} /><b>{cur.fires}</b><small>fires</small></div>
            <div><Ruler size={15} /><b>{cur.distance_km} km</b><small>to {india ? cityOf(cur) : "city"}</small></div>
            <div><Wind size={15} /><b>{cur.wind_speed} km/h</b><small>from {compass(cur.wind_from)}</small></div>
          </div>
          <h3>Why it matters</h3>
          <ul className="why">{reasonsOf(cur).map((r) => <li key={r}>{r}</li>)}</ul>
          <h3>Message to subscribers</h3>
          <div className="bubble">{cur.alert.text || "No alert written yet."}</div><small className="fine">{sourceLine(cur)}</small>
          <div className="btnrow">
            <button className="btn primary adminonly" disabled={isSent(cur)} onClick={() => send(cur.id)}>{isSent(cur) ? <><CheckCircle2 size={16} /> Alert sent</> : <><Send size={16} /> Send alert</>}</button>
            <button className="btn" onClick={() => copy(cur.alert.text)}><Copy size={16} /> Copy</button>
          </div>
          {best && <div className="reco"><b>Nearest alternative to burning</b><span>{best.type}: {best.name}</span><small>{best.km} km away, {best.contact}</small>
            <small>{data.alternatives_source === "OpenStreetMap" ? "OpenStreetMap listing, availability not verified." : "Sample data."}</small></div>}
          <p className="fine">Risk index is an estimate from wind direction, distance and fire count, not a measured share of city AQI.</p>
        </>)}
      </aside>
    </div>
  );
}
