"""Populate the pipeline audit trail with a rich, realistic history grounded in the REAL
recon bundles (real recon_ids + real finding counts). Each recon gets a reconcile step and
an RCA step, with Source→Target schemas filled, a mix of identities (you + the app service
principal) and tools (app / skill / cli), spread over the bundles' real dates and realistic
durations. Clears the demo audit log first so the trail reads cleanly for the demo.

  python3 migration/seed_audit_demo.py
"""
import glob
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rca_engine.audit import ensure_audit_table  # noqa: E402
from rca_engine.runners import StatementRunner  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLES = os.path.join(ROOT, "app", "bundles")
CATALOG = "fevm_ps_dr_us_east_2_catalog"
SCHEMA = "reconcile"
AUDIT = f"{CATALOG}.{SCHEMA}.rca_genie_audit"
WAREHOUSE = "4c79c6902dd2bbc2"
PROFILE = "ps-dr-east"

USER = "ankita.darekar@databricks.com"
SPN = "9730e27f-223f-4f51-8f3d-18302364faf5"  # the rca-genie app service principal
# (tool, run_by) rotation → a realistic mix of your identity and the app SPN across surfaces.
ACTORS = [("skill", USER), ("app", USER), ("cli", USER), ("app", SPN), ("skill", SPN), ("app", USER)]
# Source→Target schema pairs (the retail Sales & Revenue mart migration beds).
PAIRS = [("mig_hyb_src", "mig_hyb_tgt"), ("mig_det_src", "mig_det_tgt"),
         ("mig_source_sim", "mig_target"), ("mig_xl_src", "mig_xl_tgt")]


def _q(v):  # SQL string literal
    return "NULL" if v is None else "'" + str(v).replace("'", "''") + "'"


def _ts(dt: datetime) -> str:
    return f"TIMESTAMP '{dt.strftime('%Y-%m-%d %H:%M:%S')}'"


def _parse(iso):
    if not iso:
        return None
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _insert(runner, *, run_id, op, tool, by, src, tgt, rid, pairs, with_diffs,
            findings, started: datetime, dur_s: int, msg):
    ended = started + timedelta(seconds=dur_s)
    cols = ("audit_id, run_id, operation, status, tool, run_by, catalog, source_schema, "
            "target_schema, recon_id, tables, table_pairs, pairs_ok, pairs_error, "
            "tables_with_diffs, findings_total, notebook_path, message, duration_ms, "
            "started_ts, ended_ts, inserted_ts")
    vals = (
        f"{_q(uuid.uuid4().hex)}, {_q(run_id)}, {_q(op)}, 'ok', {_q(tool)}, {_q(by)}, "
        f"{_q(CATALOG)}, {_q(src)}, {_q(tgt)}, {_q(rid)}, '[]', {pairs}, {pairs}, 0, "
        f"{with_diffs}, {findings}, NULL, {_q(msg)}, {dur_s * 1000}, "
        f"{_ts(started)}, {_ts(ended)}, {_ts(ended)}"
    )
    runner.query(f"INSERT INTO {AUDIT} ({cols}) VALUES ({vals})")


def main():
    runner = StatementRunner(warehouse_id=WAREHOUSE, profile=PROFILE)
    ensure_audit_table(runner, AUDIT)
    runner.query(f"DELETE FROM {AUDIT} WHERE true")
    print(f"Cleared {AUDIT}; seeding from real bundles…\n")

    bundles = sorted(glob.glob(os.path.join(BUNDLES, "rca_*", "rca_*.json")))
    n_rows = 0
    for i, path in enumerate(bundles):
        rid = os.path.basename(os.path.dirname(path))[len("rca_"):]
        doc = json.load(open(path))
        fs = doc.get("findings", [])
        findings = len(fs)
        with_diffs = len({f.get("target_table") for f in fs if f.get("target_table")})
        meta_p = os.path.join(os.path.dirname(path), "meta.json")
        started = _parse(json.load(open(meta_p)).get("started")) if os.path.exists(meta_p) else None
        started = started or (datetime.utcnow() - timedelta(days=i))
        pairs = max(with_diffs, 3 if "hyb" in PAIRS[i % len(PAIRS)][0] or i % 3 == 0 else 1)
        tool, by = ACTORS[i % len(ACTORS)]
        src, tgt = PAIRS[i % len(PAIRS)]
        run_id = uuid.uuid4().hex

        # reconcile step (before RCA), realistic job-cluster duration
        _insert(runner, run_id=run_id, op="reconcile", tool=tool, by=by, src=src, tgt=tgt,
                rid=rid, pairs=pairs, with_diffs=with_diffs, findings=0,
                started=started - timedelta(minutes=14), dur_s=300 + (i % 5) * 90,
                msg=f"Reconciled {pairs} pair(s) — {with_diffs} with differences.")
        # RCA step
        _insert(runner, run_id=run_id, op="rca", tool=tool, by=by, src=src, tgt=tgt,
                rid=rid, pairs=pairs, with_diffs=with_diffs, findings=findings,
                started=started, dur_s=(18 if findings == 0 else 60 + findings * 6),
                msg=(f"RCA complete — {findings} finding(s)." if findings
                     else "RCA complete — no differences (clean)."))
        n_rows += 2
        print(f"  {rid[:12]}…  reconcile+rca  {tool}/{by.split('@')[0][:12]}  {src}→{tgt}  {findings} findings")

    print(f"\nSeeded {n_rows} audit rows across {len(bundles)} recons.")


if __name__ == "__main__":
    main()
