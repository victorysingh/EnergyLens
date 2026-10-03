"""Data-quality and unit tests (pytest).

Two kinds of test:
  * FIXTURE tests build tiny hand-made inputs where the right answer can be
    worked out on paper, then check the pipeline's functions against it.
  * OUTPUT tests read the files the pipeline exported and check the rules
    Power BI and the honesty rules depend on.
Run the pipeline first (`make all` runs everything, tests last).
"""

import importlib
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import common  # noqa: E402

validate = importlib.import_module("02_validate_clean")
kpis = importlib.import_module("03_kpis")
anomalies = importlib.import_module("04_anomalies")
export = importlib.import_module("06_export_powerbi")

CFG = common.load_config()
PROCESSED = ROOT / "data" / "processed"
INTERIM = ROOT / "data" / "interim"


def read(name):
    path = PROCESSED / name
    if not path.exists():
        pytest.fail(f"{path} missing - run the pipeline first (make all)")
    return pd.read_csv(path)


# ---------------------------------------------------------------------------
# FIXTURE tests: maths checked against hand-computed values
# ---------------------------------------------------------------------------
def test_eui_matches_hand_computed_value():
    # 1 building, 100 m2, constant 2 kWh every hour of 2017 (8,760 h)
    # annual kWh = 2 * 8760 = 17,520  ->  EUI = 17,520 / 100 = 175.2 kWh/m2/yr
    ts = pd.date_range("2017-01-01", "2017-12-31 23:00", freq="h")
    hourly = pd.DataFrame({"building_id": "B1", "timestamp": ts, "kwh": 2.0, "is_open": False,
                           "after_hours_kwh": 2.0})
    daily = pd.DataFrame({"building_id": "B1", "date": pd.date_range("2017-01-01", "2017-12-31"),
                          "kwh": 48.0, "baseload_kw": 2.0, "complete_day": True})
    buildings = pd.DataFrame({"building_id": ["B1"], "site_id": ["S"], "building_type": ["Retail"],
                              "floor_area_m2": [100.0]})
    a = kpis.annual_table(hourly, daily, buildings, CFG, 2017).iloc[0]
    assert a["kwh_annualised"] == pytest.approx(17520.0)
    assert a["eui_kwh_m2"] == pytest.approx(175.2)
    assert a["load_factor"] == pytest.approx(1.0)        # flat load: average == peak


def test_eui_annualises_gaps():
    # Same building with 760 hours missing: measured 8,000 h * 2 kWh = 16,000 kWh,
    # annualised = 16,000 * 8,760 / 8,000 = 17,520 -> the EUI must not drop.
    ts = pd.date_range("2017-01-01", "2017-12-31 23:00", freq="h")
    kwh = pd.Series(2.0, index=range(len(ts)))
    kwh.iloc[1000:1760] = np.nan
    hourly = pd.DataFrame({"building_id": "B1", "timestamp": ts, "kwh": kwh.values, "is_open": False,
                           "after_hours_kwh": kwh.values})
    daily = pd.DataFrame({"building_id": "B1", "date": pd.date_range("2017-01-01", "2017-12-31"),
                          "kwh": 48.0, "baseload_kw": 2.0, "complete_day": True})
    buildings = pd.DataFrame({"building_id": ["B1"], "site_id": ["S"], "building_type": ["Retail"],
                              "floor_area_m2": [100.0]})
    a = kpis.annual_table(hourly, daily, buildings, CFG, 2017).iloc[0]
    assert a["kwh_measured"] == pytest.approx(16000.0)
    assert a["eui_kwh_m2"] == pytest.approx(175.2)


def test_co2_equals_kwh_times_factor_on_fixture():
    # 1,000,000 kWh = 1,000 MWh; at 0.675 tCO2/MWh -> 675 t
    assert common.co2_tonnes(1_000_000, 0.675) == pytest.approx(675.0)
    kwh = np.array([0.0, 123.4, 98765.0])
    assert np.allclose(common.co2_tonnes(kwh, 0.675), kwh / 1000 * 0.675)


def test_fill_short_gaps_fills_only_short_gaps_and_flags_each_fill():
    s = pd.Series([1.0, np.nan, 3.0,                       # 1-h gap  -> filled (2.0)
                   4.0, np.nan, np.nan, np.nan, 8.0,       # 3-h gap  -> filled (5, 6, 7)
                   9.0, np.nan, np.nan, np.nan, np.nan, 14.0])  # 4-h gap -> left as NaN
    filled, flag = common.fill_short_gaps(s, max_gap_hours=3)
    assert filled.tolist()[:8] == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
    assert filled.iloc[9:13].isna().all()
    assert flag.sum() == 4
    changed = filled.notna() & (s.isna() | (filled != s))
    assert (changed == flag).all(), "every changed value must be flagged, and nothing else"


def test_validation_counts_each_problem_once():
    # 500 hours, long enough that one spike barely moves the building's own P99
    # (with only ~60 hours, the spike itself would inflate P99 and hide itself).
    idx = pd.date_range("2017-01-01", periods=500, freq="h")
    values = pd.Series(np.linspace(10, 20, 500), index=idx)   # all distinct, so no accidental flatline
    values.iloc[5] = -1.0                      # negative
    values.iloc[6] = 0.0                       # zero (dropout)
    values.iloc[7] = np.nan                    # missing value
    values.iloc[300] = 500.0                   # spike (> 3 x P99, P99 is about 20)
    values.iloc[400:425] = 12.5                # flatline: same value for 25 hours
    raw = values.drop(idx[10])                 # one missing timestamp
    raw = pd.concat([raw, raw.iloc[[0]]])      # one duplicate timestamp
    hourly, rep = validate.validate_building(raw, idx, CFG)
    assert rep["missing_timestamps"] == 1
    assert rep["duplicate_timestamps"] == 1
    assert rep["negative_readings"] == 1
    assert rep["zero_readings"] == 1
    assert rep["missing_values"] == 1
    assert rep["spike_readings"] == 1
    assert rep["flatline_hours"] == 25
    assert rep["invalid_hours"] == 1 + 1 + 1 + 1 + 1 + 25   # duplicates are dropped, not counted as invalid
    assert (hourly["kwh"].dropna() > 0).all()


def test_robust_z_and_severity():
    # median 10, MAD 2 -> scale 1.4826 * 2 = 2.9652; value 16 -> z = 6 / 2.9652
    assert common.robust_z([16.0], [10.0], [2.0])[0] == pytest.approx(6 / 2.9652)
    assert common.severity_bucket([3.6, 5.0, 7.9, 8.0], 5.0, 8.0).tolist() == ["low", "med", "med", "high"]


def test_isolation_forest_is_deterministic():
    ts = pd.date_range("2017-01-01", periods=24 * 21, freq="h")
    rng = np.random.default_rng(0)
    h = pd.DataFrame({"building_id": "B1", "timestamp": ts, "kwh": 10 + rng.normal(0, 1, len(ts)),
                      "is_open": ts.hour.isin(range(9, 21)), "filled_flag": False, "temp_c": 15.0})
    h["hour"] = ts.hour
    first = anomalies.isolation_forest(h.copy(), CFG)["if_score"]
    second = anomalies.isolation_forest(h.copy(), CFG)["if_score"]
    assert np.allclose(first.fillna(-1), second.fillna(-1))


# ---------------------------------------------------------------------------
# OUTPUT tests: rules on the exported files
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", list(export.EXPECTED_COLUMNS))
def test_exported_csv_exists_nonempty_with_expected_columns(name):
    df = read(name)
    assert len(df) > 0, f"{name} is empty"
    assert list(df.columns) == export.EXPECTED_COLUMNS[name]
    assert all(re.match(r"^[a-z][a-z0-9_]*$", c) for c in df.columns), "headers must be snake_case"


def test_no_negative_kwh_after_cleaning():
    assert (read("fact_hourly_energy.csv")["kwh"].dropna() >= 0).all()
    assert (read("fact_daily_energy.csv")["kwh"].dropna() >= 0).all()
    hc = pd.read_parquet(INTERIM / "hourly_clean.parquet")
    assert (hc["kwh"].dropna() > 0).all(), "zero and negative readings must be removed by cleaning"


def test_no_duplicate_keys():
    assert not read("fact_hourly_energy.csv").duplicated(["building_id", "timestamp"]).any()
    assert not read("fact_daily_energy.csv").duplicated(["building_id", "date"]).any()
    assert not read("fact_monthly_kpi.csv").duplicated(["building_id", "year_month"]).any()
    assert read("dim_building.csv")["building_id"].is_unique
    assert read("dim_date.csv")["date"].is_unique


def test_every_filled_value_is_flagged():
    hc = pd.read_parquet(INTERIM / "hourly_clean.parquet")
    changed = hc["kwh"].notna() & (hc["kwh_raw"].isna() | (hc["kwh"] != hc["kwh_raw"]))
    assert (changed == hc["filled_flag"]).all()
    assert (hc.loc[hc["filled_flag"], "issue"] != "").all(), "only invalid readings may be filled"
    daily = read("fact_daily_energy.csv")
    hourly = read("fact_hourly_energy.csv")
    days_with_fill = hourly[hourly["filled_flag"]].groupby(["building_id", "date"]).size()
    flagged_days = daily.set_index(["building_id", "date"])["filled_flag"]
    assert flagged_days.loc[days_with_fill.index].all()
    assert flagged_days.sum() == len(days_with_fill)


def test_co2_equals_kwh_times_factor_in_outputs():
    factor = common.param(CFG, "emission_factor_t_per_mwh")
    m = read("fact_monthly_kpi.csv")
    assert np.allclose(m["co2_tonnes"], m["kwh"] / 1000 * factor, atol=1e-3)
    a = read("fact_annual_kpi.csv")
    assert np.allclose(a["co2_tonnes"], a["kwh_annualised"] / 1000 * factor, rtol=1e-6)


def test_eui_in_outputs_matches_kwh_over_area():
    a = read("fact_annual_kpi.csv").merge(read("dim_building.csv"), on="building_id")
    assert np.allclose(a["eui_kwh_m2"], a["kwh_annualised"] / a["floor_area_m2"], rtol=1e-3)


def test_star_schema_keys_resolve():
    buildings = set(read("dim_building.csv")["building_id"])
    dates = set(read("dim_date.csv")["date"])
    for name in ["fact_daily_energy.csv", "fact_hourly_energy.csv", "fact_monthly_kpi.csv",
                 "fact_annual_kpi.csv", "fact_anomalies.csv", "fact_opportunities.csv"]:
        assert set(read(name)["building_id"]) <= buildings, f"{name} has unknown building_id"
    for name in ["fact_daily_energy.csv", "fact_hourly_energy.csv", "fact_anomalies.csv"]:
        assert set(read(name)["date"]) <= dates, f"{name} has dates outside dim_date"
    assert set(read("fact_monthly_kpi.csv")["month_start"]) <= dates


def test_anomaly_table_uses_known_labels():
    an = read("fact_anomalies.csv")
    assert set(an["method"]) <= {"mad_baseline", "isolation_forest", "weather_regression"}
    assert set(an["severity"]) <= {"low", "med", "high"}
    assert set(an["reason"]) <= {"after_hours_load", "daytime_spike", "unexpected_low", "meter_dropout_suspect",
                                 "weather_adjusted_high", "weather_adjusted_low"}


def test_opportunities_are_consistent_with_assumptions():
    opp = read("fact_opportunities.csv")
    tariff = common.param(CFG, "tariff_inr_per_kwh")
    assert (opp["kwh_saving"] >= 0).all()
    assert np.allclose(opp["inr_saving"], opp["kwh_saving"] * tariff, atol=1.0)
    headline = common.param(CFG, "headline_opportunity")
    assert (opp["is_headline"] == (opp["opportunity_type"] == headline)).all()


def test_assumptions_csv_contains_every_config_value():
    asm = read("assumptions.csv").set_index("key")
    for key, entry in CFG["assumptions"].items():
        assert key in asm.index, f"{key} missing from assumptions.csv"
        exported = asm.at[key, "value"]
        value = entry["value"]
        expected = json.dumps(value) if isinstance(value, (list, dict, bool)) else value
        assert str(exported) == str(expected), f"{key}: {exported!r} != {expected!r}"
        assert str(asm.at[key, "source"]).strip(), f"{key} has no source/rationale"
        assert asm.at[key, "label"] in {"ASSUMPTION", "METHOD"}


def test_every_setting_used_in_code_is_exported():
    """Any key read with param(cfg, "...") anywhere in src/ must appear in assumptions.csv,
    so no hidden setting can influence a KPI."""
    keys = set(read("assumptions.csv")["key"])
    used = set()
    for py in (ROOT / "src").glob("*.py"):
        used |= set(re.findall(r'param\(\s*cfg\s*,\s*"([a-z0-9_]+)"', py.read_text(encoding="utf-8")))
    assert used, "no param() calls found - test is broken"
    assert used <= keys, f"used in code but not exported: {sorted(used - keys)}"


def test_key_assumptions_are_labelled_assumption():
    asm = read("assumptions.csv").set_index("key")
    for key in ["tariff_inr_per_kwh", "emission_factor_t_per_mwh", "operating_hours", "baseload_reduction_scenarios"]:
        assert asm.at[key, "label"] == "ASSUMPTION"
    assert "India" in asm.at["emission_factor_t_per_mwh", "source"]
