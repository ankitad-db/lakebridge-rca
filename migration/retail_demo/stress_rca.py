"""Stress test: fire many RCA skill runs concurrently over a fleet of recon_ids and
report per-run status + the RCA compute latency (from the rca_genie_audit table).

Demonstrates the RCA pipeline handling a fleet of reconcile jobs at once. Run after the
retail beds are reconciled + the skill is synced.
"""
import json
import subprocess
import time

PROFILE = "ps-dr-east"
CAT = "fevm_ps_dr_us_east_2_catalog"
WH = "3220376d4497e2d7"
NB = "/Users/ankita.darekar@databricks.com/rca_skill_driver"
DET_ART = f"/Workspace/Users/ankita.darekar@databricks.com/.assistant/skills/rca-recon/demo_artifacts/det"
HYB_ART = f"/Workspace/Users/ankita.darekar@databricks.com/.assistant/skills/rca-recon/demo_artifacts/hybrid"

# Fleet: the retail beds (live tables, full RCA) run twice each + a few historical recons.
FLEET = [
    ("hybrid-a", "218dab3c4c51443783dbf14a16c324fc", HYB_ART),
    ("hybrid-b", "218dab3c4c51443783dbf14a16c324fc", HYB_ART),
    ("det-a", "eca72dd859f246088271a0ac0e43ddae", DET_ART),
    ("det-b", "eca72dd859f246088271a0ac0e43ddae", DET_ART),
    ("agg-a", "d90e15507e02494190c6d87cd59123bf", DET_ART),
    ("agg-b", "d90e15507e02494190c6d87cd59123bf", DET_ART),
    ("hist-1", "c07f5b5f6b604c7ab8d60fadcdc56d09", ""),
    ("hist-2", "38336e24d49e481e9716405b2940a7de", ""),
    ("hist-3", "f727523ea65c4a3ca09ecea1cf0652ca", ""),
]


def submit(name, rid, art):
    sub = {"run_name": f"stress_{name}", "tasks": [{"task_key": "rca", "notebook_task": {
        "notebook_path": NB, "base_parameters": {"recon_id": rid, "endpoint": "", "transpiled_dir": art}}}]}
    r = subprocess.run(["databricks", "api", "post", "/api/2.1/jobs/runs/submit", "-p", PROFILE,
                        "--json", json.dumps(sub)], capture_output=True, text=True)
    try:
        return json.loads(r.stdout)["run_id"]
    except Exception:
        return None


def state(run_id):
    r = subprocess.run(["databricks", "api", "get", f"/api/2.1/jobs/runs/get?run_id={run_id}", "-p", PROFILE],
                       capture_output=True, text=True)
    try:
        s = json.loads(r.stdout).get("status") or {}
        return s.get("state", ""), (s.get("termination_details") or {}).get("code", "")
    except Exception:
        return "", ""


def audit_durations():
    q = (f"SELECT recon_id, round(avg(duration_ms)/1000,1) AS avg_s, count(*) AS runs "
         f"FROM {CAT}.reconcile.rca_genie_audit WHERE operation='rca' AND status='ok' "
         f"AND started_ts > current_timestamp() - INTERVAL 3 HOURS GROUP BY recon_id ORDER BY avg_s DESC")
    r = subprocess.run(["databricks", "api", "post", "/api/2.0/sql/statements/", "-p", PROFILE, "--json",
                        json.dumps({"warehouse_id": WH, "statement": q, "wait_timeout": "40s"})],
                       capture_output=True, text=True)
    try:
        return json.loads(r.stdout).get("result", {}).get("data_array") or []
    except Exception:
        return []


def main():
    t0 = time.time()
    runs = [(n, rid, submit(n, rid, a)) for n, rid, a in FLEET]
    print(f"submitted {sum(1 for _,_,r in runs if r)}/{len(runs)} concurrent RCA runs", flush=True)
    pending = {r for _, _, r in runs if r}
    results = {}
    while pending:
        for rid in list(pending):
            st, code = state(rid)
            if st in ("TERMINATED", "INTERNAL_ERROR"):
                results[rid] = (st, code)
                pending.discard(rid)
        if pending:
            time.sleep(12)
    ok = sum(1 for st, code in results.values() if code == "SUCCESS")
    print(f"\nFLEET COMPLETE: {ok}/{len(results)} SUCCESS in {round(time.time()-t0)}s wall (concurrent)")
    for name, rid, run_id in runs:
        st, code = results.get(run_id, ("?", "?"))
        print(f"  {name:9} run={run_id} -> {code}")
    print("\nRCA compute latency (from rca_genie_audit, avg seconds per recon_id):")
    for rid, avg_s, n in audit_durations():
        print(f"  {rid}: {avg_s}s avg over {n} run(s)")


if __name__ == "__main__":
    main()
