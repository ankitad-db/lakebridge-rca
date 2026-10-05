"""Ingest AVF (Auto Validation Framework) output into normalized ``Finding`` objects.

AVF is a second supported validation tool (alongside Lakebridge reconcile). It writes
structured Delta "report" tables to a reports schema; this module reads one AVF *run*
(keyed by ``run_id``) and produces the SAME normalized model the rest of the engine
consumes (``Finding`` / ``MismatchSample`` / ``TableSummary``), so classify / drilldown /
lineage / fixes / FM-fallback / report all work unchanged.

AVF report tables consumed (see databricks-field-eng/databricks-auto-validator):

- ``avf_validation_summary``          one row per validated entity: counts, status,
                                      ``source_dialect`` (auto-selects the KB), ``primary_keys_used``.
- ``avf_validation_columns_mismatch`` one row per mismatched cell: ``source/target_column_value``,
                                      ``row_identifier`` (the PK), ``mismatch_type``, ``column_datatype``.
- ``avf_validation_rows_mismatch``    row presence: ``missing_in_target`` / ``missing_in_source``.
- ``avf_validation_schema_mismatch``  type/length/scale/nullable divergence per column.
- ``avf_validation_rca``              AVF's own row-count lineage RCA — consumed as EVIDENCE on
                                      our volume findings (not as a verdict), when ``consume_rca``.

Mapping to the normalized model mirrors ``rca_engine.ingest`` (the Lakebridge reader):
column-value diffs -> COLUMN_MISMATCH, row presence -> MISSING_IN_TARGET / MISSING_IN_SOURCE,
schema diffs -> SCHEMA. All best-effort: a missing table or empty run yields no findings.
"""

from __future__ import annotations

import json
import re
from typing import Any

from rca_engine.ingest import QueryRunner  # reuse the Protocol
from rca_engine.models import Evidence, Finding, MismatchSample, ReconType, TableSummary

_DATE_RE = re.compile(r"(date|dt|_ts|timestamp|time|day|month|year)", re.IGNORECASE)


def _esc(v: str) -> str:
    return str(v).replace("'", "''")


def _int(v: Any) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _bool(v: Any) -> bool:
    return str(v).lower() == "true"


def _fqn(catalog: Any, schema: Any, entity: Any) -> str:
    return ".".join(str(p) for p in (catalog, schema, entity) if p)


def _parse_keys(row_identifier: Any) -> dict[str, Any]:
    """AVF ``row_identifier`` is usually a JSON dict of PK col -> value; sometimes a bare
    value. Normalize to a dict so it matches the Lakebridge sample's ``keys`` shape."""
    if row_identifier is None:
        return {}
    if isinstance(row_identifier, dict):
        return row_identifier
    s = str(row_identifier)
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else {"_pk": obj}
    except (json.JSONDecodeError, ValueError):
        return {"_pk": s}


def _guess_date_col(names: list[str]) -> str | None:
    for n in names:
        if n and _DATE_RE.search(n):
            return n
    return None


def _matches(only_table: str, source_table: str, target_table: str) -> bool:
    t = only_table.strip().strip("`").lower()
    return t in {
        source_table.lower(), target_table.lower(),
        source_table.split(".")[-1].lower(), target_table.split(".")[-1].lower(),
    }


def ingest_avf(
    runner: QueryRunner,
    run_id: str,
    reports_schema: str,
    only_table: str | None = None,
    consume_rca: bool = True,
) -> tuple[list[Finding], list[TableSummary], str | None]:
    """Ingest one AVF run. Returns ``(findings, summaries, detected_dialect)``.

    ``reports_schema`` is the ``catalog.schema`` holding the ``avf_*`` tables. The detected
    dialect (from ``avf_validation_summary.source_dialect``) is returned so the caller can
    auto-select the knowledge base; ``None`` if the run has no rows.
    """
    rs = reports_schema.rstrip(".")
    rid = _esc(run_id)

    summary_rows = _q(runner, f"""
        SELECT source_catalog, source_schema, source_entity,
               target_catalog, target_schema, target_entity,
               source_dialect, source_total_rows, target_total_rows,
               source_only_rows, target_only_rows, mismatched_rows,
               primary_keys_used, schema_validation_status, overall_status
        FROM {rs}.avf_validation_summary WHERE run_id = '{rid}'""")
    if not summary_rows:
        return [], [], None

    detected_dialect = next((str(r.get("source_dialect")).lower()
                             for r in summary_rows if r.get("source_dialect")), None)

    col_rows = _q(runner, f"""
        SELECT target_catalog, target_schema, target_entity, source_catalog, source_schema, source_entity,
               source_column_name, target_column_name, source_column_value, target_column_value,
               row_identifier, mismatch_type, column_datatype, total_rows_with_column_mismatches
        FROM {rs}.avf_validation_columns_mismatch WHERE run_id = '{rid}'""")
    row_rows = _q(runner, f"""
        SELECT target_catalog, target_schema, target_entity,
               row_identifier, missing_in_target, missing_in_source, mismatched_columns
        FROM {rs}.avf_validation_rows_mismatch WHERE run_id = '{rid}'""")
    schema_rows = _q(runner, f"""
        SELECT target_catalog, target_schema, target_entity,
               source_column_name, target_column_name, source_data_type, target_data_type,
               source_length, target_length, source_scale, target_scale,
               source_nullable, target_nullable, mismatch_type, severity
        FROM {rs}.avf_validation_schema_mismatch WHERE run_id = '{rid}'""")
    rca_rows = _q(runner, f"""
        SELECT failed_table, cause_classification, confidence, primary_suspect, primary_suspect_edge,
               row_deficit, recommendations, upstream_notebooks, problematic_notebooks, problematic_jobs
        FROM {rs}.avf_validation_rca WHERE run_id = '{rid}'""") if consume_rca else []
    rca_by_table = {str(r.get("failed_table") or "").lower(): r for r in rca_rows}

    findings: list[Finding] = []
    summaries: list[TableSummary] = []

    for s in summary_rows:
        source_table = _fqn(s.get("source_catalog"), s.get("source_schema"), s.get("source_entity"))
        target_table = _fqn(s.get("target_catalog"), s.get("target_schema"), s.get("target_entity"))
        if only_table and not _matches(only_table, source_table, target_table):
            continue
        entity = str(s.get("target_entity") or "").lower()

        def _for_entity(rows: list[dict], ent: str = entity) -> list[dict]:
            return [r for r in rows if str(r.get("target_entity") or "").lower() == ent]

        source_count = _int(s.get("source_total_rows"))
        target_count = _int(s.get("target_total_rows"))
        missing_in_target = _int(s.get("source_only_rows"))   # in source, not target
        missing_in_source = _int(s.get("target_only_rows"))   # in target, not source
        schema_ok = str(s.get("schema_validation_status") or "PASS").upper() != "FAIL"
        join_keys = [k.strip() for k in str(s.get("primary_keys_used") or "").split(",") if k.strip()]
        common = dict(recon_id=run_id, source_table=source_table, target_table=target_table)

        # --- Column mismatches: one finding per (entity, target column). ---
        ecols = _for_entity(col_rows)
        by_col: dict[str, list[dict]] = {}
        for c in ecols:
            by_col.setdefault(str(c.get("target_column_name") or c.get("source_column_name")), []).append(c)
        mismatch_columns = [c for c in by_col if c]
        for col, cells in by_col.items():
            if not col:
                continue
            samples = [
                MismatchSample(
                    keys=_parse_keys(c.get("row_identifier")),
                    column=col,
                    source_value=c.get("source_column_value"),
                    target_value=c.get("target_column_value"),
                )
                for c in cells[:200]
            ]
            total_rows = max((_int(c.get("total_rows_with_column_mismatches")) for c in cells), default=0)
            findings.append(Finding(
                **common, recon_type=ReconType.COLUMN_MISMATCH, column=col,
                mismatch_count=total_rows or len(samples), total_count=source_count,
                samples=samples,
                metadata={"mismatch_type": cells[0].get("mismatch_type"),
                          "column_datatype": cells[0].get("column_datatype")},
            ))

        # --- Row presence. ---
        erows = _for_entity(row_rows)
        miss_tgt = [r for r in erows if _bool(r.get("missing_in_target"))]
        miss_src = [r for r in erows if _bool(r.get("missing_in_source"))]
        if missing_in_target or miss_tgt:
            f = Finding(
                **common, recon_type=ReconType.MISSING_IN_TARGET,
                mismatch_count=missing_in_target or len(miss_tgt), total_count=source_count,
                samples=[MismatchSample(keys=_parse_keys(r.get("row_identifier"))) for r in miss_tgt[:200]],
            )
            rca = rca_by_table.get(target_table.lower())
            if rca:
                f.metadata["avf_rca"] = rca   # surfaced as evidence in post_classify
            findings.append(f)
        if missing_in_source or miss_src:
            findings.append(Finding(
                **common, recon_type=ReconType.MISSING_IN_SOURCE,
                mismatch_count=missing_in_source or len(miss_src), total_count=target_count,
                samples=[MismatchSample(keys=_parse_keys(r.get("row_identifier"))) for r in miss_src[:200]],
            ))

        # --- Schema diffs: reshape to the Lakebridge schema-diff dict the classifier expects. ---
        eschema = _for_entity(schema_rows)
        if not schema_ok or eschema:
            diffs = [{
                "source_column": r.get("source_column_name"),
                "source_datatype": _typ(r.get("source_data_type"), r.get("source_length"), r.get("source_scale")),
                "databricks_column": r.get("target_column_name"),
                "databricks_datatype": _typ(r.get("target_data_type"), r.get("target_length"), r.get("target_scale")),
                "is_valid": "false",
                "mismatch_type": r.get("mismatch_type"),
                "severity": r.get("severity"),
            } for r in eschema]
            findings.append(Finding(
                **common, recon_type=ReconType.SCHEMA,
                mismatch_count=len(diffs),
                samples=[MismatchSample(keys=d) for d in diffs],
                metadata={"schema_diffs": diffs},
            ))

        candidate_names = list(mismatch_columns) + join_keys + \
            [str(r.get("mismatched_columns") or "") for r in erows]
        summaries.append(TableSummary(
            source_table=source_table, target_table=target_table,
            source_count=source_count, target_count=target_count,
            missing_in_source=missing_in_source, missing_in_target=missing_in_target,
            absolute_mismatch=_int(s.get("mismatched_rows")),
            mismatch_columns=mismatch_columns, schema_ok=schema_ok,
            join_keys=join_keys, date_column=_guess_date_col(candidate_names),
        ))

    # METRICS / BI_VALIDATION mode: AVF's aggregate (SUM/AVG/COUNT/variance) comparison lands
    # in avf_validation_bi_results, not the row/column tables. Ingest it as AGGREGATE findings
    # so this RCA covers *every* AVF comparison mode (PK_BASED, HASH_BASED, METRICS/BI).
    for f in _bi_findings(runner, rs, rid, run_id, only_table):
        findings.append(f)
        if f.target_table and f.target_table not in {s.target_table for s in summaries}:
            summaries.append(TableSummary(source_table=f.source_table, target_table=f.target_table))

    return findings, summaries, detected_dialect


def _bi_findings(runner: QueryRunner, rs: str, rid: str, run_id: str,
                 only_table: str | None) -> list[Finding]:
    """AVF METRICS/BI results -> AGGREGATE findings (one per mismatching BI metric)."""
    bi = _q(runner, f"""
        SELECT query_name, status, source_total, target_total, variance_pct, variance_absolute,
               tolerance_threshold, comparison_type, grain_columns, metric_columns,
               source_system, report_name
        FROM {rs}.avf_validation_bi_results WHERE run_id = '{rid}'""")
    out: list[Finding] = []
    for b in bi:
        if str(b.get("status") or "").upper() in ("PASS", ""):
            continue   # only surface metrics outside tolerance
        tbl = str(b.get("report_name") or b.get("query_name") or "bi_report")
        if only_table and only_table.strip().lower() not in tbl.lower():
            continue
        metric = str(b.get("metric_columns") or b.get("query_name") or "metric")
        out.append(Finding(
            recon_id=run_id, source_table=tbl, target_table=tbl,
            recon_type=ReconType.AGGREGATE, column=metric,
            mismatch_count=_int(b.get("variance_absolute")),
            samples=[MismatchSample(keys={"metric": metric}, column=metric,
                                    source_value=b.get("source_total"),
                                    target_value=b.get("target_total"))],
            metadata={"agg_type": b.get("comparison_type"), "group_by": b.get("grain_columns"),
                      "variance_pct": b.get("variance_pct"),
                      "tolerance": b.get("tolerance_threshold"),
                      "source_system": b.get("source_system")},
        ))
    return out


def _typ(dtype: Any, length: Any, scale: Any) -> str:
    """Compose a readable type string from AVF's split type/length/scale columns."""
    base = str(dtype or "").strip()
    if not base:
        return ""
    ln, sc = _int(length), _int(scale)
    if sc and ln:
        return f"{base}({ln},{sc})"
    if ln:
        return f"{base}({ln})"
    return base


def attach_avf_rca_evidence(findings: list[Finding]) -> None:
    """Post-classify hook: turn AVF's own row-count RCA (stored in metadata by ingest) into
    an Evidence on our volume finding's top hypothesis — AVF's lineage cause as corroboration,
    never as our verdict (our classifier decides migration-vs-genuine)."""
    for f in findings:
        rca = f.metadata.get("avf_rca")
        if not rca:
            continue
        top = f.top_hypothesis
        if top is None:
            continue
        cause = rca.get("cause_classification") or "UNKNOWN"
        conf = rca.get("confidence")
        suspect = rca.get("primary_suspect") or rca.get("primary_suspect_edge") or ""
        recs = rca.get("recommendations")
        if isinstance(recs, str):
            recs = [recs]
        detail = f"AVF row-count RCA: {cause}"
        if suspect:
            detail += f" at {suspect}"
        if conf is not None:
            detail += f" (confidence {conf})"
        top.evidence.append(Evidence(
            label="avf_rca", detail=detail,
            data={"cause": cause, "primary_suspect": suspect, "confidence": conf,
                  "recommendations": recs or [],
                  "upstream_notebooks": rca.get("upstream_notebooks"),
                  "problematic_notebooks": rca.get("problematic_notebooks"),
                  "problematic_jobs": rca.get("problematic_jobs")},
        ))


def _q(runner: QueryRunner, sql: str) -> list[dict[str, Any]]:
    """Run a query, swallowing a missing-table / access error so one absent AVF table
    (e.g. no schema mismatches written) never fails the whole ingest."""
    try:
        return runner.query(sql) or []
    except Exception as exc:  # noqa: BLE001 - best-effort per table
        print(f"[ingest_avf] query skipped: {str(exc)[:160]}")
        return []
