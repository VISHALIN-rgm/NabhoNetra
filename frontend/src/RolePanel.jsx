import { useEffect, useState } from "react";
import { Send, BadgeCheck, Image as ImageIcon, UserPlus, LogIn, Lock, MapPinOff } from "lucide-react";
import { Badge } from "./ui.jsx";
import { api, apiBlob, getSession, API } from "./api.js";
import { fmtTime } from "./shared.js";
import { ROLE_LABEL, RQ_LABEL, RQ_STEPS, rqDone, NEED_LABEL } from "./ivutil.js";

function Photo({ iid, name }) {
  const [src, setSrc] = useState("");
  return src ? <img className="evphoto" src={src} alt="Evidence photo" /> :
    <button type="button" className="btn sm" onClick={() => apiBlob(`/api/evidence/${iid}/${name}`).then(setSrc).catch(() => {})}><ImageIcon size={14} /> Show photo</button>;
}

const MSTATUS = { suggested: "Suggested", asked: "Asked", accepted: "Accepted", declined: "Declined", completed: "Reported done", verified: "Verified", rejected: "Not accepted" };
const OPEN_STATES = ["open", "proposed", "provider_declined"];
const place = (a) => [a?.village, a?.district, a?.state].filter(Boolean).join(", ");

function Steps({ done }) {
  return <ol className="rqsteps">{RQ_STEPS.map((s, n) => <li key={s} className={n < done ? "done" : n === done ? "now" : ""}><span>{n < done ? "✓" : n + 1}</span><small>{s}</small></li>)}</ol>;
}

/** One of the farmer's own requests: its stage, the proposed solutions to choose from, and what happened. */
function MyRequest({ r, act, busy }) {
  const [loc, setLoc] = useState(false);
  const closed = ["withdrawn", "verified", "rejected"].includes(r.status);
  return (
    <div className="rqcard">
      <div className="rqhead"><b>{RQ_LABEL[r.status]}</b><small>{fmtTime(r.created)}</small></div>
      <p className="fine">{r.needs.length ? "You asked for: " + r.needs.map((n) => NEED_LABEL[n] || n).join(", ") : "General help"}{r.note ? `. "${r.note}"` : ""}</p>
      <Steps done={rqDone(r.status)} />
      {r.proposals.length > 0 && <ul className="proposals">{r.proposals.map((p) => (
        <li key={p.sid}><div><b>{p.name}</b> <Badge tone="muted">{p.role === "machine_provider" ? "Machine provider" : "Biomass buyer"}</Badge>
          <small>{p.km} km from you{p.offers?.length ? `, offers ${p.offers.join(", ")}` : ""}{p.materials?.length ? `, takes ${p.materials.join(", ")}` : ""}</small>
          <small>{p.contact ? `Contact: ${p.contact}` : "Contact appears once they take the job."}</small>
          {p.status !== "proposed" && <small><Badge tone={p.status === "accepted" ? "ok" : "muted"}>{{ accepted: "You chose them", declined: "You turned this down", declined_by_provider: "They declined", unavailable: "No longer available" }[p.status] || p.status}</Badge></small>}</div>
          {p.status === "proposed" && OPEN_STATES.includes(r.status) && <div className="rqbtns"><button className="btn sm primary" disabled={busy} onClick={() => act("accept", r.rid, { sid: p.sid, share_location: loc }, "Chosen. Only this provider can now see your details.")}>Choose</button>
            <button className="btn sm" disabled={busy} onClick={() => act("decline", r.rid, { sid: p.sid }, "Option removed.")}>Not this one</button></div>}</li>))}</ul>}
      {r.proposals.some((p) => p.status === "proposed") && OPEN_STATES.includes(r.status) && <label className="check"><input type="checkbox" checked={loc} onChange={(e) => setLoc(e.target.checked)} />
        Also share my exact location with the one I choose (optional; otherwise only my village and district)</label>}
      {r.status === "open" && !r.proposals.length && <p className="fine">No registered provider or buyer covers your location yet. Officers in your area can see your request and will look for one. You can also use the listed resources above.</p>}
      {r.outcome && <p className="fine">Provider's report: {r.outcome.note}{r.outcome.decision_note ? ` Officer's note: ${r.outcome.decision_note}` : ""}</p>}
      {!closed && <div className="btnrow"><button className="btn sm" disabled={busy} onClick={() => act("withdraw", r.rid, null, "Request withdrawn. Nobody can see your details for it now.")}><MapPinOff size={13} /> Withdraw request</button></div>}
    </div>);
}

/** The part of the detail panel that depends on who is looking: visitor, farmer, provider, buyer, officer, or administrator. */
export default function RolePanel({ item, me, flash, reload, onJoin, onSignIn }) {
  const iv = item.iv;
  const [d, setD] = useState(null); const [err, setErr] = useState(""); const [note, setNote] = useState(""); const [file, setFile] = useState(null);
  const [notes, setNotes] = useState({}); const [needs, setNeeds] = useState([]); const [rnote, setRnote] = useState("");
  const [links, setLinks] = useState([]); const [busy, setBusy] = useState(false);
  const who = me ? me.role : "public";

  const load = () => {
    if (!iv || who === "public") { setD(null); return; }
    api(`/api/interventions/${iv.id}/role`).then((x) => { setD(x); setErr(""); }).catch((e) => setErr(e.message));
  };
  useEffect(() => { setD(null); setNote(""); setNotes({}); setFile(null); setLinks([]); setErr(""); setRnote(""); load(); }, [iv?.id, iv?.updated, iv?.status, who, me?.name]);
  useEffect(() => { if (d?.needs_default) setNeeds(d.needs_default); }, [d?.needs_default?.join()]);

  const run = async (fn, ok) => {
    setBusy(true);
    try { const r = await fn(); flash(typeof ok === "function" ? ok(r) : ok); setNote(""); setFile(null); reload(); load(); }
    catch (e) { flash(e.message); } finally { setBusy(false); }
  };
  const post = (path, body) => api(`/api/interventions/${iv.id}/${path}`, { method: "POST", ...(body ? { body: JSON.stringify(body) } : {}) });
  const act = (action) => run(() => post("act", { action, note }),
    action === "accept" ? "Accepted. You can now see the farmers who chose you." : action === "decline" ? "Noted. Thank you for replying." : "Thank you. An officer will check the outcome.");
  const upload = () => run(async () => {
    const fd = new FormData(); fd.append("file", file);
    const r = await fetch(`${API}/api/interventions/${iv.id}/evidence`, { method: "POST", body: fd, headers: { "x-session": getSession() } });
    const j = await r.json().catch(() => ({})); if (!r.ok) throw new Error(j.detail || "Could not upload the photo."); return j;
  }, "Photo added as evidence.");
  const coordinate = () => run(() => post("coordinate"), (r) => { setLinks(r.links || []); return r.asked ? `Requests sent to ${r.asked} matched part${r.asked > 1 ? "ies" : "y"}` : "Nobody consenting could be asked yet"; });
  const verify = (sid, approve) => run(() => post("verify", { approve, note: notes[sid] || "", sid }), approve ? "Marked as verified" : "Marked as not accepted");
  const rqAct = (what, rid, body, ok) => run(() => post(`requests/${rid}/${what}`, body), ok);
  const askHelp = () => run(() => post("requests", { needs, note: rnote }), "Request sent. Review the options below.");
  const refreshOptions = (rid) => run(() => post(`requests/${rid}/propose`), (r) => r.added ? `${r.added} new option(s) added` : "No new options yet");

  if (who === "public") return (
    <div className="iv2cta">
      <button type="button" className="btn primary wide" onClick={onJoin}><UserPlus size={16} /> Join NabhoNetra to take action</button>
      <p className="fine">Farmers can ask for help and choose a solution. Providers and buyers answer requests. Officers verify outcomes. Already joined? <button type="button" className="linkbtn" onClick={onSignIn}><LogIn size={13} /> Sign in</button></p>
    </div>);

  const head = <div className="iv2role"><span><Lock size={14} /> Your view: <b>{ROLE_LABEL[who]}</b></span></div>;
  if (!iv) return <div className="iv2rolebox">{head}<p className="fine">No intervention is open for this cluster yet. One opens automatically for each high and medium priority cluster after a data refresh.</p></div>;
  if (err) return <div className="iv2rolebox">{head}<p className="fine">{err}</p></div>;
  if (!d) return <div className="iv2rolebox">{head}<p className="fine">Loading</p></div>;

  if (d.role === "farmer") return (
    <div className="iv2rolebox">{head}
      {!d.in_range && <p>This cluster is outside your {me.radius_km} km alert area, so you cannot request help here.</p>}
      {d.in_range && <p className="fine">{d.km} km from your registered location. Please do not burn.</p>}
      {d.requests.length > 0 && <><h4>Your requests</h4>{d.requests.map((r) => <MyRequest key={r.rid} r={r} act={rqAct} busy={busy} />)}</>}
      {d.can_request && <><h4>Ask for help</h4>
        <div className="needs">{Object.entries(NEED_LABEL).map(([k, t]) => <label key={k} className="check"><input type="checkbox" checked={needs.includes(k)} onChange={(e) => setNeeds(e.target.checked ? [...needs, k] : needs.filter((x) => x !== k))} /> {t}</label>)}</div>
        <label className="field">Anything the provider should know (optional)<input value={rnote} onChange={(e) => setRnote(e.target.value)} maxLength="200" placeholder="For example: 8 acres, harvest finished" /></label>
        <div className="btnrow"><button className="btn primary" disabled={busy} onClick={askHelp}>Request help</button></div>
        <p className="fine">Nothing about you is shared when you ask. You see proposed options first, and only the one you choose can see your details.</p></>}
    </div>);

  if (d.role === "machine_provider" || d.role === "biomass_buyer") {
    const m = d.mine;
    if (!m) return <div className="iv2rolebox">{head}<p>{d.in_range ? "This is inside your service range, but no request has been matched to you yet. You will get a message if one is." : "This is outside your service range."}</p></div>;
    const open = ["asked", "suggested"].includes(m.status);
    return (
      <div className="iv2rolebox">{head}
        <p>You were matched for: <b>{(m.offers || m.materials || []).join(", ") || "this cluster"}</b> ({m.km} km away). Your status: <Badge tone={["completed", "verified"].includes(m.status) ? "ok" : "warn"}>{MSTATUS[m.status] || m.status}</Badge></p>
        {open && d.jobs.length > 0 && <><h4>Farmers who chose you</h4><ul className="leads">{d.jobs.map((j) => <li key={j.rid}>{j.land_acres} acres of {j.crop}, needs {j.needs.join(", ") || "help"}<small>{[j.area?.district, j.area?.state].filter(Boolean).join(", ")}, about {j.approx_km} km from you{j.note ? `. "${j.note}"` : ""}</small></li>)}</ul><p className="fine">Names and contact details appear after you accept.</p></>}
        {open && <div className="btnrow"><button className="btn primary" disabled={busy} onClick={() => act("accept")}>Accept</button><button className="btn" disabled={busy} onClick={() => act("decline")}>Decline</button></div>}
        {["accepted", "completed", "verified"].includes(m.status) && <>
          <h4>Farmers who chose you</h4>
          {d.leads.length ? <ul className="leads">{d.leads.map((l) => <li key={l.contact}><b>{l.name}</b> {l.contact}<small>{l.land_acres} acres, {l.crop}{l.needs?.length ? `, needs ${l.needs.join(", ")}` : ""}. {place(l.area)}{l.lat != null && <> <a href={`https://www.openstreetmap.org/?mlat=${l.lat}&mlon=${l.lon}#map=16/${l.lat}/${l.lon}`} target="_blank" rel="noreferrer">Exact location</a></>}</small></li>)}</ul> : <p className="fine">None right now. If a farmer withdraws, their details disappear here.</p>}
          {d.leads_not_shared > 0 && <p className="fine">{d.leads_not_shared} other registered farmer(s) in range have not chosen you. Their details stay private.</p>}
          {m.status === "accepted" && <>
            <label className="field">What was done? (at least 10 characters)<input value={note} onChange={(e) => setNote(e.target.value)} maxLength="500" /></label>
            <label className="field">Photo evidence (optional, JPEG or PNG, up to 5 MB)<input type="file" accept="image/jpeg,image/png" onChange={(e) => setFile(e.target.files[0])} /></label>
            <div className="btnrow">{file && <button className="btn" disabled={busy} onClick={upload}>Upload photo</button>}<button className="btn primary" disabled={busy || note.trim().length < 10} onClick={() => act("complete")}>Report work as done</button></div>
            <p className="fine">Reporting is a claim. It only counts as a result after an officer reviews your evidence and verifies it.</p></>}
          {m.status === "completed" && <p className="fine">Reported. An officer will review it. It counts as a result only after they verify it.</p>}
          {m.status === "verified" && <p className="fine">An officer verified your work.</p>}
        </>}
      </div>);
  }

  // officer (their area) or administrator
  if (d.covered === false) return <div className="iv2rolebox">{head}<p>This intervention is outside your assigned area, so you can see that it exists but not the people or evidence in it.</p></div>;
  const canSend = ["open", "coordinating"].includes(iv.status) && d.matches?.length > 0;
  return (
    <div className="iv2rolebox">{head}
      {links.length > 0 && <div className="staffbox"><b>Test mode: response links (nothing was sent)</b><ul>{links.map((l) => <li key={l.url}><a href={l.url}>Open the page {l.name} would see</a></li>)}</ul></div>}
      <h4>Farmer requests</h4>
      {d.requests?.length ? <ul className="matchlist">{d.requests.map((r) => <li key={r.rid}><b>{r.farmer.name}</b> {r.farmer.contact} <Badge tone="muted">{RQ_LABEL[r.status]}</Badge>
        <small>{r.farmer.land_acres} acres of {r.farmer.crop}, {place(r.farmer.area) || "area not given"}. Asked for {r.needs.map((n) => NEED_LABEL[n] || n).join(", ") || "general help"}{r.note ? `. "${r.note}"` : ""}. {r.proposals.length} option(s) proposed.</small>
        {["open", "proposed"].includes(r.status) && <button type="button" className="btn sm" disabled={busy} onClick={() => refreshOptions(r.rid)}>Look for more options</button>}</li>)}</ul> : <p className="fine">No farmer has asked for help here yet.</p>}
      <h4>Matched parties</h4>
      {d.matches?.length ? <ul className="matchlist">{d.matches.map((m) => <li key={m.sid}><b>{m.name}</b> <small>{m.role.replace("_", " ")}, {m.km} km, {MSTATUS[m.status] || m.status}{m.contact ? `, ${m.contact}` : ""}</small></li>)}</ul> : <p className="fine">Nobody registered in range has been matched yet.</p>}
      {canSend && <div className="btnrow"><button className="btn primary" disabled={busy} onClick={coordinate}><Send size={14} /> Send requests</button></div>}
      <h4>Completion claims</h4>
      {d.claims?.length ? d.claims.map((c) => (
        <div className="rqcard" key={c.sid}>
          <div className="rqhead"><b>{c.name}</b><Badge tone={c.status === "verified" ? "ok" : c.status === "rejected" ? "muted" : "warn"}>{c.status === "completed" ? "Waiting for your review" : MSTATUS[c.status]}</Badge></div>
          <p className="fine">{c.role.replace("_", " ")}, reported {fmtTime(c.completed_at)}</p>
          <p>{c.note}</p>
          {c.photos.length > 0 && <div className="photos">{c.photos.map((n) => <Photo key={n} iid={iv.id} name={n} />)}</div>}
          {c.satellite && <p className="fine">Satellite re-check: {c.satellite.fires_after} fire detection(s) in the area over {c.satellite.days_checked} day(s) after the work. This supports your decision, it does not replace it.</p>}
          {c.status === "completed" ? <>
            <label className="field">Your decision note<input value={notes[c.sid] || ""} onChange={(e) => setNotes({ ...notes, [c.sid]: e.target.value })} placeholder="What did you check?" maxLength="300" /></label>
            <div className="btnrow"><button className="btn primary" disabled={busy} onClick={() => verify(c.sid, true)}><BadgeCheck size={16} /> Verify</button><button className="btn" disabled={busy} onClick={() => verify(c.sid, false)}>Do not accept</button></div></>
            : c.verification && <p className="fine">{c.verification.approved ? "Verified" : "Not accepted"} on {fmtTime(c.verification.at)}{c.verification.by ? ` by ${c.verification.by}` : ""}{c.verification.note ? `: ${c.verification.note.replace(/[.\s]+$/, "")}` : ""}.</p>}
        </div>)) : <p className="fine">Nobody has reported work done yet.</p>}
    </div>);
}
