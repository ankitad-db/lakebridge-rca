"""Optional Unity Catalog lineage evidence.

When enabled (and UC lineage has been captured for the target tables), this adds an
independent confirmation source to the RCA: column-level lineage shows a target
column's *true* upstream column(s), and table lineage shows the upstream tables that
feed a target — useful for volume/drift findings (where was a filter/join introduced?)
and for catching an unexpected provenance (a column sourced from a table other than the
one being reconciled).

It reads the ``system.access.column_lineage`` / ``system.access.table_lineage`` system
tables through the same ``QueryRunner`` the rest of the engine uses. Every query is
defensive: if the system tables are unavailable, empty, or access is denied, the pass
attaches nothing and the RCA proceeds unaffected.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rca_engine.ingest import QueryRunner
from rca_engine.models import Evidence, Finding, ReconType


@dataclass
class LineageInfo:
    upstream_tables: list[str] = field(default_factory=list)
    column_upstreams: dict[str, list[str]] = field(default_factory=dict)  # target_col -> [source_col fqn]


def _short(name: str) -> str:
    return name.split(".")[-1].strip("`").lower() if name else ""


def fetch_lineage(runner: QueryRunner, target_table: str, lookback_days: int = 90) -> LineageInfo:
    info = LineageInfo()
    try:
        rows = runner.query(
            "SELECT source_table_full_name AS src_tbl, source_column_name AS src_col, "
            "target_column_name AS tgt_col "
            "FROM system.access.column_lineage "
            f"WHERE lower(target_table_full_name) = lower('{target_table}') "
            "AND source_table_full_name IS NOT NULL "
            f"AND event_date >= current_date() - INTERVAL {int(lookback_days)} DAYS "
            "GROUP BY 1, 2, 3"
        )
        for r in rows:
            tgt_col = str(r.get("tgt_col") or "").lower()
            src_tbl, src_col = r.get("src_tbl"), r.get("src_col")
            if src_tbl:
                info.upstream_tables.append(str(src_tbl))
            if tgt_col and src_tbl and src_col:
                info.column_upstreams.setdefault(tgt_col, []).append(f"{src_tbl}.{src_col}")
    except Exception:
        pass
    if not info.upstream_tables:
        try:
            rows = runner.query(
                "SELECT DISTINCT source_table_full_name AS src_tbl "
                "FROM system.access.table_lineage "
                f"WHERE lower(target_table_full_name) = lower('{target_table}') "
                "AND source_table_full_name IS NOT NULL "
                f"AND event_date >= current_date() - INTERVAL {int(lookback_days)} DAYS"
            )
            info.upstream_tables = [str(r.get("src_tbl")) for r in rows if r.get("src_tbl")]
        except Exception:
            pass
    info.upstream_tables = sorted(set(info.upstream_tables))
    return info


def run_lineage(findings: list[Finding], runner: QueryRunner, lookback_days: int = 90) -> list[Finding]:
    """Attach UC-lineage evidence to findings (grouped by target table, one fetch each)."""

    by_table: dict[str, list[Finding]] = {}
    for f in findings:
        by_table.setdefault(f.target_table, []).append(f)

    for table, fs in by_table.items():
        info = fetch_lineage(runner, table, lookback_days=lookback_days)
        if not info.upstream_tables and not info.column_upstreams:
            continue
        expected_src = _short(fs[0].source_table) if fs else ""
        for f in fs:
            top = f.top_hypothesis
            if top is None:
                continue
            if f.recon_type == ReconType.COLUMN_MISMATCH and f.column:
                ups = info.column_upstreams.get(f.column.lower())
                if ups:
                    top.evidence.append(Evidence(
                        label="lineage",
                        detail=f"UC column lineage: `{f.column}` derives from {ups}.",
                    ))
                    # Only flag a provenance surprise when the column maps 1:1 to a single
                    # upstream that isn't the reconciled source (a real "wrong source" smell).
                    # Multi-upstream columns are aggregates/joins where this is expected.
                    if (expected_src and len(ups) == 1
                            and not any(expected_src in u.lower() for u in ups)):
                        top.evidence.append(Evidence(
                            label="lineage",
                            detail=f"Lineage shows `{f.column}` is sourced from `{ups[0]}`, not the "
                            f"reconciled source `{fs[0].source_table}` — check for an unexpected "
                            f"join/derivation.",
                        ))
            elif f.recon_type in (ReconType.MISSING_IN_TARGET, ReconType.MISSING_IN_SOURCE):
                if info.upstream_tables:
                    top.evidence.append(Evidence(
                        label="lineage",
                        detail=f"UC table lineage: target is fed by {info.upstream_tables}. Inspect the "
                        f"upstream job/query for the filter/join that changed row volume.",
                    ))
    return findings
