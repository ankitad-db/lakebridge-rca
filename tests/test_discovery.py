"""Tests for recon-run discovery (list_recon_runs / format_recon_runs)."""

from __future__ import annotations

from rca_engine.discovery import format_recon_runs, list_recon_runs


class FakeRunner:
    """A QueryRunner that returns canned rows keyed by a substring of the SQL."""

    def __init__(self, responses: list[tuple[str, list[dict]]]):
        self._responses = responses

    def query(self, sql: str):
        for needle, rows in self._responses:
            if needle in sql:
                return rows
        return []


def test_list_recon_runs_rolls_up_diffs():
    runner = FakeRunner([
        ("GROUP BY recon_id", [
            {"recon_id": "run_b", "started": "2026-07-20", "ended": "2026-07-20", "table_pairs": 3},
            {"recon_id": "run_a", "started": "2026-07-19", "ended": "2026-07-19", "table_pairs": 2},
        ]),
        ("recon_id = 'run_b'", [{"n": 2}]),
        ("recon_id = 'run_a'", [{"n": 0}]),
    ])
    runs = list_recon_runs(runner, "cat", "reconcile")
    assert [r["recon_id"] for r in runs] == ["run_b", "run_a"]
    assert runs[0]["tables_with_diffs"] == 2 and runs[0]["clean"] is False
    assert runs[1]["tables_with_diffs"] == 0 and runs[1]["clean"] is True


def test_list_recon_runs_falls_back_without_start_ts():
    calls = {"n": 0}

    class Flaky:
        def query(self, sql: str):
            if "ORDER BY started" in sql:
                calls["n"] += 1
                raise RuntimeError("no such column start_ts")
            if "ORDER BY recon_id" in sql:
                return [{"recon_id": "r1", "table_pairs": 1}]
            return [{"n": -0}]

    runs = list_recon_runs(Flaky(), "cat", "reconcile")
    assert calls["n"] == 1  # tried the timestamp-ordered query first
    assert runs and runs[0]["recon_id"] == "r1"


def test_format_recon_runs_empty_and_table():
    assert "No reconcile runs" in format_recon_runs([])
    md = format_recon_runs([
        {"recon_id": "r1", "started": "2026-07-20", "ended": "x",
         "table_pairs": 3, "tables_with_diffs": 1, "clean": False},
    ])
    assert "`r1`" in md and "has diffs" in md
