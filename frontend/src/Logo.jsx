// NabhoNetra = "eye of the sky": an eye watching over a crop field, with a sprout as the pupil.
export default function Logo({ size = 38 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" role="img" aria-label="NabhoNetra logo">
      <defs><linearGradient id="nnG" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#12B981" /><stop offset="1" stopColor="#065F46" /></linearGradient></defs>
      <rect width="48" height="48" rx="12" fill="url(#nnG)" />
      <path d="M6 21C11 12.500 17.500 8.500 24 8.500S37 12.500 42 21c-5 8.500-11.500 12.500-18 12.500S11 29.500 6 21z" fill="none" stroke="#fff" strokeWidth="2.300" strokeLinejoin="round" />
      <circle cx="24" cy="21" r="8" fill="#0B1233" />
      <path d="M24 27V18" stroke="#86EFAC" strokeWidth="1.800" strokeLinecap="round" />
      <path d="M24 22.500c-3.200 0-5-1.700-5.200-4.600 3.100 0 5 1.600 5.200 4.600z" fill="#86EFAC" />
      <path d="M24 20.500c3.200 0 5-1.700 5.200-4.600-3.100 0-5 1.600-5.200 4.600z" fill="#BBF7D0" />
      <path d="M8 40.500c10-4 22-4 32 0" fill="none" stroke="#BBF7D0" strokeWidth="2" strokeLinecap="round" />
      <path d="M13 44c7.500-2.500 14.500-2.500 22 0" fill="none" stroke="#86EFAC" strokeWidth="1.600" strokeLinecap="round" opacity=".7" />
    </svg>
  );
}
