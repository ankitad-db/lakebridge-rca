"""Tests for the append-only audit trail (rca_engine.audit)."""

from __future__ import annotations

from rca_engine.audit import ensure_audit_table, log_audit, read_audit


class RecordingRunner:
    def __init__(self, fail_on: str | None = None):
        self.sql: list[str] = []
        self.fail_on = fail_on

    def query(self, sql: str):
        self.sql.append(sql)
        if self.fail_on and self.fail_on in sql:
            raise RuntimeError("boom")
        return []


def test_ensure_audit_table_emits_create_if_not_exists():
    r = RecordingRunner()
    assert ensure_audit_table(r, "c.s.rca_audit") is True
    assert r.sql and r.sql[0].startswith("CREATE TABLE IF NOT EXISTS c.s.rca_audit (")
    assert "audit_id STRING" in r.sql[0] and "USING DELTA" in r.sql[0]


def test_log_audit_inserts_row_with_values():
    r = RecordingRunner()
    run_id = log_audit(
        r, "c.s.rca_audit", operation="reconcile", status="ok", tool="app",
        recon_id="abc", catalog="c", source_schema="src", target_schema="tgt",
        tables=[{"source": "t"}], table_pairs=2, pairs_ok=2, message="done",
    )
    assert len(run_id) == 32
    inserts = [s for s in r.sql if s.startswith("INSERT INTO c.s.rca_audit")]
    assert len(inserts) == 1
    ins = inserts[0]
    assert "'reconcile'" in ins and "'ok'" in ins and "'abc'" in ins
    assert run_id in ins                      # run_id embedded
    assert '\\"source\\": \\"t\\"' in ins or '"source": "t"' in ins  # tables JSON present


def test_log_audit_escapes_quotes():
    r = RecordingRunner()
    log_audit(r, "c.s.a", operation="rca", status="error", message="it's broken")
    assert any("it''s broken" in s for s in r.sql)


def test_log_audit_never_raises_and_returns_run_id():
    r = RecordingRunner(fail_on="INSERT INTO")
    run_id = log_audit(r, "c.s.a", operation="rca", status="ok", run_id="fixed123")
    assert run_id == "fixed123"               # returned even though the insert failed


def test_disabled_when_no_table():
    r = RecordingRunner()
    rid = log_audit(r, "", operation="rca", status="ok")
    assert len(rid) == 32
    assert r.sql == []                        # nothing attempted


def test_read_audit_returns_empty_on_error():
    r = RecordingRunner(fail_on="SELECT")
    assert read_audit(r, "c.s.a") == []
