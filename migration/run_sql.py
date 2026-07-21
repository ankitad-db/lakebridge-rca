"""Execute a .sql file against a Databricks SQL warehouse.

Runs each ``;``-separated statement via the SQL Statement Execution API, using an
OAuth token from the Databricks CLI (``databricks auth token --profile ...``).
Uses only the standard library so it runs anywhere.

Usage:
    python migration/run_sql.py --file migration/source_sim/02_create_source_sim.sql \
        --warehouse-id 4c79c6902dd2bbc2 --profile ps-dr-east
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time


def split_statements(sql: str) -> list[str]:
    """Split SQL into statements on ``;``, ignoring line/block comments and strings."""

    stmts: list[str] = []
    buf: list[str] = []
    i, n = 0, len(sql)
    in_str = False
    quote = ""
    in_line_comment = False
    in_block_comment = False

    while i < n:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ""

        if in_line_comment:
            buf.append(ch)
            if ch == "\n":
                in_line_comment = False
        elif in_block_comment:
            buf.append(ch)
            if ch == "*" and nxt == "/":
                buf.append(nxt)
                i += 1
                in_block_comment = False
        elif in_str:
            buf.append(ch)
            if ch == quote:
                in_str = False
        elif ch == "-" and nxt == "-":
            in_line_comment = True
            buf.append(ch)
        elif ch == "/" and nxt == "*":
            in_block_comment = True
            buf.append(ch)
        elif ch in ("'", '"'):
            in_str, quote = True, ch
            buf.append(ch)
        elif ch == ";":
            stmt = "".join(buf).strip()
            if stmt:
                stmts.append(stmt)
            buf = []
        else:
            buf.append(ch)
        i += 1

    tail = "".join(buf).strip()
    if tail:
        stmts.append(tail)

    # Drop statements that are entirely comments/blank.
    cleaned = []
    for s in stmts:
        lines = [ln for ln in s.splitlines() if ln.strip()]
        if lines and not all(ln.strip().startswith("--") for ln in lines):
            cleaned.append(s)
    return cleaned


def _api(profile: str, method: str, path: str, body: dict | None = None) -> dict:
    """Call the Databricks REST API through the CLI (handles auth + proxy/cert)."""

    cmd = ["databricks", "api", method, path, "--profile", profile]
    if body is not None:
        cmd += ["--json", json.dumps(body)]
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or out.stdout.strip())
    return json.loads(out.stdout) if out.stdout.strip() else {}


def run_statement(profile: str, warehouse_id: str, statement: str,
                  catalog: str | None, schema: str | None) -> None:
    body: dict = {"warehouse_id": warehouse_id, "statement": statement, "wait_timeout": "50s"}
    if catalog:
        body["catalog"] = catalog
    if schema:
        body["schema"] = schema
    result = _api(profile, "post", "/api/2.0/sql/statements/", body)

    statement_id = result.get("statement_id")
    state = result.get("status", {}).get("state")
    while state in ("PENDING", "RUNNING"):
        time.sleep(2)
        result = _api(profile, "get", f"/api/2.0/sql/statements/{statement_id}")
        state = result.get("status", {}).get("state")

    if state != "SUCCEEDED":
        err = result.get("status", {}).get("error", {})
        raise RuntimeError(f"Statement failed ({state}): {err.get('message', result)}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--file", required=True)
    p.add_argument("--warehouse-id", required=True)
    p.add_argument("--profile", default="ps-dr-east")
    p.add_argument("--catalog", default=None)
    p.add_argument("--schema", default=None)
    args = p.parse_args(argv)

    with open(args.file) as f:
        statements = split_statements(f.read())

    print(f"Running {len(statements)} statement(s) from {args.file}")
    for i, stmt in enumerate(statements, 1):
        preview = " ".join(stmt.split())[:80]
        try:
            run_statement(args.profile, args.warehouse_id, stmt, args.catalog, args.schema)
            print(f"  [{i}/{len(statements)}] OK: {preview}")
        except Exception as e:
            print(f"  [{i}/{len(statements)}] FAILED: {preview}\n      {e}")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
