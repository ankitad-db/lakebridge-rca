"""Direct unit tests for each deterministic probe, including edge variants."""

from __future__ import annotations

import unicodedata

from rca_engine.models import RootCauseCategory as C
from rca_engine.probes import complex as complex_probe
from rca_engine.probes import nullbool, numeric, string, temporal


def _cats(signals):
    return {s.category for s in signals}


# --- numeric ---------------------------------------------------------------
def test_numeric_scale_loss():
    assert C.TYPE_PRECISION in _cats(numeric.probe("12.3456", "12.35"))


def test_numeric_round_to_whole_is_transpilation():
    assert C.TRANSPILATION in _cats(numeric.probe("1234.50", "1235"))


def test_numeric_float_representation():
    assert C.TYPE_PRECISION in _cats(numeric.probe("0.100000", "0.10000000000000001"))


def test_numeric_int_overflow_32bit():
    sigs = numeric.probe("3000000000", "-1294967296")
    assert C.TYPE_PRECISION in _cats(sigs)
    assert any(s.meta.get("bits") == 32 for s in sigs)


def test_numeric_equal_no_signal():
    assert numeric.probe("10.00", "10") == []


# --- temporal --------------------------------------------------------------
def test_temporal_constant_offset_is_timezone():
    assert C.TIMEZONE in _cats(temporal.probe("2026-01-01 00:00:00", "2026-01-01 05:30:00"))


def test_temporal_subsecond_precision():
    assert C.TYPE_PRECISION in _cats(
        temporal.probe("2026-01-01 00:00:00.123456", "2026-01-01 00:00:00.123")
    )


def test_temporal_large_shift_is_upstream_drift():
    assert C.UPSTREAM_DRIFT in _cats(
        temporal.probe("2026-01-01 00:00:00", "2026-01-15 00:00:00")
    )


def test_temporal_date_only_daycount_is_env_config():
    # date-only, whole-day shift -> week-start/bucketing, not a tz offset
    assert C.ENV_CONFIG in _cats(temporal.probe("2026-01-05", "2026-01-04"))


# --- string ----------------------------------------------------------------
def test_string_trailing_whitespace():
    assert C.STRING_FORMAT in _cats(string.probe("Acme", "Acme   "))


def test_string_case_fold():
    assert C.STRING_FORMAT in _cats(string.probe("SKU-1", "sku-1"))


def test_string_unicode_normalization():
    src = unicodedata.normalize("NFC", "café")
    tgt = unicodedata.normalize("NFD", "café")
    assert C.STRING_FORMAT in _cats(string.probe(src, tgt))


# --- nullbool --------------------------------------------------------------
def test_nullbool_null_vs_empty():
    assert C.NULL_BOOLEAN in _cats(nullbool.probe(None, ""))


def test_nullbool_yn_boolean():
    assert C.NULL_BOOLEAN in _cats(nullbool.probe("Y", "true"))


def test_nullbool_int_boolean():
    assert C.NULL_BOOLEAN in _cats(nullbool.probe("1", "true"))


def test_nullbool_null_vs_sentinel_is_migration_not_genuine():
    sigs = nullbool.probe(None, "-1")
    assert C.NULL_BOOLEAN in _cats(sigs)
    assert C.UPSTREAM_DRIFT not in _cats(sigs)


def test_nullbool_null_vs_real_value_is_upstream_drift():
    sigs = nullbool.probe(None, "s10@vendor.com")
    assert C.UPSTREAM_DRIFT in _cats(sigs)
    assert any(s.meta.get("provenance_candidate") for s in sigs)


# --- complex / semi-structured --------------------------------------------
def test_json_reorder_is_semantically_equal():
    sigs = complex_probe.probe('{"a":1,"b":2}', '{"b":2,"a":1}')
    assert C.SEMI_STRUCTURED in _cats(sigs)
    assert any(s.meta.get("semantically_equal") for s in sigs)


def test_json_value_diff_is_not_semantically_equal():
    sigs = complex_probe.probe('{"retries":3}', '{"retries":5}')
    assert C.SEMI_STRUCTURED in _cats(sigs)
    assert not any(s.meta.get("semantically_equal") for s in sigs)
