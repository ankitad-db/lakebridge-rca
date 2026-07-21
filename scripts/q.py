"""Tiny ad-hoc query helper: run a SQL statement on the warehouse via the CLI API.

Usage: python scripts/q.py "SELECT 1" [--warehouse-id ...] [--profile ...]
Prints the result rows as JSON (list of dicts).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time


def _api(profile: str, method: str, path: str, body: dict | None = None) -> dict:
    cmd = ["databricks", "api", method, path, "--profile", profile]
    if body is not None:
        cmd += ["--json", json.dumps(body)]
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or out.stdout.strip())
    return json.loads(out.stdout) if out.stdout.strip() else {}


def query(profile: str, warehouse_id: str, statement: str, catalog: str | None = None) -> list[dict]:
    body: dict = {"warehouse_id": warehouse_id, "statement": statement, "wait_timeout": "50s"}
    if catalog:
        body["catalog"] = catalog
    res = _api(profile, "post", "/api/2.0/sql/statements/", body)
    sid = res.get("statement_id")
    state = res.get("status", {}).get("state")
    while state in ("PENDING", "RUNNING"):
        time.sleep(1.5)
        res = _api(profile, "get", f"/api/2.0/sql/statements/{sid}")
        state = res.get("status", {}).get("state")
    if state != "SUCCEEDED":
        raise RuntimeError(f"{state}: {res.get('status', {}).get('error', {})}")
    cols = [c["name"] for c in res.get("manifest", {}).get("schema", {}).get("columns", [])]
    data = (res.get("result", {}) or {}).get("data_array") or []
    return [dict(zip(cols, row)) for row in data]


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("statement")
    p.add_argument("--warehouse-id", default="4c79c6902dd2bbc2")
    p.add_argument("--profile", default="ps-dr-east")
    p.add_argument("--catalog", default=None)
    args = p.parse_args()
    rows = query(args.profile, args.warehouse_id, args.statement, args.catalog)
    print(json.dumps(rows, indent=2, default=str))
    sys.exit(0)
