"""Stress test for the real scenario (AVF · Teradata · ADLS extracts): seed a LARGE AVF run
— many tables, many mismatched columns, many sampled rows — then run our validation-tool-
agnostic RCA over it and report ingest + classify throughput.

Rows are generated SERVER-SIDE (INSERT ... SELECT FROM range(...)) so large volumes don't
travel through the client. Measures the deterministic path (ingest + classify, no live
drill-down) — the part whose cost scales with finding count — which is what a real
hundreds-of-columns migration run stresses.

  python migration/avf_demo/stress_avf.py                 # default: 25 tables x 20 cols x 50 rows
  python migration/avf_demo/stress_avf.py 50 30 100        # tables cols rows_per_col

Produces, for N tables x C columns x R rows:
  N*C column-mismatch findings + N schema + N volume findings  (+ reads N*C*R detail rows).
"""
import json
import os
import subprocess
import sys
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from rca_engine.analyze import analyze  # noqa: E402
from rca_engine.runners import StatementRunner  # noqa: E402
from rca_engine.sources import AVFSource  # noqa: E402

CAT = "fevm_ps_dr_us_east_2_catalog"
RS = f"{CAT}.avf_reports_stress"
WAREHOUSE = "4c79c6902dd2bbc2"
PROFILE = "ps-dr-east"
RUN_ID = str(uuid.uuid4())
VER = "20260205130000000"


def sql(stmt: str, label: str = "") -> bool:
    r = subprocess.run(
        ["databricks", "api", "post", "/api/2.0/sql/statements/", "-p", PROFILE, "--json",
         json.dumps({"warehouse_id": WAREHOUSE, "statement": stmt, "wait_timeout": "50s"})],
        capture_output=True, text=True)
    try:
        d = json.loads(r.stdout)
    except json.JSONDecodeError:
        print(f"  ! {label}: {(r.stdout or r.stderr)[:200]}")
        return False
    # Long-running generators may return PENDING; poll to completion.
    sid = d.get("statement_id")
    st = (d.get("status") or {}).get("state")
    while st in ("PENDING", "RUNNING") and sid:
        time.sleep(3)
        p = subprocess.run(["databricks", "api", "get",
                            f"/api/2.0/sql/statements/{sid}", "-p", PROFILE],
                           capture_output=True, text=True)
        d = json.loads(p.stdout)
        st = (d.get("status") or {}).get("state")
    if st != "SUCCEEDED":
        print(f"  ! {label}: {json.dumps(d.get('status', {}))[:300]}")
        return False
    return True


def seed(n_tables: int, n_cols: int, n_rows: int) -> None:
    sql(f"CREATE SCHEMA IF NOT EXISTS {RS}", "schema")
    # summary: one row per table (entity_i), Teradata dialect, FAIL.
    sql(f"DROP TABLE IF EXISTS {RS}.avf_validation_summary", "drop summary")
    sql(f"""CREATE TABLE {RS}.avf_validation_summary AS
        SELECT '{RUN_ID}' AS run_id, 'edw' AS source_catalog, 'sales' AS source_schema,
               concat('fact_', t.id) AS source_entity, '{CAT}' AS target_catalog,
               'mig_td_stress' AS target_schema, concat('fact_', t.id) AS target_entity,
               'teradata' AS source_dialect,
               TIMESTAMP'2026-02-05 13:00:00' AS validation_start_time,
               TIMESTAMP'2026-02-05 13:05:00' AS validation_end_time,
               1000000 AS source_total_rows, 999990 AS target_total_rows,
               10 AS source_only_rows, 0 AS target_only_rows, {n_rows} AS mismatched_rows,
               'id' AS primary_keys_used, 'FAIL' AS schema_validation_status,
               'FAIL' AS overall_status, '{VER}' AS version
        FROM range({n_tables}) AS t""", "summary")

    # columns_mismatch: N_TABLES x N_COLS x N_ROWS rows, generated server-side.
    sql(f"DROP TABLE IF EXISTS {RS}.avf_validation_columns_mismatch", "drop cols")
    sql(f"""CREATE TABLE {RS}.avf_validation_columns_mismatch AS
        SELECT '{RUN_ID}' AS run_id, 'edw' AS source_catalog, 'sales' AS source_schema,
               concat('fact_', t.id) AS source_entity,
               '{CAT}' AS target_catalog, 'mig_td_stress' AS target_schema,
               concat('fact_', t.id) AS target_entity,
               concat('col_', c.cid) AS source_column_name, concat('col_', c.cid) AS target_column_name,
               cast(r.rid AS string) AS source_column_value,
               cast(r.rid + 1 AS string) AS target_column_value,
               to_json(named_struct('id', r.rid)) AS row_identifier,
               'VALUE' AS mismatch_type, 'decimal' AS column_datatype,
               {n_rows} AS total_rows_with_column_mismatches, '{VER}' AS version
        FROM range({n_tables}) AS t
        CROSS JOIN (SELECT id AS cid FROM range({n_cols})) c
        CROSS JOIN (SELECT id AS rid FROM range({n_rows})) r""", "columns_mismatch")

    # rows_mismatch: 10 missing-in-target per table.
    sql(f"DROP TABLE IF EXISTS {RS}.avf_validation_rows_mismatch", "drop rows")
    sql(f"""CREATE TABLE {RS}.avf_validation_rows_mismatch AS
        SELECT '{RUN_ID}' AS run_id, '{CAT}' AS target_catalog, 'mig_td_stress' AS target_schema,
               concat('fact_', t.id) AS target_entity,
               to_json(named_struct('id', 900 + r.rid)) AS row_identifier,
               true AS missing_in_target, false AS missing_in_source, '' AS mismatched_columns,
               '{VER}' AS version
        FROM range({n_tables}) AS t CROSS JOIN (SELECT id AS rid FROM range(10)) r""", "rows_mismatch")

    # schema_mismatch: one scale-loss per table.
    sql(f"DROP TABLE IF EXISTS {RS}.avf_validation_schema_mismatch", "drop schema")
    sql(f"""CREATE TABLE {RS}.avf_validation_schema_mismatch AS
        SELECT '{RUN_ID}' AS run_id, '{CAT}' AS target_catalog, 'mig_td_stress' AS target_schema,
               concat('fact_', t.id) AS target_entity, 'amount' AS source_column_name,
               'amount' AS target_column_name, 'NUMBER' AS source_data_type, 'DECIMAL' AS target_data_type,
               18 AS source_length, 18 AS target_length, 4 AS source_scale, 2 AS target_scale,
               true AS source_nullable, true AS target_nullable, 'TYPE_DIFF' AS mismatch_type,
               'WARNING' AS severity, '{VER}' AS version
        FROM range({n_tables}) AS t""", "schema_mismatch")


def main():
    args = sys.argv[1:]
    n_tables = int(args[0]) if len(args) > 0 else 25
    n_cols = int(args[1]) if len(args) > 1 else 20
    n_rows = int(args[2]) if len(args) > 2 else 50
    detail_rows = n_tables * n_cols * n_rows
    print(f"[stress] seeding {n_tables} tables x {n_cols} cols x {n_rows} rows "
          f"= {detail_rows:,} column-mismatch rows; run_id={RUN_ID}", flush=True)
    t0 = time.time()
    seed(n_tables, n_cols, n_rows)
    print(f"[stress] seeded in {time.time()-t0:.0f}s", flush=True)

    runner = StatementRunner(warehouse_id=WAREHOUSE, profile=PROFILE)
    source = AVFSource(run_id=RUN_ID, reports_schema=RS)
    t1 = time.time()
    # Deterministic path only (the part that scales with finding count): no live drill-down/
    # drift/lineage/fixes — those issue per-finding live queries and aren't what we stress here.
    result = analyze(runner, "", "", "", source=source,
                     drilldown=False, drift=False, use_lineage=False,
                     trace_job=False, fixes=False, validate_fixes=False)
    elapsed = time.time() - t1

    by_type: dict[str, int] = {}
    for f in result.findings:
        by_type[f.recon_type.value] = by_type.get(f.recon_type.value, 0) + 1
    classified = sum(1 for f in result.findings if f.top_hypothesis is not None)
    print("\n=== STRESS RESULT ===")
    print(f"dialect auto-detected : {result.dialect}")
    print(f"detail rows ingested  : ~{detail_rows:,}")
    print(f"findings              : {len(result.findings)}  by_type={by_type}")
    print(f"classified (hypothesis): {classified}/{len(result.findings)}")
    print(f"ingest+classify time  : {elapsed:.1f}s  "
          f"({len(result.findings)/elapsed:.0f} findings/s)")
    expected_cols = n_tables * n_cols
    ok = by_type.get("column_mismatch", 0) == expected_cols and classified == len(result.findings)
    print(f"integrity             : {'PASS' if ok else 'CHECK'} "
          f"(expected {expected_cols} column findings)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
