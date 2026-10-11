export const COLORS = { high: "#F0443A", medium: "#F59E0B", low: "#64748B" };
export const LABEL = { high: "High", medium: "Medium", low: "Low" };
export const cityOf = (c) => c?.city_name || "the city";
export const riskOf = (c, max) => Math.min(99, Math.round(35 * (c.score / max) + 60 * (c.reach ?? c.alignment) + 5));
export const compass = (d) => ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][Math.round(d / 45) % 8];
export const reasonsOf = (c) => {
  const a = c.alert?.alternatives?.[0];
  return [
    c.alignment >= 0.5 ? `Wind is heading toward ${cityOf(c)}` : `Wind is mostly not toward ${cityOf(c)}`,
    `${c.fires} fire detections in this area`,
    `${c.distance_km} km from ${cityOf(c)}`,
    a ? (a.km > 15 ? "No alternative within 15 km" : `Nearest alternative is ${a.km} km away`) : "No alternative data",
  ];
};
export const fmtTime = (iso) => iso ? new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit", hour12: true, timeZoneName: "short" }) : "time n/a";
export const placeOf = (c) => c.place || `${Math.abs(c.lat).toFixed(2)}°${c.lat >= 0 ? "N" : "S"}, ${Math.abs(c.lon).toFixed(2)}°${c.lon >= 0 ? "E" : "W"}`;
export const smokeLine = (c) => c.eta_hours ? `Forecast: smoke may reach ${cityOf(c)} in about ${c.eta_hours} h` : c.reach >= 0.5 ? `Forecast: smoke passes close to ${cityOf(c)}` : `Forecast: smoke is not expected to reach ${cityOf(c)} soon`;
export const nearbyLine = (c) => c.nearby ? `Registered within range: ${c.nearby.farmer} farmers, ${c.nearby.machine_provider} machine providers, ${c.nearby.biomass_buyer} biomass buyers` : "";
export const sourceLine = (c) => c.alert?.source === "model" ? "Written by the AI model and checked against the facts" : "Standard template (the AI text was not used or failed its checks)";
