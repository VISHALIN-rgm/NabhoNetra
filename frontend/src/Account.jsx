import { useEffect, useState } from "react";
import { LogIn, LogOut, X } from "lucide-react";
import { api, setSession, clearSession } from "./api.js";

export function AccountButton({ me, onSignIn, flash }) {
  if (!me) return <button type="button" className="btn sm signin" onClick={onSignIn}><LogIn size={15} /><span>Sign in</span></button>;
  return (
    <span className="acct"><span className="acctname" title={me.name}><b>{me.name}</b><small>{me.role_label}</small></span>
      <button type="button" className="iconbtn" aria-label="Sign out" title={`Sign out ${me.name}`} onClick={() => { clearSession(); flash?.("Signed out"); }}><LogOut size={16} /></button></span>);
}

/** Returning registrants sign in with the contact they registered with and a one-time code. */
export function SignInModal({ onClose, flash }) {
  const [channels, setChannels] = useState(["sms", "email"]); const [channel, setChannel] = useState("sms"); const [contact, setContact] = useState("");
  const [step, setStep] = useState("ask"); const [code, setCode] = useState(""); const [msg, setMsg] = useState(""); const [busy, setBusy] = useState(false);
  useEffect(() => { api("/api/config").then((c) => { setChannels(c.channels); setChannel(c.channels[0]); }).catch(() => {}); }, []);
  useEffect(() => { const k = (e) => e.key === "Escape" && onClose(); addEventListener("keydown", k); return () => removeEventListener("keydown", k); }, []);
  const start = async (e) => {
    e?.preventDefault(); setBusy(true); setMsg("");
    try { const r = await api("/api/session/start", { method: "POST", body: JSON.stringify({ channel, contact }) }); setStep("code");
      setMsg(`If ${contact} is registered, we sent a 6-digit code.` + (r.dev_code ? ` Test mode code: ${r.dev_code}` : "")); }
    catch (err) { setMsg(err.message); } finally { setBusy(false); }
  };
  const verify = async (e) => {
    e.preventDefault(); setBusy(true); setMsg("");
    try { const r = await api("/api/session/verify", { method: "POST", body: JSON.stringify({ channel, contact, code }) });
      setSession(r.session, r.me); flash?.(`Signed in as ${r.me.name}`); onClose(); }
    catch (err) { setMsg(err.message); } finally { setBusy(false); }
  };
  return (
    <div className="modalbg" role="presentation" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="card modal" role="dialog" aria-modal="true" aria-label="Sign in">
        <div className="cardhead"><h2>Sign in to NabhoNetra</h2><button type="button" className="iconbtn" aria-label="Close" onClick={onClose}><X size={16} /></button></div>
        <p className="muted block">Use the phone number or email you registered with. We send a one-time code. Not registered yet? Close this and use Join NabhoNetra on the home page.</p>
        {step === "ask" ? (
          <form className="form" onSubmit={start}>
            <label className="field">Send the code by<select value={channel} onChange={(e) => setChannel(e.target.value)}>{channels.map((c) => <option key={c} value={c}>{c === "sms" ? "SMS" : c === "whatsapp" ? "WhatsApp" : "Email"}</option>)}</select></label>
            <label className="field">{channel === "email" ? "Email address" : "Phone number with country code"}<input value={contact} onChange={(e) => setContact(e.target.value)} placeholder={channel === "email" ? "you@example.com" : "+91XXXXXXXXXX"} autoFocus required /></label>
            <button className="btn primary" disabled={busy || !contact.trim()}>Send code</button>
          </form>) : (
          <form className="form" onSubmit={verify}>
            <label className="field">6-digit code<input value={code} onChange={(e) => setCode(e.target.value)} inputMode="numeric" autoComplete="one-time-code" maxLength={6} autoFocus required /></label>
            <div className="btnrow"><button className="btn primary" disabled={busy || code.trim().length < 6}>Sign in</button><button type="button" className="btn" onClick={() => { setStep("ask"); setCode(""); setMsg(""); }}>Back</button></div>
          </form>)}
        {msg && <p className="fmsg" role="status">{msg}</p>}
      </div>
    </div>);
}
