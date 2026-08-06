"""Quantify *how much* and *where* a column's distribution differs (source vs target).

The value probes and drill-down tell you a column differs and by what mechanism.
This pass adds the missing magnitude: for each column-level finding it measures the
source and target distributions — null-rate, cardinality (distinct values), and, for
numerics, min/max/mean/stddev — and reports the shift.

That magnitude sharpens the verdict:
- small, symmetric numeric drift with a stable null-rate and cardinality is
  consistent with a migration/precision cause (representation changed, population
  did not);
- a jump in null-rate or a material cardinality change points to a genuine upstream
  data difference (the population itself changed), which the report should route to
  the data owner rather than the migration engineer.

It runs live through the same ``QueryRunner`` as the rest of the engine, one query
per column finding, and is fully defensive: any failure attaches nothing and leaves
the existing verdict untouched.
"""

from __future__ import annotations

from typing import Any, Optional

from rca_engine.ingest import QueryRunner
from rca_engine.models import Evidence, Finding, ReconType
from rca_engine.scan import ScanScope, partition_clause, where_clauses

# A distribution shift is "material" (population changed, not just representation)
# when the null-rate moves by more than this many percentage points or the number of
# distinct values changes by more than this fraction.
_NULL_PP_THRESHOLD = 1.0
_NDV_FRAC_THRESHOLD = 0.05


def _f(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _pct(part: Optional[float], whole: Optional[float]) -> Optional[float]:
    if part is None or not whole:
        return None
    return 100.0 * part / whole


def _rel_change(src: Optional[float], tgt: Optional[float]) -> Optional[float]:
    """Signed relative change tgt-vs-src as a fraction (e.g. -0.048 = −4.8%)."""
    if src is None or tgt is None or src == 0:
        return None
    return (tgt - src) / abs(src)


def _drift_query(st: str, tt: str, col: str, scope: ScanScope | None = None) -> str:
    # Restrict each single-table aggregate to the configured partition window so a drift
    # check reads one partition instead of full history (exact within the window).
    w = where_clauses(partition_clause(scope))

    def block(tbl: str, p: str) -> str:
        return (
            f"(SELECT count(*) FROM {tbl}{w}) AS {p}_n, "
            f"(SELECT sum(CASE WHEN `{col}` IS NULL THEN 1 ELSE 0 END) FROM {tbl}{w}) AS {p}_nulls, "
            f"(SELECT approx_count_distinct(`{col}`) FROM {tbl}{w}) AS {p}_ndv, "
            f"(SELECT avg(try_cast(`{col}` AS double)) FROM {tbl}{w}) AS {p}_avg, "
            f"(SELECT stddev(try_cast(`{col}` AS double)) FROM {tbl}{w}) AS {p}_std, "
            f"(SELECT min(try_cast(`{col}` AS double)) FROM {tbl}{w}) AS {p}_min, "
            f"(SELECT max(try_cast(`{col}` AS double)) FROM {tbl}{w}) AS {p}_max"
        )

    return "SELECT " + block(st, "s") + ", " + block(tt, "t")


def _summarize(r: dict[str, Any]) -> dict[str, Any]:
    s_n, t_n = _f(r.get("s_n")), _f(r.get("t_n"))
    s_null_pct = _pct(_f(r.get("s_nulls")), s_n)
    t_null_pct = _pct(_f(r.get("t_nulls")), t_n)
    s_ndv, t_ndv = _f(r.get("s_ndv")), _f(r.get("t_ndv"))
    s_avg, t_avg = _f(r.get("s_avg")), _f(r.get("t_avg"))
    s_std, t_std = _f(r.get("s_std")), _f(r.get("t_std"))

    null_pp = (t_null_pct - s_null_pct) if (s_null_pct is not None and t_null_pct is not None) else None
    ndv_frac = _rel_change(s_ndv, t_ndv)
    mean_frac = _rel_change(s_avg, t_avg)
    numeric = s_avg is not None or t_avg is not None

    material = bool(
        (null_pp is not None and abs(null_pp) > _NULL_PP_THRESHOLD)
        or (ndv_frac is not None and abs(ndv_frac) > _NDV_FRAC_THRESHOLD)
    )
    return {
        "source_rows": s_n, "target_rows": t_n,
        "source_null_pct": s_null_pct, "target_null_pct": t_null_pct, "null_pp_delta": null_pp,
        "source_ndv": s_ndv, "target_ndv": t_ndv, "ndv_frac_delta": ndv_frac,
        "source_mean": s_avg, "target_mean": t_avg, "mean_frac_delta": mean_frac,
        "source_stddev": s_std, "target_stddev": t_std,
        "numeric": numeric, "material": material,
    }


def _detail(col: str, d: dict[str, Any]) -> str:
    parts: list[str] = []
    if d.get("source_null_pct") is not None and d.get("target_null_pct") is not None:
        pp = d["null_pp_delta"] or 0.0
        parts.append(
            f"null-rate src {d['source_null_pct']:.2f}% vs tgt {d['target_null_pct']:.2f}% "
            f"(Δ {pp:+.2f}pp)"
        )
    if d.get("source_ndv") is not None and d.get("target_ndv") is not None:
        frac = d["ndv_frac_delta"]
        chg = f" ({frac*100:+.1f}%)" if frac is not None else ""
        parts.append(f"distinct {int(d['source_ndv']):,} vs {int(d['target_ndv']):,}{chg}")
    if d.get("numeric") and d.get("source_mean") is not None and d.get("target_mean") is not None:
        frac = d["mean_frac_delta"]
        chg = f" ({frac*100:+.2f}%)" if frac is not None else ""
        parts.append(f"mean {d['source_mean']:.4g} vs {d['target_mean']:.4g}{chg}")
    if d.get("numeric") and d.get("source_stddev") is not None and d.get("target_stddev") is not None:
        parts.append(f"stddev {d['source_stddev']:.4g} vs {d['target_stddev']:.4g}")

    body = "; ".join(parts) if parts else "no comparable statistics"
    verdict_hint = (
        "material distribution shift — the population changed, consistent with a "
        "genuine upstream data difference"
        if d.get("material")
        else "distribution stable — values differ in representation/precision, not population"
    )
    return f"Distribution of `{col}`: {body}. {verdict_hint}."


def run_drift(
    findings: list[Finding], runner: QueryRunner, scope: ScanScope | None = None
) -> list[Finding]:
    """Attach a distribution-drift evidence line (+ structured ``metadata['drift']``)
    to every column-level finding. Verdicts are left to the drill-down; this only
    quantifies and annotates. ``scope`` restricts the stats to a partition window."""

    for f in findings:
        if f.recon_type != ReconType.COLUMN_MISMATCH or not f.column:
            continue
        top = f.top_hypothesis
        if top is None:
            continue
        try:
            rows = runner.query(_drift_query(f.source_table, f.target_table, f.column, scope))
        except Exception:
            continue
        if not rows:
            continue
        d = _summarize(rows[0])
        f.metadata["drift"] = d
        top.evidence.append(Evidence(label="drift", detail=_detail(f.column, d), data=d))
    return findings
