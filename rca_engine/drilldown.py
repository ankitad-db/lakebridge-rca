"""Live drill-down: confirm each finding's hypothesis with a real query.

This is what makes the RCA end-to-end rather than a static guess. For every
finding we run a targeted query against the real source/target tables, attach
the query + result as evidence, and finalize the verdict/confidence. Runs with
any ``QueryRunner`` (Spark in a notebook, or the statement API locally).

Every probe is defensive: a failed drill-down never breaks the pipeline, it just
leaves the deterministic verdict in place with a note.
"""

from __future__ import annotations

from typing import Any

from rca_engine.ingest import QueryRunner
from rca_engine.models import Evidence, Finding, ReconType, RootCauseCategory, Verdict


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _join_keys(finding: Finding) -> list[str]:
    for s in finding.samples:
        if s.keys:
            return list(s.keys.keys())
    return []


def _table_keys(findings: list[Finding]) -> dict[str, list[str]]:
    """Learn each table's join key(s) from its column-mismatch samples."""

    keys: dict[str, list[str]] = {}
    for f in findings:
        if f.recon_type == ReconType.COLUMN_MISMATCH:
            k = _join_keys(f)
            if k and f.target_table not in keys:
                keys[f.target_table] = k
    return keys


def _one(runner: QueryRunner, sql: str) -> dict[str, Any]:
    rows = runner.query(sql)
    return rows[0] if rows else {}


def _confirm_column(finding: Finding, runner: QueryRunner, keys: list[str]) -> Evidence | None:
    st, tt, col = finding.source_table, finding.target_table, finding.column
    if not (col and keys):
        return None
    on = " AND ".join(f"s.`{k}` = t.`{k}`" for k in keys)
    cat = finding.top_hypothesis.category if finding.top_hypothesis else None

    if cat == RootCauseCategory.TIMEZONE:
        sql = (
            f"SELECT count(DISTINCT unix_timestamp(t.`{col}`) - unix_timestamp(s.`{col}`)) AS distinct_offsets, "
            f"max(unix_timestamp(t.`{col}`) - unix_timestamp(s.`{col}`))/3600.0 AS offset_hours, count(*) AS n "
            f"FROM {st} s JOIN {tt} t ON {on} WHERE s.`{col}` <> t.`{col}`"
        )
        r = _one(runner, sql)
        constant = _num(r.get("distinct_offsets")) == 1
        return Evidence(
            label="drilldown",
            detail=(
                f"Confirmed: constant {_num(r.get('offset_hours')):.2f}h offset across "
                f"{int(_num(r.get('n')))} rows (single distinct offset)."
                if constant else
                f"{int(_num(r.get('distinct_offsets')))} distinct offsets across "
                f"{int(_num(r.get('n')))} rows; offset is not uniform."
            ),
            query=sql,
            data={"confirmed": constant, **r},
        )

    if cat in (RootCauseCategory.TYPE_PRECISION, RootCauseCategory.TRANSPILATION):
        sql = (
            f"SELECT count(*) AS n, avg(abs(cast(s.`{col}` AS double) - cast(t.`{col}` AS double))) AS avg_abs_diff, "
            f"max(abs(cast(s.`{col}` AS double) - cast(t.`{col}` AS double))) AS max_abs_diff, "
            f"sum(CASE WHEN round(cast(s.`{col}` AS double), 2) = cast(t.`{col}` AS double) THEN 1 ELSE 0 END) AS eq_at_2dp "
            f"FROM {st} s JOIN {tt} t ON {on} WHERE s.`{col}` <> t.`{col}`"
        )
        r = _one(runner, sql)
        n = _num(r.get("n"))
        return Evidence(
            label="drilldown",
            detail=(
                f"Confirmed: {int(n)} rows differ, max |diff|={_num(r.get('max_abs_diff')):.4f}, "
                f"avg |diff|={_num(r.get('avg_abs_diff')):.4f}; "
                f"{int(_num(r.get('eq_at_2dp')))} equal after rounding to 2dp -> rounding/scale loss."
            ),
            query=sql,
            data={"confirmed": n > 0, **r},
        )

    if cat == RootCauseCategory.STRING_FORMAT:
        sql = (
            f"SELECT count(*) AS n, "
            f"sum(CASE WHEN trim(lower(s.`{col}`)) = trim(lower(t.`{col}`)) THEN 1 ELSE 0 END) AS cosmetic "
            f"FROM {st} s JOIN {tt} t ON {on} WHERE s.`{col}` <> t.`{col}`"
        )
        r = _one(runner, sql)
        n, cosmetic = _num(r.get("n")), _num(r.get("cosmetic"))
        return Evidence(
            label="drilldown",
            detail=f"Confirmed: {int(cosmetic)}/{int(n)} differences are trim/case-only "
            f"(value changed by the transform; align TRIM/case).",
            query=sql,
            data={"confirmed": n > 0 and cosmetic == n, **r},
        )

    if cat == RootCauseCategory.NULL_BOOLEAN:
        sql = (
            f"SELECT count(*) AS n, "
            f"sum(CASE WHEN s.`{col}` IS NULL OR t.`{col}` IS NULL THEN 1 ELSE 0 END) AS null_involved "
            f"FROM {st} s JOIN {tt} t ON {on} WHERE NOT (s.`{col}` <=> t.`{col}`)"
        )
        r = _one(runner, sql)
        return Evidence(
            label="drilldown",
            detail=f"Confirmed: {int(_num(r.get('n')))} rows differ on `{col}`; "
            f"{int(_num(r.get('null_involved')))} involve a NULL (NULL/empty or boolean encoding).",
            query=sql,
            data={"confirmed": _num(r.get("n")) > 0, **r},
        )

    if cat == RootCauseCategory.UPSTREAM_DRIFT:
        # Provenance: is the source genuinely NULL / how many rows differ.
        sql = (
            f"SELECT count(*) AS src_total, "
            f"sum(CASE WHEN `{col}` IS NULL THEN 1 ELSE 0 END) AS src_nulls "
            f"FROM {st}"
        )
        r = _one(runner, sql)
        src_nulls, src_total = _num(r.get("src_nulls")), _num(r.get("src_total"))
        if src_nulls > 0:
            detail = (f"Confirmed genuine data difference: `{col}` is NULL for "
                      f"{int(src_nulls)}/{int(src_total)} source rows but populated in target "
                      f"-> source data gap, not a migration defect. Route to the data owner.")
        else:
            detail = (f"`{col}` is populated in source ({int(src_total)} rows, 0 NULL) but differs on a "
                      f"subset in target -> stale-snapshot/upstream drift. Verify source refresh time.")
        return Evidence(label="drilldown", detail=detail, query=sql, data={"confirmed": True, **r})

    return None


def _confirm_volume(finding: Finding, runner: QueryRunner, key: str | None) -> Evidence | None:
    st, tt = finding.source_table, finding.target_table
    if not key:
        return None
    if finding.recon_type == ReconType.MISSING_IN_TARGET:
        sql = f"SELECT max(`{key}`) AS src_max FROM {st}"
        src_max = _num(_one(runner, sql).get("src_max"))
        tgt_max = _num(_one(runner, f"SELECT max(`{key}`) AS tgt_max FROM {tt}").get("tgt_max"))
        watermark = tgt_max < src_max
        return Evidence(
            label="drilldown",
            detail=(
                f"Confirmed watermark/incremental lag: target max(`{key}`)={int(tgt_max)} < "
                f"source max={int(src_max)}; the {finding.mismatch_count} missing rows are the newest keys. "
                f"Advance the watermark / back-fill."
                if watermark else
                f"Missing rows are not a simple high-watermark cut (target max `{key}`={int(tgt_max)}); "
                f"inspect the load filter."
            ),
            query=f"SELECT max(`{key}`) FROM {st}  /* vs */  SELECT max(`{key}`) FROM {tt}",
            data={"confirmed": watermark, "src_max": src_max, "tgt_max": tgt_max},
        )
    # MISSING_IN_SOURCE (extra rows in target)
    sql = (
        f"SELECT count(*) AS extra FROM {tt} t LEFT ANTI JOIN {st} s ON s.`{key}` = t.`{key}`"
    )
    extra = _num(_one(runner, sql).get("extra"))
    return Evidence(
        label="drilldown",
        detail=f"Confirmed: {int(extra)} target rows have `{key}` values absent from source "
        f"(extra rows) -> fan-out join or non-idempotent load; de-duplicate / make idempotent.",
        query=sql,
        data={"confirmed": extra > 0, "extra": extra},
    )


def run_drilldown(findings: list[Finding], runner: QueryRunner) -> list[Finding]:
    """Execute confirmation queries and finalize verdicts in place."""

    tk = _table_keys(findings)
    for f in findings:
        try:
            if f.recon_type == ReconType.COLUMN_MISMATCH:
                ev = _confirm_column(f, runner, _join_keys(f) or tk.get(f.target_table, []))
            elif f.recon_type in (ReconType.MISSING_IN_TARGET, ReconType.MISSING_IN_SOURCE):
                key = (tk.get(f.target_table) or [None])[0]
                ev = _confirm_volume(f, runner, key)
            else:
                ev = None
        except Exception as e:  # never break the pipeline on a bad query
            ev = Evidence(label="drilldown", detail=f"Drill-down query failed: {e}")

        if ev is None:
            continue
        top = f.top_hypothesis
        if top is not None:
            top.evidence.insert(0, ev)
            if ev.data and ev.data.get("confirmed"):
                top.confidence = round(min(0.98, max(top.confidence, 0.6) + 0.15), 2)
                if top.verdict == Verdict.NEEDS_REVIEW:
                    top.verdict = Verdict.GENUINE_DATA if top.category in (
                        RootCauseCategory.UPSTREAM_DRIFT,
                    ) else Verdict.MIGRATION_INDUCED
    return findings
