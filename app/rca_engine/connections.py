"""External source connectivity via Unity Catalog connection configs.

ReconResolve reads all of its inputs as **Unity Catalog tables**. To reconcile against a
NON-Databricks source (Snowflake, Oracle, Teradata, SQL Server, Synapse, Redshift), the
source is reached through **Unity Catalog Lakehouse Federation**:

    UC CONNECTION  (created once, holds the credentials / connection config)
        └── FOREIGN CATALOG  (CREATE FOREIGN CATALOG ... USING CONNECTION <name>)
                └── <foreign_catalog>.<schema>.<table>   ← queryable like any UC table

Once federated, the external tables are addressable with ordinary three-part names, so the
existing SQL runner, the reconcile joins, and the RCA confirming/drill-down queries all work
**unchanged** — they just point at the foreign catalog instead of a local schema. This is
also how Lakebridge reconcile itself reaches non-Databricks sources (a UC connection
referenced by name in ``reconcile.yml``); for the Lakebridge path a JDBC config
(``jdbc_reader_options``) is the alternative, carried here as a passthrough.

NOTE — untested end to end: there is no external sandbox wired in this environment, so the
federation path below has not been exercised against a live Snowflake/Oracle/etc. The logic
is in place and **guarded**: every step is best-effort and degrades to today's same-catalog
behavior when a source connection is not configured (or federation is unavailable), so the
bundled Databricks-to-Databricks demo is unaffected.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _bt(name: str) -> str:
    """Backtick-quote a single identifier (defensive against reserved words / dots)."""
    return "`" + str(name).replace("`", "``") + "`"


@dataclass
class SourceConnection:
    """How to reach an external source system for reconcile + source-side confirming queries.

    All fields optional; when none are set the source is assumed to live in the same catalog
    as the target (today's Databricks→Databricks behavior).

    catalog       Federated FOREIGN CATALOG name for the source (Lakehouse Federation). When
                  set, source tables resolve to ``<catalog>.<schema>.<table>``.
    connection    UC CONNECTION name holding the source credentials/config. When given
                  alongside ``catalog``, the foreign catalog is created on demand from it.
    jdbc_options  Optional JDBC reader options (host/port/database/driver/...) — a passthrough
                  for the Lakebridge reconcile path (``jdbc_reader_options``); not used by the
                  federation SQL path.
    """

    catalog: str = ""
    connection: str = ""
    jdbc_options: dict[str, Any] = field(default_factory=dict)

    @property
    def enabled(self) -> bool:
        return bool(self.catalog or self.connection or self.jdbc_options)

    @classmethod
    def from_config(cls, cfg: dict[str, Any] | None) -> "SourceConnection":
        """Build from a config/env-style mapping (keys: source_catalog / source_connection /
        source_jdbc_options), tolerating missing keys."""
        cfg = cfg or {}
        return cls(
            catalog=str(cfg.get("source_catalog") or ""),
            connection=str(cfg.get("source_connection") or ""),
            jdbc_options=dict(cfg.get("source_jdbc_options") or {}),
        )


def ensure_foreign_catalog(runner: Any, conn: SourceConnection) -> str:
    """Best-effort: make sure the source foreign catalog exists, creating it from the UC
    connection when both a catalog name and a connection are given. Returns the catalog name
    to use for source tables (``""`` when not configured). Never raises — any federation setup
    error is logged and degrades to a no-op (the caller then falls back to the local catalog).
    """
    if not conn.enabled or not conn.catalog:
        return ""
    if conn.connection and runner is not None:
        try:
            runner.query(
                f"CREATE FOREIGN CATALOG IF NOT EXISTS {_bt(conn.catalog)} "
                f"USING CONNECTION {_bt(conn.connection)}"
            )
        except Exception as exc:  # federation not enabled / no permission / already exists differently
            print(f"[connections] foreign catalog ensure skipped ({conn.catalog}): {exc}")
    return conn.catalog


def resolve_source_catalog(
    conn: SourceConnection | None, default_catalog: str, runner: Any = None
) -> str:
    """The catalog to read SOURCE tables from.

    Returns the federated foreign catalog when a source connection is configured (ensuring it
    exists first, on demand), otherwise the ``default_catalog`` (same-catalog behavior). Safe
    to call with ``conn=None``.
    """
    if conn is not None and conn.enabled:
        cat = ensure_foreign_catalog(runner, conn)
        if cat:
            return cat
        # A connection may declare only jdbc_options (Lakebridge path) with no federated
        # catalog — nothing to resolve for the SQL path; fall through to the default.
    return default_catalog
