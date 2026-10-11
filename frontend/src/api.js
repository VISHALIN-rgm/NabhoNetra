// Signed-in registrants (farmer, provider, buyer, officer): a signed session token kept in this browser until they sign out.
const safe = (f) => { try { return f(); } catch { return null; } };
export const getSession = () => safe(() => localStorage.getItem("nn_session")) || "";
export const getMe = () => safe(() => JSON.parse(localStorage.getItem("nn_me") || "null"));
export function setSession(token, me) {
  safe(() => { localStorage.setItem("nn_session", token); localStorage.setItem("nn_me", JSON.stringify(me || null)); });
  window.dispatchEvent(new Event("nn-session"));
}
export function clearSession() {
  safe(() => { localStorage.removeItem("nn_session"); localStorage.removeItem("nn_me"); });
  window.dispatchEvent(new Event("nn-session"));
}

// Calls the NabhoNetra server (FastAPI). Every call carries the sign-in session when there is one.
// The website never holds an admin token: administrators and officers sign in with a one-time code like everyone else,
// and the server decides on every call what that person's role and area allow.
export async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
  const sess = getSession();
  if (sess) headers["x-session"] = sess;
  const r = await fetch(path, { ...opts, headers });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) {
    const d = j.detail;
    throw new Error(typeof d === "string" ? d : Array.isArray(d) ? d[0]?.msg || "Invalid input" : `Request failed (${r.status})`);
  }
  return j;
}

export async function apiBlob(path) {
  const sess = getSession();
  const r = await fetch(path, { headers: sess ? { "x-session": sess } : {} });
  if (!r.ok) throw new Error("Could not load the file.");
  return URL.createObjectURL(await r.blob());
}
