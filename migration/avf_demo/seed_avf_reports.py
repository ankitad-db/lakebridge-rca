"""Seed a COMPLETED AVF run's report tables so our validation-tool-agnostic RCA can be
tested end-to-end against real Delta tables — WITHOUT needing the AVF wheel deployed.

Scenario (matches the real project): source = Teradata, surfaced in Databricks as ADLS
extracts (pre- and post-load); AVF validated the post-load target against the source
extract and wrote its avf_* report tables; our RCA reads those tables by run_id.

This writes a Teradata-dialect `fact_sales` validation that exercises EVERY AVF feature our
ingest consumes, so run_rca_avf.py produces a full RCA bundle:

  PK_BASED column mismatches  amount (DECIMAL precision), order_ts_utc (timezone),
                              customer_name (string case/trim)   -> columns_mismatch
  row presence                5 rows missing in target, 2 extra  -> rows_mismatch
  schema                      NUMBER(18,4) -> DECIMAL(18,2)       -> schema_mismatch
  AVF row-count RCA           FILTER_LOSS on an upstream stage    -> avf_validation_rca (evidence)
  METRICS / BI mode           revenue aggregate variance          -> avf_validation_bi_results

Run (CLI):
  python migration/avf_demo/seed_avf_reports.py            # prints RUN_ID=<uuid>
  python migration/avf_demo/run_rca_avf.py <RUN_ID>

For a REAL AVF run instead of this seed, see README.md (Track 1).
"""
import json
import subprocess
import sys
import uuid

CAT = "fevm_ps_dr_us_east_2_catalog"
REPORTS_SCHEMA = "avf_reports"           # catalog.schema holding the avf_* tables
WAREHOUSE = "4c79c6902dd2bbc2"
PROFILE = "ps-dr-east"
RS = f"{CAT}.{REPORTS_SCHEMA}"
RUN_ID = str(uuid.uuid4())
VERSION = "20260205120000000"
DIALECT = "teradata"
SRC = ("edw", "sales", "fact_sales")      # (catalog, schema, entity) — the Teradata source extract
TGT = (CAT, "mig_td_tgt", "fact_sales")   # the migrated Databricks target


_FAILED: list[str] = []


def sql(statement: str, label: str = "") -> list | None:
    """Run a statement. Returns the data rows on success, or None on failure (and records
    the failure so main() can report honestly instead of claiming a false success)."""
    r = subprocess.run(
        ["databricks", "api", "post", "/api/2.0/sql/statements/", "-p", PROFILE, "--json",
         json.dumps({"warehouse_id": WAREHOUSE, "statement": statement, "wait_timeout": "50s"})],
        capture_output=True, text=True)
    try:
        d = json.loads(r.stdout)
    except json.JSONDecodeError:
        print(f"  ! {label}: {(r.stdout or r.stderr)[:200]}")
        _FAILED.append(label)
        return None
    st = (d.get("status") or {}).get("state")
    if st != "SUCCEEDED":
        print(f"  ! {label}: {json.dumps(d.get('status', {}))[:300]}")
        _FAILED.append(label)
        return None
    return (d.get("result", {}).get("data_array") or [])


def _vals(rows: list[dict], cols: list[str]) -> str:
    def lit(v):
        if v is None:
            return "NULL"
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, (int, float)):
            return str(v)
        return "'" + str(v).replace("'", "''") + "'"
    return ",\n".join("(" + ",".join(lit(r.get(c)) for c in cols) + ")" for r in rows)


def seed_table(name: str, cols_ddl: list[tuple[str, str]], rows: list[dict]) -> None:
    cols = [c for c, _ in cols_ddl]
    sql(f"DROP TABLE IF EXISTS {RS}.{name}", f"drop {name}")
    created = sql(f"CREATE TABLE {RS}.{name} (" + ", ".join(f"{c} {t}" for c, t in cols_ddl)
                  + ") USING DELTA", f"create {name}")
    inserted = sql(f"INSERT INTO {RS}.{name} ({', '.join(cols)}) VALUES\n{_vals(rows, cols)}",
                   f"insert {name}") if (rows and created is not None) else []
    ok = created is not None and inserted is not None
    print(f"  {'seeded' if ok else 'FAILED'} {name} ({len(rows)} rows)")


def main():
    print(f"[AVF seed] reports schema {RS}  run_id={RUN_ID}", flush=True)
    sql(f"CREATE SCHEMA IF NOT EXISTS {RS}", "schema")
    src_fqn, tgt_fqn = ".".join(SRC), ".".join(TGT)
    common = dict(run_id=RUN_ID, version=VERSION, source_dialect=DIALECT,
                  source_catalog=SRC[0], source_schema=SRC[1], source_entity=SRC[2],
                  target_catalog=TGT[0], target_schema=TGT[1], target_entity=TGT[2])

    # 1) summary — one validated entity (counts, status, dialect, PKs AVF already detected).
    seed_table("avf_validation_summary", [
        ("run_id", "STRING"), ("source_catalog", "STRING"), ("source_schema", "STRING"),
        ("source_entity", "STRING"), ("target_catalog", "STRING"), ("target_schema", "STRING"),
        ("target_entity", "STRING"), ("source_dialect", "STRING"),
        ("validation_start_time", "TIMESTAMP"), ("validation_end_time", "TIMESTAMP"),
        ("source_total_rows", "BIGINT"), ("target_total_rows", "BIGINT"),
        ("source_only_rows", "BIGINT"), ("target_only_rows", "BIGINT"), ("mismatched_rows", "BIGINT"),
        ("primary_keys_used", "STRING"), ("schema_validation_status", "STRING"),
        ("overall_status", "STRING"), ("version", "STRING"),
    ], [{**common,
         "validation_start_time": "2026-02-05 12:00:00", "validation_end_time": "2026-02-05 12:02:30",
         "source_total_rows": 500000, "target_total_rows": 499995,
         "source_only_rows": 5, "target_only_rows": 2, "mismatched_rows": 1200,
         "primary_keys_used": "order_id", "schema_validation_status": "FAIL",
         "overall_status": "FAIL"}])

    # 2) columns_mismatch — three value-level causes (precision, timezone, string).
    col = dict(**{k: common[k] for k in
                  ("run_id", "source_catalog", "source_schema", "source_entity",
                   "target_catalog", "target_schema", "target_entity")}, version=VERSION)
    cells = []
    for i in range(1, 6):
        cells += [
            {**col, "source_column_name": "amount", "target_column_name": "amount",
             "source_column_value": f"{i}0.0000", "target_column_value": f"{i}0.00",
             "row_identifier": json.dumps({"order_id": i}), "mismatch_type": "VALUE",
             "column_datatype": "decimal", "total_rows_with_column_mismatches": 1200},
            {**col, "source_column_name": "order_ts_utc", "target_column_name": "order_ts_utc",
             "source_column_value": "2026-01-01T00:00:00Z", "target_column_value": "2026-01-01T05:00:00Z",
             "row_identifier": json.dumps({"order_id": i}), "mismatch_type": "VALUE",
             "column_datatype": "timestamp", "total_rows_with_column_mismatches": 1200},
            {**col, "source_column_name": "customer_name", "target_column_name": "customer_name",
             "source_column_value": "Jane Doe", "target_column_value": "JANE DOE",
             "row_identifier": json.dumps({"order_id": i}), "mismatch_type": "VALUE",
             "column_datatype": "string", "total_rows_with_column_mismatches": 400},
        ]
    seed_table("avf_validation_columns_mismatch", [
        ("run_id", "STRING"), ("source_catalog", "STRING"), ("source_schema", "STRING"),
        ("source_entity", "STRING"), ("target_catalog", "STRING"), ("target_schema", "STRING"),
        ("target_entity", "STRING"), ("source_column_name", "STRING"), ("target_column_name", "STRING"),
        ("source_column_value", "STRING"), ("target_column_value", "STRING"), ("row_identifier", "STRING"),
        ("mismatch_type", "STRING"), ("column_datatype", "STRING"),
        ("total_rows_with_column_mismatches", "INT"), ("version", "STRING"),
    ], cells)

    # 3) rows_mismatch — 5 missing in target, 2 extra in target.
    rid = dict(run_id=RUN_ID, version=VERSION, target_catalog=TGT[0],
               target_schema=TGT[1], target_entity=TGT[2])
    rrows = [{**rid, "row_identifier": json.dumps({"order_id": 900 + i}),
              "missing_in_target": True, "missing_in_source": False, "mismatched_columns": ""}
             for i in range(5)]
    rrows += [{**rid, "row_identifier": json.dumps({"order_id": 950 + i}),
               "missing_in_target": False, "missing_in_source": True, "mismatched_columns": ""}
              for i in range(2)]
    seed_table("avf_validation_rows_mismatch", [
        ("run_id", "STRING"), ("target_catalog", "STRING"), ("target_schema", "STRING"),
        ("target_entity", "STRING"), ("row_identifier", "STRING"), ("missing_in_target", "BOOLEAN"),
        ("missing_in_source", "BOOLEAN"), ("mismatched_columns", "STRING"), ("version", "STRING"),
    ], rrows)

    # 4) schema_mismatch — NUMBER(18,4) -> DECIMAL(18,2) scale loss.
    seed_table("avf_validation_schema_mismatch", [
        ("run_id", "STRING"), ("target_catalog", "STRING"), ("target_schema", "STRING"),
        ("target_entity", "STRING"), ("source_column_name", "STRING"), ("target_column_name", "STRING"),
        ("source_data_type", "STRING"), ("target_data_type", "STRING"), ("source_length", "INT"),
        ("target_length", "INT"), ("source_scale", "INT"), ("target_scale", "INT"),
        ("source_nullable", "BOOLEAN"), ("target_nullable", "BOOLEAN"), ("mismatch_type", "STRING"),
        ("severity", "STRING"), ("version", "STRING"),
    ], [{**rid, "source_column_name": "amount", "target_column_name": "amount",
         "source_data_type": "NUMBER", "target_data_type": "DECIMAL", "source_length": 18,
         "target_length": 18, "source_scale": 4, "target_scale": 2, "source_nullable": True,
         "target_nullable": True, "mismatch_type": "TYPE_DIFF", "severity": "WARNING"}])

    # 5) AVF's own row-count RCA (consumed as EVIDENCE on our volume finding).
    seed_table("avf_validation_rca", [
        ("run_id", "STRING"), ("failed_table", "STRING"), ("cause_classification", "STRING"),
        ("confidence", "DOUBLE"), ("primary_suspect", "STRING"), ("primary_suspect_edge", "STRING"),
        ("row_deficit", "BIGINT"), ("recommendations", "ARRAY<STRING>"),
        ("upstream_notebooks", "ARRAY<STRING>"), ("problematic_notebooks", "ARRAY<STRING>"),
        ("problematic_jobs", "ARRAY<STRING>"), ("version", "STRING"),
    ], [])
    rca_ins = sql(f"""INSERT INTO {RS}.avf_validation_rca
            (run_id, failed_table, cause_classification, confidence, primary_suspect,
             primary_suspect_edge, row_deficit, recommendations, upstream_notebooks,
             problematic_notebooks, problematic_jobs, version)
            VALUES ('{RUN_ID}', '{tgt_fqn}', 'FILTER_LOSS', 0.88, '{SRC[0]}.{SRC[1]}.stg_sales',
             'stg_sales -> fact_sales', 5, array('Review the WHERE clause added on stg_sales'),
             array('/Workspace/etl/build_fact_sales'), array('/Workspace/etl/build_fact_sales'),
             array('job_1047'), '{VERSION}')""", "insert rca")
    print(f"  {'seeded' if rca_ins is not None else 'FAILED'} avf_validation_rca (1 row)")

    # 6) METRICS / BI mode — a revenue aggregate variance outside tolerance.
    seed_table("avf_validation_bi_results", [
        ("run_id", "STRING"), ("query_name", "STRING"), ("status", "STRING"),
        ("source_total", "DOUBLE"), ("target_total", "DOUBLE"), ("variance_pct", "DOUBLE"),
        ("variance_absolute", "DOUBLE"), ("tolerance_threshold", "DOUBLE"),
        ("comparison_type", "STRING"), ("grain_columns", "STRING"), ("metric_columns", "STRING"),
        ("source_system", "STRING"), ("report_name", "STRING"), ("version", "STRING"),
    ], [{"run_id": RUN_ID, "query_name": "daily_revenue", "status": "FAIL",
         "source_total": 12850000.0, "target_total": 12848750.0, "variance_pct": 0.0097,
         "variance_absolute": 1250.0, "tolerance_threshold": 0.0, "comparison_type": "AGGREGATE",
         "grain_columns": "store_id", "metric_columns": "revenue", "source_system": "TERADATA",
         "report_name": "revenue_by_store", "version": VERSION}])

    if _FAILED:
        print(f"\n✗ seeding FAILED ({len(_FAILED)} statement(s)) — e.g. {_FAILED[0]}.")
        print("  If this is an auth error, re-login:  databricks auth login -p ps-dr-east")
        return 1
    print(f"\n✓ seeded AVF run  src={src_fqn}  tgt={tgt_fqn}")
    print(f"RUN_ID={RUN_ID}")
    print(f"REPORTS_SCHEMA={RS}")
    print(f"next: python migration/avf_demo/run_rca_avf.py {RUN_ID}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
