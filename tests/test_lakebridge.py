"""Tests for Lakebridge-artifact parsing (recon config, source DDL, transpiled SQL)
against the real migration scripts in this repo."""

from __future__ import annotations

from conftest import REPO_ROOT

from rca_engine.lakebridge import (
    build_mapping,
    parse_source_ddl,
    parse_transpiled_sql,
)

PIPELINE = REPO_ROOT / "migration" / "pipeline"
RECON_CFG = REPO_ROOT / "migration" / "recon" / "30_reconcile_config.json"
RECON_CFG_ADV = REPO_ROOT / "migration" / "recon" / "31_reconcile_config_advanced.json"
SOURCE_SQL = REPO_ROOT / "migration" / "source_sql"


def test_recon_config_gives_join_keys():
    m = build_mapping(recon_config_path=RECON_CFG)
    assert m["fact_orders"].join_keys == ["order_id"]
    assert m["agg_daily_sales"].join_keys == ["store_id", "sales_date"]


def test_transpiled_sql_extracts_timezone_transform():
    m = parse_transpiled_sql((PIPELINE / "21_silver_transform.sql").read_text())
    order_ts = m["fact_orders"].transforms["order_ts"]
    assert "MAKE_INTERVAL" in order_ts.functions
    assert not order_ts.is_direct


def test_transpiled_sql_detects_load_filter():
    m = parse_transpiled_sql((PIPELINE / "21_silver_transform.sql").read_text())
    assert "order_id" in (m["fact_orders"].target_filter or "").lower()


def test_transpiled_sql_direct_passthrough():
    m = parse_transpiled_sql((PIPELINE / "21_silver_transform.sql").read_text())
    assert m["fact_orders"].transforms["customer_id"].is_direct


def test_source_ddl_types_and_scale():
    types = parse_source_ddl((SOURCE_SQL / "01_source_ddl.sql").read_text())
    assert types["fact_order_items"]["amount"].startswith("DECIMAL(18")
    assert "LTZ" in types["fact_orders"]["order_ts"]


def test_advanced_recon_config_parses_features():
    m = build_mapping(recon_config_path=RECON_CFG_ADV)
    # column_mapping (rename): edge_geo country -> country_name
    assert m["edge_geo"].column_map.get("country") == "country_name"
    # transformations
    assert "trim(lower" in m["dim_product"].recon_transform_for("sku")["target"].lower()
    # column_thresholds
    assert m["fact_order_items"].threshold_for("amount")["upper"] == "0.005"
    # table_thresholds
    assert m["fact_orders"].table_thresholds and m["fact_orders"].table_thresholds[0]["model"] == "mismatch"
    # filters
    assert "order_ts" in m["fact_orders"].source_filter
    # select / drop columns
    assert "region" in m["dim_store"].select_columns
    assert "updated_ts" in m["dim_customer"].drop_columns
    # jdbc reader options
    assert m["fact_orders"].jdbc_reader_options.get("number_partitions") == 8


def test_recon_config_features_surface_as_evidence():
    from rca_engine.classify import classify_all
    from rca_engine.models import Finding, MismatchSample, ReconType

    m = build_mapping(recon_config_path=RECON_CFG_ADV)
    f = Finding(recon_id="r1", source_table="edge_geo", target_table="edge_geo",
                recon_type=ReconType.COLUMN_MISMATCH, column="lat", mismatch_count=1,
                total_count=20,
                samples=[MismatchSample(keys={"geo_id": 1}, column="lat",
                                        source_value="10.5", target_value="10.5000001")])
    out = classify_all([f], mapping=m)
    details = " ".join(e.detail for e in out[0].top_hypothesis.evidence)
    assert "tolerance" in details.lower()


def test_full_build_mapping_merges_sources():
    m = build_mapping(recon_config_path=RECON_CFG, transpiled_output=PIPELINE,
                      source_scripts=SOURCE_SQL)
    fo = m["fact_orders"]
    assert fo.join_keys == ["order_id"]                       # from recon config
    assert "MAKE_INTERVAL" in fo.transforms["order_ts"].functions  # from transpiled SQL
    assert fo.source_types["order_total"].startswith("DECIMAL")    # from source DDL
