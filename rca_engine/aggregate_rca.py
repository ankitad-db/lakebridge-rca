"""Aggregate-reconcile RCA (feature #13).

Lakebridge's ``aggregates-reconcile`` compares per-group aggregates (SUM/AVG/COUNT/MIN/MAX
over group-by columns) rather than row-by-row, and writes them to ``aggregate_rules`` /
``aggregate_metrics`` / ``aggregate_details`` (keyed by ``recon_table_id``, joined to
``main`` for the recon_id + table names). Row-level RCA (ingest.py) ignores these tables,
so this module ingests them into ``Finding``s and classifies each rule's mismatch:

* group keys diverge (``missing_in_source`` and ``missing_in_target`` both > 0, no value
  mismatch) — a transform on the GROUP BY column (e.g. a 'Y'/'N' -> boolean mapping) means
  source and target groups don't align, so the totals can't be compared group-for-group;
* aggregated value drift (``mismatch`` > 0) — matching groups whose SUM/AVG/... differs,
  typically a per-row transform on the aggregated column.

Each finding carries a confirming query that recomputes both aggregates and compares them.
Best-effort: any failure returns no aggregate findings and never breaks the row-level RCA.
"""

from __future__ import annotations

from rca_engine.ingest import QueryRunner
from rca_engine.models import (
    Evidence,
    Finding,
    Hypothesis,
    ReconType,
    RootCauseCategory,
    Verdict,
)


def _rows_for(runner: QueryRunner, recon_id: str, catalog: str, schema: str) -> list[dict]:
    q = f"""
    SELECT concat_ws('.', m.source_table.catalog, m.source_table.schema, m.source_table.table_name) AS src,
           concat_ws('.', m.target_table.catalog, m.target_table.schema, m.target_table.table_name) AS tgt,
           ar.rule_info['agg_type']          AS agg_type,
           ar.rule_info['agg_column']        AS agg_col,
           ar.rule_info['group_by_columns']  AS grp,
           am.recon_metrics.mismatch          AS mismatch,
           am.recon_metrics.missing_in_source AS mis_src,
           am.recon_metrics.missing_in_target AS mis_tgt
    FROM {catalog}.{schema}.main m
    JOIN {catalog}.{schema}.aggregate_metrics am ON am.recon_table_id = m.recon_table_id
    JOIN {catalog}.{schema}.aggregate_rules   ar ON ar.rule_id       = am.rule_id
    WHERE m.recon_id = '{recon_id}'
    """
    return runner.query(q)


def _confirm_query(src: str, tgt: str, agg_type: str, agg_col: str, grp: str) -> str:
    keys = [g.strip() for g in (grp or "").split(",") if g.strip()]
    gsel = ", ".join(keys) if keys else "1"
    gkey = " , ".join(keys) if keys else "1"
    on = " AND ".join(f"s.`{k}` <=> t.`{k}`" for k in keys) if keys else "1=1"
    agg = f"{agg_type}(`{agg_col}`)" if agg_col else f"{agg_type}(*)"
    return (
        f"WITH s AS (SELECT {gsel}, {agg} AS v FROM {src} GROUP BY {gkey}),\n"
        f"     t AS (SELECT {gsel}, {agg} AS v FROM {tgt} GROUP BY {gkey})\n"
        f"SELECT count_if(s.`{keys[0]}` IS NULL OR t.`{keys[0]}` IS NULL OR NOT (s.v <=> t.v)) AS n,\n"
        f"       count_if(s.`{keys[0]}` IS NULL OR t.`{keys[0]}` IS NULL OR NOT (s.v <=> t.v)) > 0 AS confirmed\n"
        f"FROM s FULL OUTER JOIN t ON {on}"
        if keys else
        f"SELECT (SELECT {agg} FROM {src}) AS src_v, (SELECT {agg} FROM {tgt}) AS tgt_v, "
        f"NOT ((SELECT {agg} FROM {src}) <=> (SELECT {agg} FROM {tgt})) AS confirmed"
    )


def run_aggregate_rca(runner: QueryRunner, recon_id: str, recon_catalog: str,
                      recon_schema: str) -> list[Finding]:
    """Return AGGREGATE findings for a Lakebridge aggregates-reconcile ``recon_id``."""

    try:
        rows = _rows_for(runner, recon_id, recon_catalog, recon_schema)
    except Exception:
        return []

    findings: list[Finding] = []
    for r in rows:
        try:
            mismatch = int(r.get("mismatch") or 0)
            mis_src = int(r.get("mis_src") or 0)
            mis_tgt = int(r.get("mis_tgt") or 0)
        except (TypeError, ValueError):
            mismatch = mis_src = mis_tgt = 0
        if mismatch == 0 and mis_src == 0 and mis_tgt == 0:
            continue  # this aggregate rule reconciled cleanly

        agg_type = (r.get("agg_type") or "").lower()
        agg_col = r.get("agg_col") or ""
        grp = r.get("grp") or ""
        src, tgt = r.get("src") or "", r.get("tgt") or ""
        rule = f"{agg_type}({agg_col}) BY {grp}" if grp else f"{agg_type}({agg_col})"

        if mis_src > 0 and mis_tgt > 0 and mismatch == 0:
            category = RootCauseCategory.TRANSPILATION
            rationale = (
                f"The GROUP BY column(s) `{grp}` take different values in source vs target "
                f"(a migration transform on the grouping key — e.g. a 'Y'/'N' → boolean or "
                f"case/format change), so {mis_src} source group(s) and {mis_tgt} target "
                f"group(s) have no counterpart. The {agg_type.upper()}(`{agg_col}`) totals "
                f"therefore cannot be compared group-for-group."
            )
            remediation = (
                f"Align the GROUP BY key `{grp}` between source and target (apply the same "
                f"mapping/normalization on both sides), or add a recon transformation so the "
                f"groups match before aggregating."
            )
        elif mismatch > 0:
            category = RootCauseCategory.TRANSPILATION
            rationale = (
                f"{agg_type.upper()}(`{agg_col}`) differs for {mismatch} matching group(s) of "
                f"`{grp}`: the aggregated value diverges, typically a per-row transform on "
                f"`{agg_col}` (precision/scale, formula, or filtered rows) changing the total."
            )
            remediation = (
                f"Reconcile the per-row transform on `{agg_col}` (see the row-level RCA for "
                f"that column); the aggregate is a rollup of the same defect."
            )
        else:
            category = RootCauseCategory.VOLUME_MISSING if mis_tgt else RootCauseCategory.VOLUME_EXTRA
            rationale = (
                f"{mis_src} group(s) present only in target and {mis_tgt} only in source for "
                f"{agg_type.upper()}(`{agg_col}`) BY `{grp}` — a group appeared/disappeared "
                f"(row volume or a new/removed grouping value)."
            )
            remediation = "Investigate the missing/extra group(s) — a load filter or new dimension value."

        f = Finding(
            recon_id=recon_id, source_table=src, target_table=tgt,
            recon_type=ReconType.AGGREGATE, column=agg_col or None,
            mismatch_count=mismatch + mis_src + mis_tgt, total_count=0,
            metadata={"agg_type": agg_type, "group_by": grp, "rule": rule,
                      "mismatch": mismatch, "missing_in_source": mis_src,
                      "missing_in_target": mis_tgt},
        )
        ev = [Evidence(label="code",
                       detail=f"Aggregate rule `{rule}` — mismatch={mismatch}, "
                              f"missing_in_source={mis_src}, missing_in_target={mis_tgt}.")]
        if src and tgt:
            confirm = _confirm_query(src, tgt, agg_type, agg_col, grp)
            confirmed = False
            try:
                res = runner.query(confirm)
                confirmed = bool(res and res[0].get("confirmed"))
            except Exception:
                confirmed = False
            ev.append(Evidence(label="drilldown",
                               detail=("Confirmed by recomputing the aggregate on both sides."
                                       if confirmed else "Recompute the aggregate to confirm."),
                               query=confirm))
        f.hypotheses.append(Hypothesis(
            category=category, verdict=Verdict.MIGRATION_INDUCED,
            confidence=0.85, rationale=rationale, remediation=remediation,
            recommended_owner="migration engineer", evidence=ev,
        ))
        findings.append(f)
    return findings
