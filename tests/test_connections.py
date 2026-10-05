"""External-source connection config: resolver logic (offline; federation is untested live)."""
from rca_engine.connections import (
    SourceConnection,
    ensure_foreign_catalog,
    resolve_source_catalog,
)


class RecordingRunner:
    """Captures the SQL it is asked to run; returns nothing."""

    def __init__(self):
        self.queries: list[str] = []

    def query(self, sql):
        self.queries.append(sql)
        return []


def test_disabled_by_default_uses_local_catalog():
    conn = SourceConnection()
    assert conn.enabled is False
    runner = RecordingRunner()
    assert resolve_source_catalog(conn, "main_cat", runner=runner) == "main_cat"
    assert resolve_source_catalog(None, "main_cat", runner=runner) == "main_cat"
    assert runner.queries == []  # nothing federation-related runs when unconfigured


def test_from_config_reads_keys():
    conn = SourceConnection.from_config(
        {"source_catalog": "sf_fed", "source_connection": "sf_conn"}
    )
    assert conn.enabled and conn.catalog == "sf_fed" and conn.connection == "sf_conn"


def test_federated_catalog_resolves_and_is_ensured_from_connection():
    conn = SourceConnection(catalog="sf_fed", connection="sf_conn")
    runner = RecordingRunner()
    assert resolve_source_catalog(conn, "main_cat", runner=runner) == "sf_fed"
    # a foreign catalog is created on demand from the UC connection
    assert any("CREATE FOREIGN CATALOG IF NOT EXISTS" in q and "sf_conn" in q
               for q in runner.queries)


def test_catalog_without_connection_is_used_as_is():
    conn = SourceConnection(catalog="sf_fed")  # already-federated catalog, no connection
    runner = RecordingRunner()
    assert resolve_source_catalog(conn, "main_cat", runner=runner) == "sf_fed"
    assert runner.queries == []  # nothing to create


def test_jdbc_only_connection_falls_back_to_local_for_sql_path():
    # A JDBC-only config (Lakebridge path) has no federated catalog for the SQL path.
    conn = SourceConnection(jdbc_options={"host": "x"})
    assert conn.enabled is True
    assert resolve_source_catalog(conn, "main_cat", runner=RecordingRunner()) == "main_cat"


def test_ensure_never_raises_on_federation_error():
    class Boom:
        def query(self, sql):
            raise RuntimeError("federation not enabled")

    conn = SourceConnection(catalog="sf_fed", connection="sf_conn")
    # degrades: returns the catalog name, swallows the error
    assert ensure_foreign_catalog(Boom(), conn) == "sf_fed"
