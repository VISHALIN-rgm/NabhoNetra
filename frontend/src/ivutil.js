// Pure helpers for the Interventions page (kept apart so they can be tested without a browser).
export const STAGES = ["Detected", "Solution suggested", "Resource matched", "In progress", "Completed"];
export const STATUS = { open: "Open", coordinating: "Requests sent", accepted: "In progress", completed: "Reported done", verified: "Verified", rejected: "Not verified" };
export const ROLE_LABEL = { farmer: "Farmer", machine_provider: "Machine provider", biomass_buyer: "Biomass buyer", officer: "Officer", admin: "Admin" };
const PRIO = { high: 2, medium: 1, low: 0 };

/** How far an intervention has got, from real record fields only. `done` stages are ticked; `note` explains the current step. */
export function stageOf(iv) {
  if (!iv) return { done: 1, note: "Monitored only. No intervention is opened for low-priority clusters." };
  const s = iv.status, matched = Object.keys(iv.matches || {}).length > 0;
  if (s === "verified") return { done: 5, note: "Outcome verified by an officer." };
  if (s === "rejected") return { done: 4, note: "An officer did not accept the evidence." };
  if (s === "completed") return { done: 4, note: "Work reported. Waiting for an officer to verify." };
  if (s === "accepted") return { done: 4, note: "A matched party accepted and is working on it." };
  return { done: matched ? 3 : 2, note: s === "coordinating" ? "Requests sent. Waiting for a reply." : matched ? "Matches found. Requests not sent yet." : "No registered provider or buyer matched yet." };
}

export const nearPt = (a, b) => Math.abs(a.lat - b.lat) < 0.06 && Math.abs(a.lon - b.lon) < 0.06;
export const split = (place) => { const [t, ...r] = String(place || "").split(", "); return { title: t || "Unnamed place", sub: r.join(", ") }; };

/** Join interventions with the latest cluster data (wind, AI text, alternatives) and add detections that have no intervention. */
export function buildItems(list, clusters) {
  const used = new Set();
  const out = (list || []).map((iv) => {
    const dc = (clusters || []).find((c) => c.id === iv.cluster.id && nearPt(c, iv.cluster)) || (clusters || []).find((c) => nearPt(c, iv.cluster));
    if (dc) used.add(dc.id);
    return { key: iv.id, iv, dc, c: { ...(dc || {}), ...iv.cluster } };
  });
  (clusters || []).filter((c) => !used.has(c.id)).forEach((c) => out.push({ key: "d-" + c.id, iv: null, dc: c, c }));
  return out.sort((a, b) => (PRIO[b.c.priority] - PRIO[a.c.priority]) || String(b.c.last_detected || "").localeCompare(String(a.c.last_detected || "")));
}

/** Title and subtitle for a cluster. Without a place name, falls back to its id and coordinates instead of splitting them. */
export function where(c) {
  if (c.place) return split(c.place);
  return { title: c.id ? `Fire cluster ${c.id}` : "Fire cluster", sub: `${Math.abs(c.lat).toFixed(2)}°${c.lat >= 0 ? "N" : "S"}, ${Math.abs(c.lon).toFixed(2)}°${c.lon >= 0 ? "E" : "W"}` };
}

export const RQ_LABEL = { open: "Looking for options", proposed: "Options ready: choose one", waiting_provider: "Waiting for the provider", provider_declined: "Provider declined: choose another",
  in_progress: "Work in progress", completed: "Work reported, waiting for an officer to check", verified: "Outcome verified", rejected: "Evidence not accepted", withdrawn: "Withdrawn" };
export const RQ_STEPS = ["Requested", "Options proposed", "You chose", "Provider accepted", "Work reported", "Verified"];
/** How many of the six request steps are done, from the request status alone. */
export const rqDone = (st) => ({ open: 1, proposed: 2, provider_declined: 2, waiting_provider: 3, in_progress: 4, completed: 5, rejected: 5, verified: 6, withdrawn: 1 })[st] ?? 1;
export const NEED_LABEL = { seeder: "Sow through residue (seeder)", mulcher: "Mulcher or chopper", baler: "Baler", buyer: "A buyer for the straw", decomposer: "Bio-decomposer" };
