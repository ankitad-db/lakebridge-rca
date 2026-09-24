"""Render a concluded RCA as a readable TL;DR and a Databricks notebook.

The engine runs the full pipeline (ingest -> classify -> live drill-down); this
module turns the concluded ``RcaResult`` into a professional, skimmable report
grouped by verdict, with symbols, an executed query, and its result per finding.
"""

from __future__ import annotations

import dataclasses
import json
import re
from typing import Any

from rca_engine.models import Finding, RcaResult, ReconType, RootCauseCategory, Verdict
from rca_engine.severity import severity_badge, severity_score

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


def _analyst_summary(text: str) -> str:
    """Render an LLM-authored narrative, clearly labeled as synthesis (not evidence)
    so a reader never mistakes description for a verdict-setting fact."""

    body = "\n".join(f"> {ln}" if ln.strip() else ">" for ln in text.strip().splitlines())
    return ("## 🧠 Analyst summary\n"
            "_LLM synthesis, grounded in the evidence below — verdicts are set by the "
            "deterministic engine and confirmed by executed queries._\n\n" + body)


def build_systemic_causes(result: RcaResult) -> str:
    """Lead with the few systemic causes that each explain many findings, so the
    reader fixes one thing and clears N. Built from ``result.clusters``."""

    if not result.clusters:
        return ""
    lines = ["## 🧨 Systemic root causes _(fix one, resolve many)_", "",
             "Each row groups findings that share a single mechanism — a mistranslated "
             "expression, a transpile warning, or one category concentrated in a table. "
             "Start here: they clear the most findings per fix.", "",
             "| Fix this | Verdict | Category | Findings | Rows | Impacted locations |",
             "| :-- | :-- | :-- | --: | --: | :-- |"]
    for c in result.clusters:
        sym = _VERDICT.get(c.verdict, ("•",))[0]
        locs = ", ".join(f"`{m}`" for m in c.members[:6])
        if len(c.members) > 6:
            locs += f" _(+{len(c.members) - 6} more)_"
        lines.append(
            f"| {c.signature} | {sym} | {_cat_label(c.category)} | {c.finding_count} | "
            f"{c.rows_impacted:,} | {locs} |"
        )
    return "\n".join(lines)


def build_blast_radius(result: RcaResult) -> str:
    """Downstream consumers of the *affected* tables, so a fix can be prioritized by
    how far a defect propagates. Built from ``TableSummary.downstream_tables`` (set by
    the lineage blast-radius pass); empty when UC lineage wasn't run/available."""

    rows = []
    actionable = {f.target_table for f in result.findings
                  if f.top_hypothesis and f.top_hypothesis.verdict != Verdict.BENIGN}
    for s in sorted(result.table_summaries, key=lambda x: len(x.downstream_tables), reverse=True):
        if not s.downstream_tables or s.target_table not in actionable:
            continue
        name = s.target_table.split(".")[-1]
        preview = ", ".join(f"`{t.split('.')[-1]}`" for t in s.downstream_tables[:6])
        if len(s.downstream_tables) > 6:
            preview += f" _(+{len(s.downstream_tables) - 6} more)_"
        rows.append(f"| `{name}` | {len(s.downstream_tables)} | {preview} |")
    if not rows:
        return ""
    return "\n".join(["## 💥 Downstream blast radius", "",
                      "Affected tables (with an actionable finding) and the tables that consume them. "
                      "A defect here propagates downstream — fix and re-validate consumers first.", "",
                      "| Affected table | Downstream consumers | Tables |",
                      "| :-- | --: | :-- |", *rows])


def build_fixes(result: RcaResult) -> str:
    """A compact roll-up of the concrete suggested fixes across the run, so a reader
    can see the actionable to-do list before diving into per-finding cells."""

    rows = []
    for f in sorted(result.findings, key=severity_score, reverse=True):
        h = f.top_hypothesis
        if h and h.fix:
            check = "✅" if h.fix.validated else "·"
            rows.append(f"| `{_loc(f)}` | {h.fix.title} | {h.fix.target} | {check} | {h.fix.confidence:.0%} |")
    if not rows:
        return ""
    return "\n".join(["## 🛠️ Suggested fixes", "",
                      "Concrete, runnable remediations (review before running — each is shown as a "
                      "fix cell under its finding). **✅** in _Valid._ means a query confirmed the "
                      "fix closes the gap; blank means it's a suggestion to review.", "",
                      "| Location | Fix | Target | Valid. | Conf. |",
                      "| :-- | :-- | :-- | :--: | --: |", *rows])


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
    if result.narrative:
        lines += [_analyst_summary(result.narrative), ""]
    sc = build_systemic_causes(result)
    if sc:
        lines.append(sc)
        lines.append("")
    tp = build_top_priorities(result)
    if tp:
        lines.append(tp)
        lines.append("")
    lines.append(build_overview(result))
    lines.append("")
    mr = build_matchrates(result)
    if mr:
        lines.append(mr)
        lines.append("")
    br = build_blast_radius(result)
    if br:
        lines.append(br)
        lines.append("")
    fx = build_fixes(result)
    if fx:
        lines.append(fx)
        lines.append("")

    by_verdict: dict[Verdict, list[Finding]] = {v: [] for v in _VERDICT_ORDER}
    for f in result.findings:
        h = f.top_hypothesis
        if h:
            by_verdict.setdefault(h.verdict, []).append(f)

    lines += ["", "## 🎯 Findings by verdict _(highest impact first)_"]
    for v in _VERDICT_ORDER:
        group = sorted(by_verdict.get(v, []), key=severity_score, reverse=True)
        if not group:
            continue
        sym, label, action = _VERDICT[v]
        lines += ["", f"## {sym} {label} — _{action}_", "",
                  "| Location | Severity | Category | Conf. | ✔ | Root cause |",
                  "| :-- | :-- | :-- | :-: | :-: | :-- |"]
        for f in group:
            h = f.top_hypothesis
            check = "✓" if _confirmed(f) else "·"
            rationale = (h.rationale or "").replace("\n", " ").strip()
            if len(rationale) > 110:
                rationale = rationale[:107] + "..."
            lines.append(
                f"| `{_loc(f)}` | {severity_badge(f)} | {_cat_label(h.category)} | "
                f"{h.confidence:.0%} | {check} | {rationale} |"
            )
    return "\n".join(lines)


def build_top_priorities(result: RcaResult, n: int = 5) -> str:
    """The highest-impact findings across the whole run, so a reader sees what to
    tackle first before scrolling the per-verdict tables."""

    actionable = [f for f in result.findings
                  if f.top_hypothesis and f.top_hypothesis.verdict != Verdict.BENIGN]
    if not actionable:
        return ""
    ranked = sorted(actionable, key=severity_score, reverse=True)[:n]
    lines = ["## 🔺 Top priorities", "",
             "| Severity | Location | Verdict | Fix / next step |",
             "| :-- | :-- | :-- | :-- |"]
    for f in ranked:
        h = f.top_hypothesis
        sym = _VERDICT[h.verdict][0]
        fix = (h.remediation or h.rationale or "").replace("\n", " ").strip()
        if len(fix) > 90:
            fix = fix[:87] + "..."
        lines.append(f"| {severity_badge(f)} ({severity_score(f)}) | `{_loc(f)}` | {sym} | {fix} |")
    return "\n".join(lines)


def build_conclusion(result: RcaResult) -> str:
    """A closing, action-oriented wrap-up grouped by who owns the fix."""

    by_verdict: dict[Verdict, list[Finding]] = {}
    for f in result.findings:
        if f.top_hypothesis:
            by_verdict.setdefault(f.top_hypothesis.verdict, []).append(f)

    def _rows(v: Verdict) -> list[str]:
        out = []
        for f in sorted(by_verdict.get(v, []), key=severity_score, reverse=True):
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
    if rt == "aggregate":
        md = f.metadata or {}
        return (f"**aggregate-level** — rule `{md.get('rule', f.column)}`: "
                f"mismatch={md.get('mismatch', 0)}, missing_in_source={md.get('missing_in_source', 0)}, "
                f"missing_in_target={md.get('missing_in_target', 0)} group(s)")
    return f"recon `{rt}`, {f.mismatch_count} of {total} rows"


def _provenance(h) -> str:
    """Compact list of which independent inputs confirmed this finding."""

    used = ["📊 recon data"]  # every finding starts from the recon output
    details = [(e.label, (e.detail or "").lower()) for e in h.evidence]
    if any(lbl == "drilldown" for lbl, _ in details):
        used.append("🔎 live query")
    if any(lbl == "code" and any(w in d for w in ("derivation", "load filter", "generated", "passthrough"))
           for lbl, d in details):
        used.append("🧩 target code")
    if any(lbl == "code" and ("declared" in d or "session/zoned" in d) for lbl, d in details):
        used.append("🧬 source types")
    if any(lbl == "transpile" for lbl, _ in details):
        used.append("📄 transpile report")
    if any(lbl == "drift" for lbl, _ in details):
        used.append("📉 distribution")
    if any(lbl == "lineage" for lbl, _ in details):
        used.append("🔗 UC lineage")
    if any(lbl == "llm_drilldown" for lbl, _ in details):
        used.append("🧠 LLM synthesis")
    if any(lbl == "memory" for lbl, _ in details):
        used.append("📚 learned prior")
    return " · ".join(used)


def _transform_evidence(f: Finding) -> dict[str, Any]:
    """Pull the migrated target derivation from the code evidence for the prominent
    'Transformation logic' callout: {expr, source_file, source_line, snippet, functions}."""

    # Search ALL hypotheses (not just the top one): for an agentic column the promoted LLM
    # hypothesis is on top, but the parsed derivation lives on the deterministic hypothesis.
    for h in (f.hypotheses or []):
        for e in h.evidence:
            if e.label != "code":
                continue
            data = e.data or {}
            if data.get("expr"):
                return {"expr": data["expr"], "source_file": data.get("source_file") or "",
                        "source_line": int(data.get("source_line") or 0),
                        "snippet": data.get("source_snippet") or "",
                        "functions": list(data.get("functions") or [])}
            d = (e.detail or "").strip()
            low = d.lower()
            if low.startswith("target derivation"):
                expr = d.split(":", 1)[1].strip() if ":" in d else d
                return {"expr": expr.strip().strip("`").strip(), "source_file": "",
                        "source_line": 0, "snippet": "", "functions": []}
            if "load filter" in low or "passthrough" in low or "generated" in low:
                return {"expr": d.strip("`"), "source_file": "", "source_line": 0,
                        "snippet": "", "functions": []}
    return {}


def _culprit(category: RootCauseCategory, expr: str, functions: list[str]) -> str:
    """Pinpoint the part of the migrated derivation tied to the detected mechanism."""

    e = expr or ""
    if category == RootCauseCategory.TYPE_PRECISION:
        m = re.search(r"DECIMAL\s*\(\s*\d+\s*,\s*\d+\s*\)", e, re.I)
        if m:
            return f"the target type `{m.group(0)}` — scale reduced vs source (precision loss)"
        m = re.search(r"ROUND\s*\(.*,\s*(\d+)\s*\)", e, re.I | re.S)
        if m:
            return f"`ROUND(…, {m.group(1)})` — rounded to {m.group(1)} dp (scale loss)"
        return "the numeric scale/precision in the derivation"
    if category == RootCauseCategory.TIMEZONE:
        m = re.search(r"[+\-]\s*INTERVAL\s+'?\d+\s*HOURS?'?", e, re.I)
        return f"`{m.group(0).strip()}` — a fixed offset added on load" if m else \
            "the timezone offset in the derivation"
    if category == RootCauseCategory.STRING_FORMAT:
        for fn in ("UPPER", "LOWER", "INITCAP", "TRIM"):
            if fn in e.upper():
                return f"`{fn}(…)` — case/whitespace normalization not applied on the source side"
        return "the string transform (case/whitespace)"
    if category == RootCauseCategory.NULL_BOOLEAN:
        return "the `CASE … 'true'/'false'` boolean encoding (source keeps 'Y'/'N')"
    if category == RootCauseCategory.SEMI_STRUCTURED:
        return "the `to_json(named_struct(…))` serialization (key set/order differs)"
    if category in (RootCauseCategory.VOLUME_MISSING, RootCauseCategory.VOLUME_EXTRA):
        m = re.search(r"WHERE\s+.+", e, re.I)
        return f"`{m.group(0).strip().strip('`')}`" if m else "the load filter / fan-out in the transform"
    if category == RootCauseCategory.TRANSPILATION:
        return "the migrated expression differs from the source's intended formula (see root cause)"
    return ""


def _finding_section(f: Finding) -> list[dict[str, Any]]:
    h = f.top_hypothesis
    sym, label, action = _VERDICT.get(h.verdict, ("•", "?", "")) if h else ("•", "?", "")
    header = [f"### {sym} `{_loc(f)}` — {label}", ""]
    if h:
        header += [
            f"- **Category**: {_cat_label(h.category)}  ·  **Confidence**: {h.confidence:.0%}"
            f"  ·  **Owner**: {h.recommended_owner or '—'}",
            f"- **Signal**: {_signal(f)}",
        ]
        te = _transform_evidence(f)
        if te.get("expr"):
            col = f.column or _loc(f)
            header.append(f"- **🔧 Transformation logic** — migrated target derivation: `{col} = {te['expr']}`")
            if te.get("source_file"):
                loc = te["source_file"] + (f"  ·  line {te['source_line']}" if te.get("source_line") else "")
                header.append(f"  - **📄 Script location**: `{loc}`")
                if te.get("snippet"):
                    header.append(f"  - **In the script**: `{te['snippet'][:200]}`")
            culprit = _culprit(h.category, te["expr"], te.get("functions") or [])
            if culprit:
                header.append(f"  - **⚠️ Likely culprit**: {culprit}")
        header += [
            f"- **Root cause**: {h.rationale}",
        ]
        if h.remediation:
            header.append(f"- **Fix**: {h.remediation.strip()}")
        if h.fix:
            badge = "✅ validated" if h.fix.validated else "suggested"
            header.append(f"- **🛠️ Suggested fix ({badge})**: {h.fix.title} "
                          f"_(target: {h.fix.target} · {h.fix.confidence:.0%})_ — see the fix cell below.")
            if h.fix.validation:
                header.append(f"  - _{h.fix.validation}_")
        _ev_label = {"drilldown": "Evidence (query)", "code": "Evidence (code)",
                     "transpile": "Transpile report", "lineage": "Evidence (lineage)",
                     "drift": "Distribution drift", "llm_drilldown": "Evidence (LLM query)",
                     "memory": "Learned prior"}
        for e in h.evidence:
            if e.label in _ev_label:
                header.append(f"- **{_ev_label[e.label]}**: {e.detail}")
        prov = _provenance(h)
        if prov:
            header.append(f"- **Inputs used**: {prov}")

    samples = [
        f"  - `{ {k: v for k, v in list(s.keys.items())[:3]} }` "
        f"source={s.source_value!r} → target={s.target_value!r}"
        for s in f.samples[:4] if s.column
    ]
    if samples:
        header += ["", "Sample differences:", *samples]

    # Pre-fill the confirming query so the reader can re-run it live. Prefer the
    # deterministic drill-down; fall back to an agent-generated (llm_drilldown) query
    # when that's what confirmed the finding.
    query = ""
    for e in (h.evidence if h else []):
        if e.label in ("drilldown", "llm_drilldown") and e.query:
            query = e.query
            break
    live = _code_cell(
        f"# Re-run to confirm / drill deeper for {_loc(f)}\n"
        + (f'spark.sql("""{query}""").display()' if query
           else f'# spark.sql("SELECT * FROM {f.target_table} LIMIT 20").display()')
    )
    cells = [_md_cell("\n".join(x for x in header if x is not None)), live]

    # Suggested fix as a review-then-run cell (never auto-applied).
    if h and h.fix:
        status = "VALIDATED by query" if h.fix.validated else "SUGGESTED — not validated"
        val = f"# {h.fix.validation}\n" if h.fix.validation else ""
        cells.append(_code_cell(
            f"# 🛠️ Suggested fix for {_loc(f)} — {h.fix.title}\n"
            f"# Status: {status}. Review before running. target={h.fix.target}, kind={h.fix.kind}\n"
            f"{val}"
            f'fix_sql = """\\\n{h.fix.sql}\n"""\n'
            f"print(fix_sql)  # inspect, then run manually: spark.sql(fix_sql)"
        ))
    return cells


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
    narrative_by_table = {s.target_table: s.narrative for s in result.table_summaries if s.narrative}

    for table in sorted(by_table):
        fs = sorted(by_table[table],
                    key=lambda x: (_RECON_ORDER.get(x.recon_type, 9),
                                   -(x.top_hypothesis.confidence if x.top_hypothesis else 0)))
        cells.append(_md_cell(f"## 📦 `{table}`  \n_{_verdict_badges(fs)}  ·  {len(fs)} finding(s)_"))
        if narrative_by_table.get(table):
            cells.append(_md_cell(_analyst_summary(narrative_by_table[table])))
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


# --------------------------------------------------------------------------- #
# Per-table notebooks (one notebook per reconciled table + a master index)
# --------------------------------------------------------------------------- #
def _target_tables(result: RcaResult) -> list[str]:
    names = {s.target_table for s in result.table_summaries}
    names |= {f.target_table for f in result.findings}
    return sorted(n for n in names if n)


def _subresult(result: RcaResult, target_table: str) -> RcaResult:
    """A single-table view of the run, reusing the same report machinery. Clusters are
    recomputed from the table's own findings so the systemic-causes section stays scoped."""
    from rca_engine.cluster import build_clusters

    sub_findings = [f for f in result.findings if f.target_table == target_table]
    return RcaResult(
        recon_id=result.recon_id,
        dialect=result.dialect,
        findings=sub_findings,
        table_summaries=[s for s in result.table_summaries if s.target_table == target_table],
        clusters=build_clusters(sub_findings),
    )


def build_index_notebook(result: RcaResult, table_files: dict[str, str]) -> dict[str, Any]:
    """A master routing notebook: overall TL;DR + a per-table index linking each notebook."""
    cells = [_md_cell(build_tldr(result))]
    rows = ["| Table | Max severity | Verdicts | Findings | Notebook |",
            "|---|---|---|---|---|"]
    # Sort tables by their worst finding so the riskiest tables surface first.
    def _max_sev(tbl: str) -> int:
        fs = [f for f in result.findings if f.target_table == tbl]
        return max((severity_score(f) for f in fs), default=-1)

    for tbl in sorted(_target_tables(result), key=_max_sev, reverse=True):
        fs = [f for f in result.findings if f.target_table == tbl]
        badge = _verdict_badges(fs) if fs else "✅ clean"
        worst = max(fs, key=severity_score) if fs else None
        sev_cell = severity_badge(worst) if worst else "🟢 —"
        rows.append(f"| `{tbl}` | {sev_cell} | {badge} | {len(fs)} | `{table_files.get(tbl, '—')}` |")
    cells.append(_md_cell("---\n# 🗂️ Per-table RCA notebooks\n\nOne notebook per reconciled "
                          "table (open the file listed below). Route each to its owner.\n\n"
                          + "\n".join(rows)))
    return {
        "cells": cells,
        "metadata": {"language_info": {"name": "python"},
                     "kernelspec": {"name": "python3", "display_name": "Python 3"}},
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def build_summary_md(result: RcaResult) -> str:
    """A standalone, shareable markdown summary (TL;DR + conclusion) that can be
    pasted straight into a ticket, Slack, or email without opening a notebook."""
    return build_tldr(result) + "\n\n---\n\n" + build_conclusion(result)


def write_summary_md(result: RcaResult, path: str) -> None:
    with open(path, "w") as f:
        f.write(build_summary_md(result))


def _table_filename(target_table: str) -> str:
    """Filesystem-safe notebook name from the (short) target table name."""
    short = target_table.split(".")[-1].strip("`") or target_table
    safe = re.sub(r"[^0-9A-Za-z_.-]", "_", short)
    return f"{safe}.ipynb"


def write_rca_bundle(result: RcaResult, base_dir: str, recon_id: str,
                     combined: bool = False) -> str:
    """Write the RCA as a self-contained per-recon folder and return its path.

    Layout (recommended)::

        <base_dir>/rca_<recon_id>/
            00_index.ipynb          master overview + per-table routing (multi-table)
            SUMMARY.md              shareable plain-markdown summary (ticket/Slack/email)
            rca_<recon_id>.json     full machine-readable findings
            <table>.ipynb           one self-contained notebook per reconciled table
            rca_<recon_id>_all.ipynb  optional single-scroll combined book (combined=True)

    One folder per ``recon_id`` keeps runs isolated; per-table notebooks route to
    owners; the index is the landing page.
    """
    import os

    folder = os.path.join(base_dir, f"rca_{recon_id}")
    os.makedirs(folder, exist_ok=True)

    write_json(result, os.path.join(folder, f"rca_{recon_id}.json"))
    write_summary_md(result, os.path.join(folder, "SUMMARY.md"))

    tables = _target_tables(result)
    table_files: dict[str, str] = {}
    for tbl in tables:
        fname = _table_filename(tbl)
        # Disambiguate rare short-name collisions across schemas.
        if fname in table_files.values():
            fname = _table_filename(tbl.replace(".", "_"))
        write_notebook(_subresult(result, tbl), os.path.join(folder, fname))
        table_files[tbl] = fname

    # Index is the landing page; only meaningful once there is more than one table.
    if len(tables) > 1:
        with open(os.path.join(folder, "00_index.ipynb"), "w") as f:
            json.dump(build_index_notebook(result, table_files), f, indent=1)

    if combined:
        write_notebook(result, os.path.join(folder, f"rca_{recon_id}_all.ipynb"))

    return folder
