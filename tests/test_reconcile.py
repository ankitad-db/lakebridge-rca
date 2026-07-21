"""Tests for the app-native reconcile engine (rca_engine.reconcile).

Uses a scripted fake QueryRunner that answers by SQL shape, so the tests exercise
key detection, the comparison flow, and the Lakebridge-compatible writes without a
warehouse.
"""

from __future__ import annotations

import re

from rca_engine.reconcile import (
    TablePairSpec,
    _array_of_maps,
    _key_candidates,
    _map_literal,
    _sql_str,
    detect_join_keys,
    run_reconcile,
)


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #
def test_sql_str_escapes_and_null():
    assert _sql_str(None) == "NULL"
    assert _sql_str("a'b") == "'a''b'"
    assert _sql_str(5) == "'5'"


def test_map_and_array_literals():
    assert _map_literal([("k", "v"), ("n", None)]) == "map('k', 'v', 'n', NULL)"
    assert _array_of_maps([]) == "array()"
    assert _array_of_maps([[("a", "1")]]) == "array(map('a', '1'))"


def test_key_candidates_prefers_pk_then_composites():
    cands = _key_candidates("agg_daily_sales", ["store_id", "sales_date", "revenue"])
    assert ["store_id"] in cands
    assert ["store_id", "sales_date"] in cands            # id-like + date grain key
    assert cands.index(["store_id"]) < cands.index(["store_id", "sales_date"])


def test_key_candidates_all_id_like_composite():
    cands = _key_candidates("bridge", ["a_id", "b_id", "val"])
    assert ["a_id", "b_id"] in cands


# --------------------------------------------------------------------------- #
# Scripted fake runner
# --------------------------------------------------------------------------- #
class FakeRunner:
    """Answers queries by SQL shape and records INSERTs."""

    def __init__(self, columns, counts, missing, agg=None, samples=None, unique_keys=None):
        self.columns = columns          # (schema, table) -> {col: type}
        self.counts = counts            # table -> count
        self.missing = missing          # ("target"/"source") -> n
        self.agg = agg or {}            # {"common":, "anym":, "c0":, ...}
        self.samples = samples or []    # list of dict rows for mismatch sample
        self.unique_keys = unique_keys or set()  # tuple(keys) considered unique
        self.inserts: list[str] = []

    def query(self, sql: str):
        s = " ".join(sql.split())
        if s.startswith("INSERT INTO"):
            self.inserts.append(s)
            return []
        if "information_schema.columns" in s:
            schema = re.search(r"table_schema = '([^']+)'", s).group(1)
            table = re.search(r"table_name = '([^']+)'", s).group(1)
            cols = self.columns.get((schema, table), {})
            return [{"column_name": c, "data_type": t, "ordinal_position": i}
                    for i, (c, t) in enumerate(cols.items())]
        if "max(recon_table_id)" in s:
            return [{"m": 100}]
        if "count(DISTINCT" in s:
            # uniqueness probe: n, d, nulls
            keys = tuple(re.findall(r"`([a-z_]+)` IS NOT NULL", s))
            n = 50
            d = n if keys in self.unique_keys else 3
            return [{"n": n, "d": d, "nulls": 0}]
        if "LEFT ANTI JOIN" in s and "count(*)" in s:
            key = "target" if " s LEFT ANTI JOIN " in s else "source"
            return [{"n": self.missing.get(key, 0)}]
        if "count_if(" in s and "AS common" in s:
            return [self.agg]
        if s.startswith("SELECT count(*) AS n FROM"):
            table = re.search(r"FROM `[^`]+`\.`[^`]+`\.`([^`]+)`", s).group(1)
            return [{"n": self.counts.get(table, 0)}]
        if "WHERE" in s and "LIMIT" in s:          # mismatch sample
            return self.samples
        if "LEFT ANTI JOIN" in s and "LIMIT" in s:  # missing samples
            return []
        return []


def _cols(*pairs):
    return {c: t for c, t in pairs}


def test_run_reconcile_happy_path_writes_and_summarizes():
    cols = _cols(("id", "LONG"), ("amount", "DECIMAL"))
    runner = FakeRunner(
        columns={("src", "t"): cols, ("tgt", "t"): cols},
        counts={"t": 50},
        missing={"target": 0, "source": 0},
        agg={"common": 50, "anym": 5, "c0": 5},   # amount mismatches on 5 rows
        samples=[{"id": "1", "amount__b": "10.00", "amount__c": "10"}],
        unique_keys={("id",)},
    )
    res = run_reconcile(runner, "cat", "src", "tgt", [TablePairSpec(source_table="t")])
    assert len(res.recon_id) == 32
    pair = res.pairs[0]
    assert pair.status == "ok"
    assert pair.join_keys == ["id"]
    assert pair.mismatch_columns == ["amount"]
    assert pair.absolute_mismatch == 5
    # main + metrics + details(mismatch) inserted, all carrying the recon_id / values.
    assert any(".main (" in i for i in runner.inserts)
    assert any(".metrics (" in i for i in runner.inserts)
    assert any(".details (" in i and "'mismatch'" in i for i in runner.inserts)
    assert all(res.recon_id in i for i in runner.inserts if ".main (" in i)


def test_run_reconcile_missing_table_is_isolated_error():
    runner = FakeRunner(columns={}, counts={}, missing={})
    res = run_reconcile(runner, "cat", "src", "tgt", [TablePairSpec(source_table="ghost")])
    assert res.pairs[0].status == "error"
    assert "not found" in res.pairs[0].message
    assert res.pairs[0].to_dict()["status"] == "error"
    assert runner.inserts == []            # nothing written for a failed pair


def test_detect_join_keys_gives_up_within_limit():
    runner = FakeRunner(columns={}, counts={}, missing={}, unique_keys=set())  # nothing unique
    keys, note = detect_join_keys(runner, "cat", "src", "t", ["a_id", "b_id"], max_key_tries=2)
    assert keys == []
    assert "attempt" in note
