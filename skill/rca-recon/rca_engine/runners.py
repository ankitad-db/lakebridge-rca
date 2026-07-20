"""Query runners that satisfy the ``QueryRunner`` protocol.

Two backends:

- ``SparkQueryRunner``  - for use inside a Databricks notebook / Genie Code
  (``spark`` is in scope). Returns fully-nested Python objects.
- ``StatementRunner``   - for local runs via the Databricks SQL Statement
  Execution API, shelling out to the ``databricks`` CLI (so it inherits the
  CLI's auth, proxy, and cert handling). Nested types come back as JSON strings,
  which the ingester parses defensively.
"""

from __future__ import annotations

import json
import subprocess
import time
from typing import Any


class SparkQueryRunner:
    """QueryRunner backed by an active SparkSession (Databricks notebook)."""

    def __init__(self, spark: Any):
        self._spark = spark

    def query(self, sql: str) -> list[dict[str, Any]]:
        rows = self._spark.sql(sql).collect()
        return [r.asDict(recursive=True) for r in rows]


class StatementRunner:
    """QueryRunner backed by the SQL Statement Execution API via the CLI."""

    def __init__(self, warehouse_id: str, profile: str = "ps-dr-east"):
        self._warehouse_id = warehouse_id
        self._profile = profile

    def _api(self, method: str, path: str, body: dict | None = None) -> dict:
        cmd = ["databricks", "api", method, path, "--profile", self._profile]
        if body is not None:
            cmd += ["--json", json.dumps(body)]
        out = subprocess.run(cmd, capture_output=True, text=True)
        if out.returncode != 0:
            raise RuntimeError(out.stderr.strip() or out.stdout.strip())
        return json.loads(out.stdout) if out.stdout.strip() else {}

    def query(self, sql: str) -> list[dict[str, Any]]:
        result = self._api(
            "post",
            "/api/2.0/sql/statements/",
            {"warehouse_id": self._warehouse_id, "statement": sql, "wait_timeout": "50s"},
        )
        statement_id = result.get("statement_id")
        state = result.get("status", {}).get("state")
        while state in ("PENDING", "RUNNING"):
            time.sleep(2)
            result = self._api("get", f"/api/2.0/sql/statements/{statement_id}")
            state = result.get("status", {}).get("state")
        if state != "SUCCEEDED":
            err = result.get("status", {}).get("error", {})
            raise RuntimeError(f"Statement failed ({state}): {err.get('message', result)}")

        manifest = result.get("manifest", {})
        columns = [c["name"] for c in manifest.get("schema", {}).get("columns", [])]

        rows: list[list[Any]] = []
        res = result.get("result", {})
        rows.extend(res.get("data_array", []) or [])
        # Follow chunk links if the result is paginated.
        next_link = res.get("next_chunk_internal_link")
        while next_link:
            chunk = self._api("get", next_link)
            rows.extend(chunk.get("data_array", []) or [])
            next_link = chunk.get("next_chunk_internal_link")

        return [dict(zip(columns, r)) for r in rows]
