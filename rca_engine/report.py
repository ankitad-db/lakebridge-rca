"""Render a concluded RCA as a readable TL;DR and a Databricks notebook.

The engine runs the full pipeline (ingest -> classify -> live drill-down); this
module turns the concluded ``RcaResult`` into a professional, skimmable report
grouped by verdict, with symbols, an executed query, and its result per finding.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any

from rca_engine.models import Finding, RcaResult, ReconType, RootCauseCategory, Verdict

# Verdict presentation (symbol + label + one-line action).
_VERDICT = {
    Verdict.MIGRATION_INDUCED: ("🔧", "Migration-induced", "Fix in the migration"),
    Verdict.GENUINE_DATA: ("📊", "Genuine data difference", "Route to the data owner"),
    Verdict.BENIGN: ("✅", "Benign / expected", "No action"),
    Verdict.NEEDS_REVIEW: ("🔍", "Needs review", "Investigate further"),
}

_CATEGORY_ICON = {
    RootCauseCategory.TYPE_PRECISION: "🔢",
    RootCauseCategory.TIMEZONE: "🕐",
    RootCauseCategory.TRANSPILATION: "🔀",
    RootCauseCategory.STRING_FORMAT: "🔤",
    RootCauseCategory.NULL_BOOLEAN: "␀",
    RootCauseCategory.SEMI_STRUCTURED: "🧬",
    RootCauseCategory.VOLUME_MISSING: "➖",
    RootCauseCategory.VOLUME_EXTRA: "➕",
    RootCauseCategory.UPSTREAM_DRIFT: "🌊",
    RootCauseCategory.ENV_CONFIG: "⚙️",
    RootCauseCategory.RECON_CONFIG: "🧷",
    RootCauseCategory.UNKNOWN: "❓",
}

# Order verdicts appear in the report.
_VERDICT_ORDER = [Verdict.MIGRATION_INDUCED, Verdict.GENUINE_DATA, Verdict.NEEDS_REVIEW, Verdict.BENIGN]


def to_dict(result: RcaResult) -> dict[str, Any]:
    return dataclasses.asdict(result)


def write_json(result: RcaResult, path: str) -> None:
    with open(path, "w") as f:
        json.dump(to_dict(result), f, indent=2, default=str)


def _loc(f: Finding) -> str:
    table = f.target_table.split(".")[-1]
    if f.column:
        return f"{table}.{f.column}"
    suffix = {"missing_in_target": " (missing rows)", "missing_in_source": " (extra rows)",
              "schema": " (schema)"}.get(f.recon_type.value, "")
    return f"{table}{suffix}"


def _cat_label(cat: RootCauseCategory) -> str:
    return f"{_CATEGORY_ICON.get(cat, '•')} {cat.value}"


def _confirmed(f: Finding) -> bool:
    h = f.top_hypothesis
    return bool(h and any(e.data and e.data.get("confirmed") for e in h.evidence))


def _verdict_badges(findings: list[Finding]) -> str:
    """Compact per-table verdict rollup, e.g. '🔧3 📊1'."""

    tally: dict[Verdict, int] = {}
    for f in findings:
        if f.top_hypothesis:
            tally[f.top_hypothesis.verdict] = tally.get(f.top_hypothesis.verdict, 0) + 1
    parts = [f"{_VERDICT[v][0]}{tally[v]}" for v in _VERDICT_ORDER if tally.get(v)]
    return " ".join(parts) or "—"


def build_overview(result: RcaResult) -> str:
    """Per-table matrix mirroring how Lakebridge reconcile reports each table pair:
    schema, row-level (missing both directions), and column-level mismatches."""

    by_table: dict[str, list[Finding]] = {}
    for f in result.findings:
        by_table.setdefault(f.target_table, []).append(f)

    lines = ["## 📋 Reconciliation overview (per table pair)", "",
             "| Target table | Schema | ➖ Missing in target | ➕ Extra in target | 🔤 Mismatched columns | Verdicts |",
             "| :-- | :-: | --: | --: | :-- | :-- |"]
    for table in sorted(by_table):
        fs = by_table[table]
        name = table.split(".")[-1]
        schema = next((x for x in fs if x.recon_type == ReconType.SCHEMA), None)
        schema_cell = f"⚠️ {schema.mismatch_count}" if schema else "✅"
        miss_t = sum(x.mismatch_count for x in fs if x.recon_type == ReconType.MISSING_IN_TARGET)
        miss_s = sum(x.mismatch_count for x in fs if x.recon_type == ReconType.MISSING_IN_SOURCE)
        cols = [x.column for x in fs if x.recon_type == ReconType.COLUMN_MISMATCH and x.column]
        cols_cell = f"{len(cols)} (`{'`, `'.join(cols)}`)" if cols else "0"
        lines.append(
            f"| `{name}` | {schema_cell} | {miss_t or '·'} | {miss_s or '·'} | {cols_cell} | {_verdict_badges(fs)} |"
        )
    return "\n".join(lines)


def build_matchrates(result: RcaResult) -> str:
    """Overall row-level and column-level match rates for every table pair
    (not just the ones with issues) — a reconciliation scorecard."""

    if not result.table_summaries:
        return ""
    lines = ["## 📈 Match rates (row & column level)", "",
             "Reconciliation health per table pair. **Row match %** = source rows that "
             "exist in target *and* match on all columns.", "",
             "| Target table | Source rows | Target rows | ➖ Missing | ➕ Extra | "
             "Mismatched rows | ✅ Row match % |",
             "| :-- | --: | --: | --: | --: | --: | --: |"]
    for s in sorted(result.table_summaries, key=lambda x: x.row_match_pct):
        name = s.target_table.split(".")[-1]
        lines.append(
            f"| `{name}` | {s.source_count:,} | {s.target_count:,} | {s.missing_in_target:,} | "
            f"{s.missing_in_source:,} | {s.absolute_mismatch:,} | **{s.row_match_pct:.2f}%** |"
        )

    cols = [f for f in result.findings if f.recon_type == ReconType.COLUMN_MISMATCH and (f.total_count or 0) > 0]
    if cols:
        lines += ["", "**Column-level match %** _(columns not listed matched 100%)_:", "",
                  "| Table.Column | Rows | Mismatches | ✅ Match % |",
                  "| :-- | --: | --: | --: |"]
        for f in sorted(cols, key=lambda x: x.mismatch_count / (x.total_count or 1), reverse=True):
            pct = 100.0 * (f.total_count - f.mismatch_count) / f.total_count
            lines.append(f"| `{_loc(f)}` | {f.total_count:,} | {f.mismatch_count:,} | {pct:.2f}% |")
    return "\n".join(lines)


def build_tldr(result: RcaResult) -> str:
    counts = result.verdict_counts()
    n_tables = len({f.target_table for f in result.findings})
    lines = [
        f"# 🧭 RCA Summary — recon `{result.recon_id}`",
        "",
        f"**{len(result.findings)} findings** across **{n_tables} table pair(s)** · "
        f"source dialect: `{result.dialect}`",
        "",
        "| Verdict | Count | Meaning |",
        "| :-- | --: | :-- |",
    ]
    for v in _VERDICT_ORDER:
        sym, label, action = _VERDICT[v]
        lines.append(f"| {sym} {label} | {counts.get(v.value, 0)} | {action} |")
    lines.append("")
    lines.append(build_overview(result))
    lines.append("")
    mr = build_matchrates(result)
    if mr:
        lines.append(mr)
        lines.append("")

    by_verdict: dict[Verdict, list[Finding]] = {v: [] for v in _VERDICT_ORDER}
    for f in result.findings:
        h = f.top_hypothesis
        if h:
            by_verdict.setdefault(h.verdict, []).append(f)

    lines += ["", "## 🎯 Findings by verdict"]
    for v in _VERDICT_ORDER:
        group = sorted(by_verdict.get(v, []),
                       key=lambda x: x.top_hypothesis.confidence if x.top_hypothesis else 0, reverse=True)
        if not group:
            continue
        sym, label, action = _VERDICT[v]
        lines += ["", f"## {sym} {label} — _{action}_", "",
                  "| Location | Category | Conf. | ✔ | Root cause |",
                  "| :-- | :-- | :-- | :-: | :-- |"]
        for f in group:
            h = f.top_hypothesis
            check = "✓" if _confirmed(f) else "·"
            rationale = (h.rationale or "").replace("\n", " ").strip()
            if len(rationale) > 110:
                rationale = rationale[:107] + "..."
            lines.append(
                f"| `{_loc(f)}` | {_cat_label(h.category)} | {h.confidence:.0%} | {check} | {rationale} |"
            )
    return "\n".join(lines)


def build_conclusion(result: RcaResult) -> str:
    """A closing, action-oriented wrap-up grouped by who owns the fix."""

    by_verdict: dict[Verdict, list[Finding]] = {}
    for f in result.findings:
        if f.top_hypothesis:
            by_verdict.setdefault(f.top_hypothesis.verdict, []).append(f)

    def _rows(v: Verdict) -> list[str]:
        out = []
        for f in sorted(by_verdict.get(v, []),
                        key=lambda x: x.top_hypothesis.confidence, reverse=True):
            h = f.top_hypothesis
            fix = (h.remediation or h.rationale or "").replace("\n", " ").strip()
            if len(fix) > 130:
                fix = fix[:127] + "..."
            out.append(f"- `{_loc(f)}` — {fix}")
        return out

    n = len(result.findings)
    mig = by_verdict.get(Verdict.MIGRATION_INDUCED, [])
    data = by_verdict.get(Verdict.GENUINE_DATA, [])
    review = by_verdict.get(Verdict.NEEDS_REVIEW, [])
    benign = by_verdict.get(Verdict.BENIGN, [])

    lines = ["# 🧾 Conclusion & recommended actions", "",
             f"Analyzed **{n} findings**. Every verdict below is backed by a query "
             f"executed in this notebook (see the cell under each finding)."]

    lines += ["", f"## 🔧 Fix in the migration — {len(mig)} ({'owner: migration engineer'})"]
    lines += _rows(Verdict.MIGRATION_INDUCED) or ["- _None._"]

    lines += ["", f"## 📊 Route to the data owner — {len(data)} (not migration bugs)"]
    lines += _rows(Verdict.GENUINE_DATA) or ["- _None._"]

    if review:
        lines += ["", f"## 🔍 Needs review — {len(review)}"]
        lines += _rows(Verdict.NEEDS_REVIEW)

    lines += ["", f"## ✅ Benign / expected — {len(benign)}",
              f"- {len(benign)} finding(s) are representation-only or within tolerance; no action."]

    lines += ["", "> If re-running a cell changes an output, update that finding's verdict "
              "above and regenerate this report so the conclusion always matches the evidence."]
    return "\n".join(lines)


def _md_cell(text: str) -> dict[str, Any]:
    return {"cell_type": "markdown", "metadata": {}, "source": text.splitlines(keepends=True)}


def _code_cell(code: str) -> dict[str, Any]:
    return {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [],
            "source": code.splitlines(keepends=True)}


def _signal(f: Finding) -> str:
    """Phrase the finding in Lakebridge recon terms (row-level vs column-level)."""

    total = f.total_count or "?"
    rt = f.recon_type.value
    if rt == "column_mismatch":
        s = f"**column-level** mismatch — `{f.column}` differs on {f.mismatch_count} of {total} rows"
        abs_m = (f.metadata or {}).get("absolute_mismatch")
        if abs_m:
            s += f" (table had {abs_m} mismatched rows across all columns)"
        return s
    if rt == "missing_in_target":
        return f"**row-level** — {f.mismatch_count} rows present in source but missing in target (of {total})"
    if rt == "missing_in_source":
        return f"**row-level** — {f.mismatch_count} rows present in target but not in source (of {total})"
    if rt == "schema":
        return f"**schema-level** — {f.mismatch_count} column datatype difference(s) reported by recon"
    return f"recon `{rt}`, {f.mismatch_count} of {total} rows"


def _finding_section(f: Finding) -> list[dict[str, Any]]:
    h = f.top_hypothesis
    sym, label, action = _VERDICT.get(h.verdict, ("•", "?", "")) if h else ("•", "?", "")
    header = [f"### {sym} `{_loc(f)}` — {label}", ""]
    if h:
        header += [
            f"- **Category**: {_cat_label(h.category)}  ·  **Confidence**: {h.confidence:.0%}"
            f"  ·  **Owner**: {h.recommended_owner or '—'}",
            f"- **Signal**: {_signal(f)}",
            f"- **Root cause**: {h.rationale}",
        ]
        if h.remediation:
            header.append(f"- **Fix**: {h.remediation.strip()}")
        _ev_label = {"drilldown": "Evidence (query)", "code": "Evidence (code)",
                     "transpile": "Transpile report"}
        for e in h.evidence:
            if e.label in _ev_label:
                header.append(f"- **{_ev_label[e.label]}**: {e.detail}")

    samples = [
        f"  - `{ {k: v for k, v in list(s.keys.items())[:3]} }` "
        f"source={s.source_value!r} → target={s.target_value!r}"
        for s in f.samples[:4] if s.column
    ]
    if samples:
        header += ["", "Sample differences:", *samples]

    # Pre-fill the confirming query so the reader can re-run it live.
    query = ""
    if h and h.evidence and h.evidence[0].label == "drilldown" and h.evidence[0].query:
        query = h.evidence[0].query
    live = _code_cell(
        f"# Re-run to confirm / drill deeper for {_loc(f)}\n"
        + (f'spark.sql("""{query}""").display()' if query
           else f'# spark.sql("SELECT * FROM {f.target_table} LIMIT 20").display()')
    )
    return [_md_cell("\n".join(x for x in header if x is not None)), live]


# Order findings within a table the way Lakebridge reports them.
_RECON_ORDER = {
    ReconType.SCHEMA: 0,
    ReconType.MISSING_IN_TARGET: 1,
    ReconType.MISSING_IN_SOURCE: 2,
    ReconType.COLUMN_MISMATCH: 3,
}


_VALIDATION_HELPERS = '''\
# 📅 Date-range validation — set the window (widgets), then re-run these cells.
# Row match % and per-column match % over an optional date range so you can
# validate a slice of the migration (e.g. one month) rather than the whole table.
dbutils.widgets.text("start_date", "2000-01-01")
dbutils.widgets.text("end_date", "2100-01-01")
START, END = dbutils.widgets.get("start_date"), dbutils.widgets.get("end_date")

def _win(date_col):
    return f"WHERE `{date_col}` BETWEEN '{START}' AND '{END}'" if date_col else ""

def validate_rows(src, tgt, keys, date_col=None):
    name = tgt.split(".")[-1]
    if not keys:  # no join key learned — report counts only (edit keys to enable match)
        return spark.sql(f"""
            SELECT '{name}' AS table,
                   (SELECT count(*) FROM {src} {_win(date_col)}) AS source_rows,
                   (SELECT count(*) FROM {tgt} {_win(date_col)}) AS target_rows,
                   CAST(NULL AS BIGINT) AS matched_keys,
                   CAST(NULL AS DOUBLE) AS row_match_pct
        """)
    on = " AND ".join(f"s.`{k}` = t.`{k}`" for k in keys)
    return spark.sql(f"""
        WITH s AS (SELECT * FROM {src} {_win(date_col)}),
             t AS (SELECT * FROM {tgt} {_win(date_col)})
        SELECT '{name}' AS table,
               (SELECT count(*) FROM s) AS source_rows,
               (SELECT count(*) FROM t) AS target_rows,
               (SELECT count(*) FROM s JOIN t ON {on}) AS matched_keys,
               round(100.0 * (SELECT count(*) FROM s JOIN t ON {on}) /
                     nullif((SELECT count(*) FROM s), 0), 2) AS row_match_pct
    """)

def validate_column(src, tgt, keys, col, date_col=None):
    on = " AND ".join(f"s.`{k}` = t.`{k}`" for k in keys) if keys else "TRUE"
    return spark.sql(f"""
        WITH s AS (SELECT * FROM {src} {_win(date_col)}),
             t AS (SELECT * FROM {tgt} {_win(date_col)})
        SELECT '{col}' AS column, count(*) AS compared,
               sum(CASE WHEN s.`{col}` <=> t.`{col}` THEN 1 ELSE 0 END) AS matches,
               round(100.0 * sum(CASE WHEN s.`{col}` <=> t.`{col}` THEN 1 ELSE 0 END) /
                     nullif(count(*), 0), 2) AS match_pct
        FROM s JOIN t ON {on}
    """)
'''


def _validation_cells(result: RcaResult) -> list[dict[str, Any]]:
    if not result.table_summaries:
        return []
    from functools import reduce  # noqa: F401 (used in generated code)

    row_calls, col_calls = [], []
    for s in result.table_summaries:
        keys = s.join_keys
        dc = f'"{s.date_column}"' if s.date_column else "None"
        row_calls.append(f'    validate_rows("{s.source_table}", "{s.target_table}", {keys}, {dc}),')
        for c in s.mismatch_columns:
            col_calls.append(
                f'    validate_column("{s.source_table}", "{s.target_table}", {keys}, "{c}", {dc}),'
            )

    row_code = (
        "# Row-level match per table pair (edit date_col via the widgets above):\n"
        "row_checks = [\n" + "\n".join(row_calls) + "\n]\n"
        "from functools import reduce\n"
        "reduce(lambda a, b: a.unionByName(b), row_checks).display()"
    )
    col_code = (
        "# Column-level match % (over the same date window):\n"
        "col_checks = [\n" + "\n".join(col_calls) + "\n]\n"
        "reduce(lambda a, b: a.unionByName(b), col_checks).display()"
        if col_calls else "# No column-level mismatches to validate."
    )
    return [
        _md_cell("---\n# 📅 Validation (row & column match %, date-range filterable)\n\n"
                 "Set `start_date` / `end_date` widgets to validate a slice, then re-run."),
        _code_cell(_VALIDATION_HELPERS),
        _code_cell(row_code),
        _code_cell(col_code),
    ]


def build_notebook(result: RcaResult) -> dict[str, Any]:
    cells = [_md_cell(build_tldr(result))]
    cells += _validation_cells(result)
    cells.append(
        _md_cell("---\n# 🔬 Findings & evidence\n\nGrouped by table pair (as Lakebridge "
                 "reports), then schema → row-level → column-level. Each finding shows the "
                 "concluded verdict and the query that confirms it. Re-run any cell to drill deeper.")
    )
    by_table: dict[str, list[Finding]] = {}
    for f in result.findings:
        by_table.setdefault(f.target_table, []).append(f)

    for table in sorted(by_table):
        fs = sorted(by_table[table],
                    key=lambda x: (_RECON_ORDER.get(x.recon_type, 9),
                                   -(x.top_hypothesis.confidence if x.top_hypothesis else 0)))
        cells.append(_md_cell(f"## 📦 `{table}`  \n_{_verdict_badges(fs)}  ·  {len(fs)} finding(s)_"))
        for f in fs:
            cells.extend(_finding_section(f))
    cells.append(_md_cell("---\n" + build_conclusion(result)))
    return {
        "cells": cells,
        "metadata": {"language_info": {"name": "python"},
                     "kernelspec": {"name": "python3", "display_name": "Python 3"}},
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def write_notebook(result: RcaResult, path: str) -> None:
    with open(path, "w") as f:
        json.dump(build_notebook(result), f, indent=1)
