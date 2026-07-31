"""Turn a concluded finding into a concrete, runnable fix.

Remediation text tells a reader *what* to do; this module produces the *how* — the
corrected transform expression, a recon-config change, or a load/back-fill statement
they can review and run. Fixes are **deterministic** (built from the finding's category,
its code-derivation evidence, declared source type, and join keys) and are always
**suggestions**: the engine attaches them, a human runs them.

Each category maps to a fix template:
- ``type_precision`` → widen the target cast to the source scale.
- ``timezone``       → normalize to UTC on load.
- ``string_format``  → align TRIM/case in the transform.
- ``null_boolean``   → explicit NULL/boolean mapping.
- ``volume_missing`` → a back-fill (LEFT ANTI JOIN) statement.
- ``volume_extra``   → a de-duplicate (QUALIFY row_number) rewrite.
- ``semi_structured``→ a recon-config normalization/tolerance (representation-only).
- ``transpilation``  → surface the target derivation to correct by hand.

When the inputs needed for a precise fix aren't present (e.g. no derivation captured),
the builder returns a best-effort scaffold with the pieces it does know, or ``None``.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from rca_engine.models import Evidence, Finding, Fix, ReconType, RootCauseCategory

_SCALE_RE = re.compile(r"\(\s*\d+\s*,\s*(\d+)\s*\)")
_DECLARED_RE = re.compile(r"declared\s+`([^`]+)`", re.IGNORECASE)


def _scale(type_or_expr: str | None) -> Optional[int]:
    if not type_or_expr:
        return None
    m = _SCALE_RE.search(type_or_expr)
    return int(m.group(1)) if m else None


def _derivation(finding: Finding) -> tuple[Optional[str], list[str]]:
    """The transpiled target expression + its functions, if the code-correlation pass
    attached them."""
    top = finding.top_hypothesis
    if not top:
        return None, []
    for e in top.evidence:
        if e.label == "code" and e.data and e.data.get("expr"):
            return e.data.get("expr"), [str(x) for x in (e.data.get("functions") or [])]
    return None, []


def _declared_source_type(finding: Finding) -> Optional[str]:
    top = finding.top_hypothesis
    if not top:
        return None
    for e in top.evidence:
        if e.label == "code":
            m = _DECLARED_RE.search(e.detail or "")
            if m:
                return m.group(1)
    return None


def _join_keys(finding: Finding) -> list[str]:
    for s in finding.samples:
        if s.keys:
            return list(s.keys.keys())
    return []


def _on(finding: Finding) -> tuple[str, list[str]]:
    keys = _join_keys(finding)
    return " AND ".join(f"s.`{k}` = t.`{k}`" for k in keys), keys


def _col(finding: Finding) -> str:
    return finding.column or "<col>"


def _fix_type_precision(f: Finding) -> Optional[Fix]:
    col = _col(f)
    expr, _ = _derivation(f)
    src_type = _declared_source_type(f)
    src_scale = _scale(src_type)
    tgt_scale = _scale(expr)
    # Only a confident, precise fix when we can see the scale actually dropped.
    if src_scale is not None and tgt_scale is not None and tgt_scale < src_scale:
        corrected = re.sub(_SCALE_RE, f"(38,{src_scale})", expr, count=1) if expr else \
            f"CAST(`{col}` AS DECIMAL(38,{src_scale}))"
        on, keys = _on(f)
        vq = ""
        if keys:
            vq = (f"SELECT (count(*) = sum(CASE WHEN round(cast(s.`{col}` AS double), {tgt_scale}) "
                  f"= cast(t.`{col}` AS double) THEN 1 ELSE 0 END)) AS confirmed, count(*) AS n "
                  f"FROM {f.source_table} s JOIN {f.target_table} t ON {on} "
                  f"WHERE s.`{col}` <> t.`{col}`")
        return Fix(
            title=f"Widen `{col}` cast to preserve scale {src_scale}",
            kind="widen_cast", target="transform",
            sql=f"-- Source `{col}` is {src_type} (scale {src_scale}); target rounds to "
                f"scale {tgt_scale}.\n-- In the migrated transform, change the cast to keep "
                f"full scale:\n{corrected}",
            rationale=f"Restores the {src_scale - tgt_scale} lost decimal place(s).",
            confidence=0.85, validation_query=vq,
        )
    return Fix(
        title=f"Match `{col}` numeric type to source precision/scale",
        kind="widen_cast", target="transform",
        sql=f"-- Align the target type of `{col}` with the source"
            + (f" ({src_type})" if src_type else "")
            + f":\nCAST(`{col}` AS DECIMAL(38, <source_scale>))",
        rationale="Cast to the source scale so no decimals are truncated.",
        confidence=0.5,
    )


def _fix_timezone(f: Finding) -> Fix:
    col = _col(f)
    on, keys = _on(f)
    vq = ""
    if keys:
        vq = (f"SELECT (count(DISTINCT unix_timestamp(t.`{col}`) - unix_timestamp(s.`{col}`)) = 1) "
              f"AS confirmed, count(*) AS n FROM {f.source_table} s JOIN {f.target_table} t ON {on} "
              f"WHERE s.`{col}` <> t.`{col}`")
    return Fix(
        title=f"Normalize `{col}` to UTC on load",
        kind="tz_normalize", target="transform",
        sql=f"-- The source is a zoned/session timestamp; store UTC to match.\n"
            f"-- Replace the target derivation of `{col}` with an explicit conversion, e.g.:\n"
            f"to_utc_timestamp(`{col}`, 'America/Los_Angeles')  -- use the source session TZ",
        rationale="A constant offset means a single timezone normalization aligns all rows.",
        confidence=0.7, validation_query=vq,
    )


def _fix_string_format(f: Finding) -> Fix:
    col = _col(f)
    on, keys = _on(f)
    vq = ""
    if keys:
        vq = (f"SELECT (count(*) = sum(CASE WHEN trim(lower(s.`{col}`)) = trim(lower(t.`{col}`)) "
              f"THEN 1 ELSE 0 END)) AS confirmed, count(*) AS n FROM {f.source_table} s JOIN "
              f"{f.target_table} t ON {on} WHERE s.`{col}` <> t.`{col}`")
    return Fix(
        title=f"Align TRIM/case for `{col}`",
        kind="trim_case", target="transform",
        sql=f"-- Difference is trim/case only. Match the source's representation in the\n"
            f"-- target transform (drop an added UPPER()/LOWER(), or apply TRIM), e.g.:\n"
            f"trim(`{col}`)",
        rationale="Removes a formatting-only divergence introduced by the transform.",
        confidence=0.65, validation_query=vq,
    )


def _fix_null_boolean(f: Finding) -> Fix:
    col = _col(f)
    return Fix(
        title=f"Explicit NULL/boolean mapping for `{col}`",
        kind="null_boolean", target="transform",
        sql=f"-- Map the source encoding explicitly instead of an implicit cast:\n"
            f"CASE WHEN `{col}` IN ('Y','y','1','true','T') THEN true\n"
            f"     WHEN `{col}` IN ('N','n','0','false','F') THEN false\n"
            f"     WHEN `{col}` IS NULL THEN NULL END AS `{col}`",
        rationale="Preserves NULL vs empty and normalizes Y/N-style flags to boolean.",
        confidence=0.6,
    )


def _fix_volume_missing(f: Finding) -> Fix:
    on, keys = _on(f)
    on = on or "s.<key> = t.<key>"
    vq = ""
    if keys:
        vq = (f"SELECT (count(*) > 0) AS confirmed, count(*) AS n "
              f"FROM {f.source_table} s LEFT ANTI JOIN {f.target_table} t ON {on}")
    return Fix(
        title="Back-fill the rows missing in target",
        kind="backfill", target="load",
        sql=f"-- Insert source rows absent from target (advance the watermark / back-fill):\n"
            f"INSERT INTO {f.target_table}\n"
            f"SELECT s.* FROM {f.source_table} s\n"
            f"LEFT ANTI JOIN {f.target_table} t ON {on};",
        rationale="Loads exactly the keys present in source but missing in target.",
        confidence=0.6 if keys else 0.4, validation_query=vq,
    )


def _fix_volume_extra(f: Finding) -> Fix:
    keys = _join_keys(f)
    part = ", ".join(f"`{k}`" for k in keys) if keys else "`<key>`"
    vq = ""
    if keys:
        concat = "concat_ws('|', " + ", ".join(f"`{k}`" for k in keys) + ")"
        vq = (f"SELECT ((count(*) - count(DISTINCT {concat})) > 0) AS confirmed, "
              f"(count(*) - count(DISTINCT {concat})) AS n FROM {f.target_table}")
    return Fix(
        title="De-duplicate the extra target rows",
        kind="dedup", target="load",
        sql=f"-- Make the load idempotent — keep one row per key:\n"
            f"CREATE OR REPLACE TABLE {f.target_table} AS\n"
            f"SELECT * EXCEPT(_rn) FROM (\n"
            f"  SELECT *, row_number() OVER (PARTITION BY {part} ORDER BY 1) AS _rn\n"
            f"  FROM {f.target_table}\n"
            f") WHERE _rn = 1;",
        rationale="Removes fan-out/non-idempotent duplicates while preserving one row per key.",
        confidence=0.55 if keys else 0.35, validation_query=vq,
    )


def _fix_semi_structured(f: Finding) -> Fix:
    col = _col(f)
    return Fix(
        title=f"Normalize `{col}` in the recon comparison (representation-only)",
        kind="recon_normalize", target="recon_config",
        sql=f"-- Values are semantically equal (e.g. JSON key order). Normalize both sides\n"
            f"-- in the reconcile transform so it stops flagging a cosmetic diff:\n"
            f"to_json(from_json(`{col}`, schema_of_json(`{col}`)))",
        rationale="Canonicalizes serialization so equal objects compare equal.",
        confidence=0.6,
    )


def _fix_transpilation(f: Finding) -> Optional[Fix]:
    col = _col(f)
    expr, funcs = _derivation(f)
    if not expr:
        return None
    fn = f" (functions: {', '.join(funcs)})" if funcs else ""
    return Fix(
        title=f"Correct the translated derivation of `{col}`",
        kind="fix_transpile", target="transform",
        sql=f"-- The transpiled target derivation differs semantically from the source{fn}:\n"
            f"--   {expr}\n"
            f"-- Rewrite it to the Databricks equivalent of the source expression, then re-run recon.",
        rationale="A code-translation difference must be corrected in the migrated SQL.",
        confidence=0.5,
    )


_BUILDERS = {
    RootCauseCategory.TYPE_PRECISION: _fix_type_precision,
    RootCauseCategory.TIMEZONE: _fix_timezone,
    RootCauseCategory.STRING_FORMAT: _fix_string_format,
    RootCauseCategory.NULL_BOOLEAN: _fix_null_boolean,
    RootCauseCategory.VOLUME_MISSING: _fix_volume_missing,
    RootCauseCategory.VOLUME_EXTRA: _fix_volume_extra,
    RootCauseCategory.SEMI_STRUCTURED: _fix_semi_structured,
    RootCauseCategory.TRANSPILATION: _fix_transpilation,
}


def build_fix(finding: Finding) -> Optional[Fix]:
    """Deterministic fix for a finding's top hypothesis, or ``None`` when the category
    has no actionable code/load fix (or inputs are insufficient)."""

    top = finding.top_hypothesis
    if top is None:
        return None
    builder = _BUILDERS.get(top.category)
    if builder is None:
        return None
    try:
        return builder(finding)
    except Exception:  # a fix builder must never break the pipeline
        return None


def generate_fixes(findings: list[Finding]) -> list[Finding]:
    """Attach a suggested ``Fix`` to every finding whose category has one. Schema-only
    findings are skipped (they're resolved by correcting the type mapping, already
    covered by the type_precision fix on the column findings)."""

    for f in findings:
        if f.recon_type == ReconType.SCHEMA:
            continue
        top = f.top_hypothesis
        if top is None:
            continue
        fix = build_fix(f)
        if fix is not None:
            top.fix = fix
            # Surface a one-line pointer in the evidence stream too, so the provenance
            # and conclusion can reference that a concrete fix exists.
            top.evidence.append(Evidence(label="fix", detail=f"Suggested fix: {fix.title}",
                                         data={"kind": fix.kind, "target": fix.target}))
    return findings


def _truthy(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, str):
        return v.strip().lower() in {"1", "true", "t", "yes", "y"}
    return bool(v)


def validate_fix(finding: Finding, runner: Any) -> bool:
    """Fix-validation gate: run the fix's ``validation_query`` and mark it validated iff
    the query confirms the gap this fix addresses is the *entire* difference (so applying
    the fix would close it). Best-effort — a missing query or a failure leaves the fix an
    unvalidated suggestion. Returns whether it was validated."""

    top = finding.top_hypothesis
    fix = top.fix if top else None
    if fix is None or not fix.validation_query:
        return False
    try:
        rows = runner.query(fix.validation_query)
        row = rows[0] if rows else {}
        confirmed = _truthy(row.get("confirmed"))
        n = row.get("n")
    except Exception as exc:
        fix.validation = f"Validation query failed: {exc}"
        return False
    fix.validated = confirmed
    fix.validation = (
        "Validated: the entire gap is explained by this mechanism"
        + (f" ({int(n)} rows checked)" if n is not None else "")
        + " — applying the fix closes it."
        if confirmed else
        "Not fully validated: the gap is not entirely explained by this mechanism; "
        "review before applying."
    )
    return confirmed


def validate_all_fixes(findings: list[Finding], runner: Any) -> list[Finding]:
    """Run the validation gate for every finding that has a fix with a validation query."""
    for f in findings:
        top = f.top_hypothesis
        if top and top.fix and top.fix.validation_query:
            try:
                validate_fix(f, runner)
            except Exception:
                continue
    return findings
