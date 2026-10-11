import { useEffect, useState } from "react";
import { api } from "./api.js";
import { Badge } from "./ui.jsx";
import { placeOf, fmtTime } from "./shared.js";

export default function Respond({ token }) {
  const [d, setD] = useState(null); const [err, setErr] = useState(""); const [note, setNote] = useState(""); const [msg, setMsg] = useState(""); const [file, setFile] = useState(null);
  const load = () => api("/api/respond/" + token).then((r) => { setD(r); setErr(""); }).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, [token]);
  const act = (action) => api("/api/respond/" + token, { method: "POST", body: JSON.stringify({ action, note }) })
    .then(() => { setMsg(action === "complete" ? "Thank you. An officer will check the outcome." : action === "accept" ? "Thank you. You can now see the farmers who chose you." : "Noted. Thank you for replying."); load(); }).catch((e) => setMsg(e.message));
  const upload = async () => {
    if (!file) return;
    const fd = new FormData(); fd.append("file", file);
    const r = await fetch(`/api/respond/${token}/evidence`, { method: "POST", body: fd }); const j = await r.json().catch(() => ({}));
    setMsg(r.ok ? "Photo added as evidence." : j.detail || "Could not upload the photo."); setFile(null);
  };
  if (err) return <section className="page narrow"><div className="card"><h2>This link cannot be used</h2><p className="muted">{err}</p></div></section>;
  if (!d) return <section className="page narrow"><p className="muted">Loading</p></section>;
  const c = d.cluster, r = d.demand;
  return (
    <section className="page narrow">
      <div className="card respond">
        <div className="cardhead"><h2>Request for {d.name}</h2><Badge tone={d.status === "completed" ? "ok" : "warn"}>{d.status}</Badge></div>
        <p><b>{c.fires} crop fires</b> near {placeOf(c)}, latest {fmtTime(c.last_detected)}. {d.estimated.eta_hours ? `Smoke may reach the city in about ${d.estimated.eta_hours} h (forecast).` : ""}</p>
        <p>{r.farmers} registered farmers ({r.acres} acres) in range may need: {Object.keys(r.needs).join(", ") || "any help"}. You were matched for: {(d.offers || []).join(", ")}.</p>
        {["asked", "suggested"].includes(d.status) && d.jobs?.length > 0 && <><h3>Farmers who chose you</h3><p className="fine">Their names and contact details appear after you accept.</p>
          <ul className="leads">{d.jobs.map((j) => <li key={j.rid}>{j.land_acres} acres of {j.crop}, needs {j.needs.join(", ") || "help"}<small>{[j.area?.district, j.area?.state].filter(Boolean).join(", ")}, about {j.approx_km} km from you{j.note ? `. "${j.note}"` : ""}</small></li>)}</ul></>}
        {["asked", "suggested"].includes(d.status) && <div className="btnrow"><button className="btn primary" onClick={() => act("accept")}>Accept</button><button className="btn" onClick={() => act("decline")}>Decline</button></div>}
        {["accepted", "completed"].includes(d.status) && <>
          <h3>Farmers who chose you</h3>
          {d.leads.length ? <ul className="leads">{d.leads.map((l) => <li key={l.contact}><b>{l.name}</b> {l.contact}<small>{l.land_acres} acres, {l.crop}{l.needs?.length ? `, needs ${l.needs.join(", ")}` : ""}. {[l.area?.village, l.area?.district, l.area?.state].filter(Boolean).join(", ")}{l.lat != null && <> <a href={`https://www.openstreetmap.org/?mlat=${l.lat}&mlon=${l.lon}#map=16/${l.lat}/${l.lon}`} target="_blank" rel="noreferrer">Exact location</a></>}</small></li>)}</ul> : <p className="muted">None yet.</p>}
          {d.leads_not_shared > 0 && <p className="fine">{d.leads_not_shared} other registered farmer(s) in range have not chosen you. Their details stay private.</p>}
          {d.status === "accepted" && <>
            <h3>When the work is done</h3>
            <label className="field">What was done? (at least 10 characters)<input value={note} onChange={(e) => setNote(e.target.value)} maxLength="500" /></label>
            <label className="field">Photo evidence (optional, JPEG or PNG, up to 5 MB)<input type="file" accept="image/jpeg,image/png" onChange={(e) => setFile(e.target.files[0])} /></label>
            <div className="btnrow">{file && <button className="btn" onClick={upload}>Upload photo</button>}<button className="btn primary" onClick={() => act("complete")}>Mark as completed</button></div></>}
        </>}
        {msg && <p className="fmsg ok" role="status">{msg}</p>}
        <p className="fine">Results only count once an officer has verified them.</p>
      </div>
    </section>);
}
