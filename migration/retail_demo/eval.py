"""Offline eval / LLM-as-judge over the retail demo beds.

Grades the generated RCA (deterministic + hybrid) against a ground-truth oracle of the KNOWN
seeded defects — verdict precision/recall + category accuracy + detection recall + a
false-positive check (the within-tolerance column must NOT be raised) — plus the LLM-as-judge
quality scores (evidence sufficiency, fix validity, narrative faithfulness) via
rca_engine.judge. Reads the generated bundle JSONs; pass --endpoint to use the LLM grader.

  python3 migration/retail_demo/eval.py [--endpoint databricks-claude-opus-5]
"""
import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from rca_engine.judge import grade_result  # noqa: E402
from rca_engine.models import (  # noqa: E402
    Evidence, Finding, Fix, Hypothesis, RcaResult, ReconType, RootCauseCategory, Verdict,
)


def _ev(d):
    return Evidence(label=d.get("label", ""), detail=d.get("detail", ""),
                    query=d.get("query", ""), data=d.get("data") or {})


def _fix(d):
    if not d:
        return None
    return Fix(title=d.get("title", ""), kind=d.get("kind", ""), sql=d.get("sql", ""),
               target=d.get("target", "transform"), confidence=d.get("confidence", 0.0),
               validated=bool(d.get("validated")), validation=d.get("validation", ""))


def _hyp(d):
    return Hypothesis(category=RootCauseCategory(d["category"]), verdict=Verdict(d["verdict"]),
                      confidence=d.get("confidence", 0.0), rationale=d.get("rationale", ""),
                      remediation=d.get("remediation", ""), recommended_owner=d.get("recommended_owner", ""),
                      evidence=[_ev(e) for e in (d.get("evidence") or [])], fix=_fix(d.get("fix")))


def result_from_json(path):
    d = json.load(open(path))
    fs = [Finding(recon_id=f["recon_id"], source_table=f["source_table"], target_table=f["target_table"],
                  recon_type=ReconType(f["recon_type"]), column=f.get("column"),
                  mismatch_count=f.get("mismatch_count", 0), total_count=f.get("total_count", 0),
                  metadata=f.get("metadata") or {}, hypotheses=[_hyp(h) for h in (f.get("hypotheses") or [])])
          for f in d.get("findings", [])]
    return RcaResult(recon_id=d.get("recon_id", ""), dialect=d.get("dialect", "snowflake"), findings=fs)


def _loc(f):
    tbl = (f.target_table or "").split(".")[-1]
    return f"{tbl}.{f.column}" if f.column else tbl


# ground-truth category oracle for the column findings (verdict is migration_induced for all)
DET_CAT = {
    "fact_sales.unit_price": "type_precision", "fact_sales.net_revenue": "type_precision",
    "fact_sales.customer_name": "string_format", "fact_sales.is_active": "null_boolean",
    "fact_sales.order_ts_utc": "timezone", "dim_customer.customer_name": "string_format",
    "dim_customer.email": "string_format", "dim_customer.is_active": "null_boolean",
    "dim_product.product_name": "string_format", "dim_product.list_price": "type_precision",
}
HYB_CAT = {
    "fact_sales.unit_price": "type_precision", "fact_sales.customer_name": "string_format",
    "fact_sales.order_ts_utc": "timezone", "fact_sales.net_revenue": "transpilation",
    "fact_sales.amount_usd": "transpilation", "fact_sales.status_bucket": "transpilation",
}
BENIGN = {"fact_sales.tax_rate"}  # within declared tolerance — must NOT be raised migration-induced


def grade_bed(name, path, cat_oracle, endpoint):
    res = result_from_json(path)
    verdict_oracle = {loc: "migration_induced" for loc in cat_oracle}
    top = {_loc(f): f.top_hypothesis for f in res.findings if f.top_hypothesis}
    detected = [c for c in cat_oracle if c in top]
    cat_ok = [c for c in detected if top[c].category.value == cat_oracle[c]]
    fp = [c for c in BENIGN if c in top and top[c].verdict == Verdict.MIGRATION_INDUCED]
    g = grade_result(res, oracle=verdict_oracle, endpoint=endpoint)
    print(f"\n===== {name} =====")
    print(f"  detection recall     : {len(detected)}/{len(cat_oracle)}  ({round(100*len(detected)/len(cat_oracle))}%)")
    print(f"  category accuracy    : {len(cat_ok)}/{len(detected)}  ({round(100*len(cat_ok)/max(1,len(detected)))}%)")
    print(f"  verdict accuracy     : {g['summary'].get('verdict_accuracy')}")
    print(f"  migration precision  : {g['summary'].get('migration_induced_precision')}")
    print(f"  migration recall     : {g['summary'].get('migration_induced_recall')}")
    print(f"  false positives (benign flagged): {len(fp)}  {fp}")
    print(f"  LLM-judge backend    : {g['summary']['backend']}")
    print(f"  evidence sufficiency : {g['summary']['mean_evidence_sufficiency']}")
    print(f"  fix validity         : {g['summary']['mean_fix_validity']}")
    print(f"  narrative faithfulness: {g['summary']['mean_narrative_faithfulness']}")
    return {"bed": name, "detection": f"{len(detected)}/{len(cat_oracle)}",
            "category": f"{len(cat_ok)}/{len(detected)}", "false_positives": len(fp), **g["summary"]}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", default=None)
    ap.add_argument("--det", default=glob.glob("/tmp/dg_eca72*/rca_*/*.json") and glob.glob("/tmp/dg_eca72*/rca_*/*.json")[0])
    ap.add_argument("--hyb", default=glob.glob("/tmp/dg_218dab*/rca_*/*.json") and glob.glob("/tmp/dg_218dab*/rca_*/*.json")[0])
    a = ap.parse_args()
    out = []
    if a.det:
        out.append(grade_bed("Deterministic bed", a.det, DET_CAT, a.endpoint))
    if a.hyb:
        out.append(grade_bed("Hybrid bed", a.hyb, HYB_CAT, a.endpoint))
    print("\nJSON:", json.dumps(out))
