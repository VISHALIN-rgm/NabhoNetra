export const Badge = ({ tone = "muted", children }) => <span className={"badge " + tone}>{children}</span>;

export function Ring({ v, color, size = 92, light = false }) {
  const r = 34, C = 2 * Math.PI * r;
  return (
    <svg width={size} height={size} viewBox="0 0 84 84" role="img" aria-label={`Risk index ${v}%`}>
      <circle cx="42" cy="42" r={r} fill="none" stroke={light ? "rgba(255,255,255,.18)" : "#E8ECF4"} strokeWidth="8" />
      <circle cx="42" cy="42" r={r} fill="none" stroke={color} strokeWidth="8" strokeLinecap="round" strokeDasharray={`${(C * v) / 100} ${C}`} transform="rotate(-90 42 42)" />
      <text x="42" y="48" textAnchor="middle" className="ringtxt" fill={light ? "#fff" : "#0B1233"}>{v}%</text>
    </svg>
  );
}

export function Spark({ values, color = "#0E9F6E" }) {
  if (!values || values.length < 2) return null;
  const m = Math.max(...values, 1), w = 80, h = 28;
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * w},${h - 3 - (v / m) * (h - 6)}`).join(" ");
  return <svg className="spark" width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden="true"><polyline points={pts} fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>;
}
