"""Emit structured findings and an RCA notebook scaffold.

The engine produces the deterministic first pass (findings + candidate
hypotheses + TL;DR). The Genie Code skill runs the notebook live, adds evidence
from real queries, and finalizes the narrative.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any

from rca_engine.models import Finding, RcaResult, Verdict

_VERDICT_LABEL = {
    Verdict.MIGRATION_INDUCED: "Migration-induced",
    Verdict.GENUINE_DATA: "Genuine data difference",
    Verdict.BENIGN: "Benign / expected",
    Verdict.NEEDS_REVIEW: "Needs review",
}


def to_dict(result: RcaResult) -> dict[str, Any]:
    return dataclasses.asdict(result)


def write_json(result: RcaResult, path: str) -> None:
    with open(path, "w") as f:
        json.dump(to_dict(result), f, indent=2, default=str)


def build_tldr(result: RcaResult) -> str:
    counts = result.verdict_counts()
    lines = [
        f"# RCA TL;DR - recon `{result.recon_id}` ({result.dialect})",
        "",
        f"- Findings analyzed: **{len(result.findings)}**",
    ]
    for verdict, label in _VERDICT_LABEL.items():
        n = counts.get(verdict.value, 0)
        if n:
            lines.append(f"- {label}: **{n}**")
    lines.append("")
    lines.append("## Headline root causes")
    for f in sorted(result.findings, key=lambda x: (x.top_hypothesis.confidence if x.top_hypothesis else 0), reverse=True)[:10]:
        h = f.top_hypothesis
        if not h:
            continue
        loc = f"{f.target_table}" + (f".{f.column}" if f.column else "")
        lines.append(
            f"- `{loc}` -> **{_VERDICT_LABEL[h.verdict]}** / {h.category.value} "
            f"(confidence {h.confidence:.0%}): {h.rationale}"
        )
    return "\n".join(lines)


def _md_cell(text: str) -> dict[str, Any]:
    return {"cell_type": "markdown", "metadata": {}, "source": text.splitlines(keepends=True)}


def _code_cell(code: str) -> dict[str, Any]:
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": code.splitlines(keepends=True),
    }


def _finding_section(f: Finding) -> list[dict[str, Any]]:
    h = f.top_hypothesis
    loc = f"{f.target_table}" + (f".{f.column}" if f.column else "")
    header = [f"## {loc}", "", f"- Recon type: `{f.recon_type.value}`", f"- Mismatches: {f.mismatch_count}"]
    if h:
        header += [
            f"- **Verdict**: {_VERDICT_LABEL[h.verdict]}",
            f"- Category: `{h.category.value}` (confidence {h.confidence:.0%})",
            f"- Rationale: {h.rationale}",
            f"- Recommended owner: {h.recommended_owner}",
            f"- Remediation: {h.remediation}" if h.remediation else "",
        ]
    samples = [
        f"  - keys={s.keys} source={s.source_value!r} target={s.target_value!r}"
        for s in f.samples[:5]
    ]
    if samples:
        header += ["", "Sample differences:", *samples]
    live = _code_cell(
        f"# Live drill-down for {loc}: run to confirm the hypothesis, then\n"
        f"# refine and re-run until the verdict is confident.\n"
        f"# spark.sql(\"SELECT ... FROM {f.source_table} ... \").display()"
    )
    return [_md_cell("\n".join(x for x in header if x is not None)), live]


def build_notebook(result: RcaResult) -> dict[str, Any]:
    cells = [_md_cell(build_tldr(result)), _md_cell("---\n# Findings")]
    for f in result.findings:
        cells.extend(_finding_section(f))
    return {
        "cells": cells,
        "metadata": {"language_info": {"name": "python"}, "kernelspec": {"name": "python3", "display_name": "Python 3"}},
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def write_notebook(result: RcaResult, path: str) -> None:
    with open(path, "w") as f:
        json.dump(build_notebook(result), f, indent=1)
