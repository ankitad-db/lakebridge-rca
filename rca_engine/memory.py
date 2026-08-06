"""Learning loop — remember confirmed root causes so recurring ones auto-classify.

Migrations repeat their mistakes: the same mistranslated function, the same scale loss,
the same session-timezone assumption recur across tables and across runs. This module
lets the RCA *learn* from what it has already confirmed:

- ``record_confirmations`` writes a compact **signature → cause** row for every finding a
  run concluded *and confirmed with a query* (append-only Delta table, like the audit log).
- ``load_memory`` reads those rows back (aggregated by signature) at the start of a run.
- ``apply_memory`` uses the memory as a **prior**: for a matching residual/unknown finding
  it proposes the remembered category (so the deterministic drill-down can confirm it), and
  for a matching known finding it nudges confidence and cites the prior sightings.

The signature is *mechanism-based*, not column-specific (dialect + category + the translated
function set / scale delta), so a cause learned on one column generalizes to others.

Guardrail: memory never finalizes a verdict on its own — it only proposes/nudges. The
drill-down (or the Tier-2 query gate) still confirms, so the "every verdict cites an
executed query" guarantee holds. Everything is best-effort: a missing/again unwritable
table degrades to no memory and the RCA proceeds unaffected.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from rca_engine.fixgen import _declared_source_type, _derivation, _scale
from rca_engine.ingest import QueryRunner
from rca_engine.models import Evidence, Finding, Hypothesis, RootCauseCategory, Verdict

_COLUMNS: list[tuple[str, str]] = [
    ("memory_id", "STRING"),
    ("signature", "STRING"),
    ("dialect", "STRING"),
    ("category", "STRING"),
    ("verdict", "STRING"),
    ("remediation", "STRING"),
    ("recommended_owner", "STRING"),
    ("confidence", "DOUBLE"),
    ("example_location", "STRING"),
    ("recon_id", "STRING"),
    ("run_by", "STRING"),
    ("inserted_ts", "TIMESTAMP"),
]


def _lit(v: Any) -> str:
    if v is None:
        return "NULL"
    return "'" + str(v).replace("\\", "\\\\").replace("'", "''") + "'"


def _short(name: str) -> str:
    return name.split(".")[-1].strip("`") if name else name


def signature_for(finding: Finding, dialect: str) -> str:
    """Stable, mechanism-based key for a finding's cause.

    Prefers the translated function set (a shared translation defect), then a numeric
    scale delta (precision loss), then falls back to ``dialect|category|recon_type`` so
    every finding still has a signature. Column/table names are deliberately excluded so
    a learned cause generalizes."""

    top = finding.top_hypothesis
    cat = top.category.value if top else RootCauseCategory.UNKNOWN.value
    expr, funcs = _derivation(finding)
    if funcs:
        mech = "fn:" + ",".join(sorted({f.lower() for f in funcs}))
    else:
        src_scale = _scale(_declared_source_type(finding))
        tgt_scale = _scale(expr)
        if src_scale is not None and tgt_scale is not None:
            mech = f"scale:{src_scale}->{tgt_scale}"
        else:
            mech = f"rt:{finding.recon_type.value}"
    return f"{dialect}|{cat}|{mech}"


@dataclass
class MemoryHit:
    signature: str
    category: str
    verdict: str
    remediation: str = ""
    recommended_owner: str = ""
    confidence: float = 0.0
    hits: int = 0
    examples: list[str] = field(default_factory=list)


def ensure_memory_table(runner: QueryRunner, memory_table: str) -> bool:
    if not memory_table:
        return False
    cols = ", ".join(f"{c} {t}" for c, t in _COLUMNS)
    try:
        runner.query(f"CREATE TABLE IF NOT EXISTS {memory_table} ({cols}) USING DELTA")
        return True
    except Exception as exc:  # pragma: no cover - perms/env dependent
        print(f"[memory] could not ensure {memory_table}: {exc}")
        return False


def _confirmed(finding: Finding) -> bool:
    top = finding.top_hypothesis
    return bool(top and any(e.data and e.data.get("confirmed") for e in top.evidence))


def record_confirmations(
    runner: QueryRunner,
    memory_table: str,
    result: Any,
    dialect: str,
    run_by: str | None = None,
) -> int:
    """Append a memory row for each *query-confirmed*, concluded finding. Returns the
    number of rows written. Best-effort; returns 0 on any failure."""

    if not memory_table:
        return 0
    findings = getattr(result, "findings", result) or []
    rows: list[str] = []
    for f in findings:
        top = f.top_hypothesis
        if top is None or not _confirmed(f):
            continue
        if top.verdict in (Verdict.NEEDS_REVIEW,) or top.category == RootCauseCategory.UNKNOWN:
            continue
        loc = f"{_short(f.target_table)}.{f.column}" if f.column else _short(f.target_table)
        vals = [
            _lit(uuid.uuid4().hex), _lit(signature_for(f, dialect)), _lit(dialect),
            _lit(top.category.value), _lit(top.verdict.value),
            _lit((top.remediation or "")[:2000]), _lit(top.recommended_owner or ""),
            str(round(float(top.confidence), 4)), _lit(loc),
            _lit(getattr(result, "recon_id", "")), _lit(run_by), "current_timestamp()",
        ]
        rows.append(f"({', '.join(vals)})")
    if not rows:
        return 0
    try:
        ensure_memory_table(runner, memory_table)
        cols = ", ".join(c for c, _ in _COLUMNS)
        runner.query(f"INSERT INTO {memory_table} ({cols}) VALUES {', '.join(rows)}")
        return len(rows)
    except Exception as exc:  # pragma: no cover - perms/env dependent
        print(f"[memory] write failed for {memory_table}: {exc}")
        return 0


def load_memory(
    runner: QueryRunner,
    memory_table: str,
    dialect: str | None = None,
    limit: int = 5000,
) -> dict[str, MemoryHit]:
    """Read memory rows and aggregate by signature into the dominant confirmed cause.

    Returns ``{signature: MemoryHit}``. The dominant (category, verdict) per signature is
    the most frequently recorded; ``confidence`` is the max seen and ``hits`` the total.
    Empty dict when the table is missing/unreadable."""

    if not memory_table:
        return {}
    where = f"WHERE dialect = {_lit(dialect)} " if dialect else ""
    try:
        rows = runner.query(
            "SELECT signature, category, verdict, remediation, recommended_owner, "
            f"confidence, example_location FROM {memory_table} {where}"
            f"ORDER BY inserted_ts DESC LIMIT {int(limit)}"
        )
    except Exception:
        return {}

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        sig = r.get("signature")
        if sig:
            grouped[str(sig)].append(r)

    out: dict[str, MemoryHit] = {}
    for sig, recs in grouped.items():
        combo_counts: dict[tuple[str, str], int] = defaultdict(int)
        for r in recs:
            combo_counts[(str(r.get("category")), str(r.get("verdict")))] += 1
        (cat, verdict), _ = max(combo_counts.items(), key=lambda kv: kv[1])
        dom = [r for r in recs if str(r.get("category")) == cat and str(r.get("verdict")) == verdict]
        conf = max((float(r.get("confidence") or 0) for r in dom), default=0.0)
        rem = next((str(r.get("remediation")) for r in dom if r.get("remediation")), "")
        owner = next((str(r.get("recommended_owner")) for r in dom if r.get("recommended_owner")), "")
        examples = [str(r.get("example_location")) for r in dom if r.get("example_location")][:5]
        out[sig] = MemoryHit(signature=sig, category=cat, verdict=verdict, remediation=rem,
                             recommended_owner=owner, confidence=conf, hits=len(recs),
                             examples=examples)
    return out


def _as_category(value: str) -> RootCauseCategory:
    try:
        return RootCauseCategory(value)
    except ValueError:
        return RootCauseCategory.UNKNOWN


def _as_verdict(value: str) -> Verdict:
    try:
        return Verdict(value)
    except ValueError:
        return Verdict.NEEDS_REVIEW


def apply_memory(findings: list[Finding], memory: dict[str, MemoryHit], dialect: str) -> list[Finding]:
    """Use memory as a prior (never a verdict). For a residual/unknown finding whose
    signature was confirmed before, propose the remembered category so the drill-down can
    confirm it; for a matching known finding, cite the prior sightings and nudge confidence.
    Every touched finding gets a ``memory`` evidence line; the drill-down still confirms."""

    if not memory:
        return findings
    for f in findings:
        sig = signature_for(f, dialect)
        hit = memory.get(sig)
        if hit is None or hit.hits <= 0:
            continue
        top = f.top_hypothesis
        note = Evidence(
            label="memory",
            detail=f"Learned prior: this signature was confirmed as "
            f"`{hit.category}`/`{hit.verdict}` in {hit.hits} previous finding(s)"
            + (f" (e.g. {', '.join(hit.examples[:3])})" if hit.examples else "") + ".",
            data={"signature": sig, "hits": hit.hits, "category": hit.category,
                  "verdict": hit.verdict},
        )
        remembered_cat = _as_category(hit.category)
        if top is None or top.category == RootCauseCategory.UNKNOWN:
            # Drop the inconclusive UNKNOWN hypothesis so the remembered proposal ranks
            # top, then let the drill-down confirm it.
            f.hypotheses = [h for h in f.hypotheses if h.category != RootCauseCategory.UNKNOWN]
            # Propose the remembered cause as a hypothesis for the drill-down to confirm.
            f.hypotheses.append(Hypothesis(
                category=remembered_cat,
                verdict=Verdict.NEEDS_REVIEW,   # stays gated until a query confirms
                confidence=min(0.5, 0.2 + 0.05 * hit.hits),
                rationale=f"Proposed from learned memory ({hit.hits} prior confirmations of "
                f"`{hit.category}`); confirm with the drill-down before actioning.",
                remediation=hit.remediation,
                recommended_owner=hit.recommended_owner,
                evidence=[note],
            ))
        else:
            top.evidence.append(note)
            if top.category == remembered_cat:
                top.confidence = round(min(0.97, top.confidence + 0.05), 2)
    return findings
