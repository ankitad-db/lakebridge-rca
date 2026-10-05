/* Shared, professional date/time formatting used across all pages so timestamps read
   consistently (e.g. "Sep 24, 2026" and "Sep 24, 2026, 8:02 AM"). Recon timestamps arrive
   either ISO ("2026-07-21T08:02:55Z") or space-separated ("2026-07-21 08:02:55", treated as
   UTC); both normalize here. Invalid/empty values render as an em dash. */

function parse(ts: string | null | undefined): Date | null {
  if (!ts) return null;
  const iso = ts.includes("T") ? ts : ts.replace(" ", "T") + "Z";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? null : d;
}

/** "Sep 24, 2026" */
export function fmtDate(ts: string | null | undefined): string {
  const d = parse(ts);
  return d ? d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }) : "—";
}

/** "Sep 24, 2026, 8:02 AM" */
export function fmtDateTime(ts: string | null | undefined): string {
  const d = parse(ts);
  return d
    ? d.toLocaleString(undefined, {
        year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
      })
    : "—";
}
