"""Step 6: write Power BI-ready CSVs to data/processed/.

Rules for every file: snake_case headers, ISO dates (YYYY-MM-DD), one header
row, no merged cells, UTF-8. Dimension attributes (site, type, floor area)
live only in dim_building; fact tables carry just building_id and date keys,
which is what makes the star schema work in Power BI.
"""

import json
import re

import pandas as pd

from common import CONFIG_PATH, INTERIM, PROCESSED, banner, load_config, param

# The contract with Power BI and with tests/test_pipeline.py
EXPECTED_COLUMNS = {
    "dim_building.csv": ["building_id", "site", "type", "floor_area_m2", "year", "quality_flag",
                         "sub_type", "country", "timezone", "lat", "lng", "opening_hours_assumed"],
    "dim_date.csv": ["date", "year", "quarter", "month", "month_name", "month_start", "year_month", "week",
                     "day_of_week", "day_name", "is_weekend", "season"],
    "fact_daily_energy.csv": ["building_id", "date", "kwh", "kwh_per_m2", "baseload_kw", "peak_kw",
                              "after_hours_kwh", "temp_mean_c", "hdd", "cdd", "filled_flag",
                              "valid_hours", "complete_day"],
    "fact_hourly_energy.csv": ["building_id", "timestamp", "date", "hour", "kwh", "is_open",
                               "filled_flag", "quality_issue"],
    "fact_monthly_kpi.csv": ["building_id", "year_month", "month_start", "kwh", "eui_month", "co2_tonnes",
                             "load_factor", "peak_kw", "valid_hours"],
    "fact_annual_kpi.csv": ["building_id", "year", "kwh_measured", "kwh_annualised", "valid_hours",
                            "eui_kwh_m2", "co2_tonnes", "baseload_kw", "peak_kw", "mean_kw", "load_factor",
                            "after_hours_kwh", "after_hours_share", "after_hours_time_share",
                            "weekend_weekday_ratio", "eui_rank_in_type", "n_in_type",
                            "eui_percentile_in_type", "peer_median_eui", "peer_p25_eui",
                            "gap_to_median_eui", "gap_to_best_quartile_eui"],
    "fact_anomalies.csv": ["anomaly_id", "building_id", "date", "timestamp", "method", "score", "severity",
                           "reason", "flagged_hours", "actual_kwh", "expected_kwh", "deviation_kwh"],
    "fact_opportunities.csv": ["opportunity_id", "rank", "building_id", "opportunity_type", "scenario",
                               "estimate_label", "kwh_saving", "inr_saving", "co2_saving_t",
                               "pct_of_building_kwh", "is_headline", "basis"],
    "data_quality_report.csv": ["building_id", "site_id", "building_type", "floor_area_m2", "year",
                                "expected_hours", "missing_timestamps", "duplicate_timestamps",
                                "missing_values", "negative_readings", "zero_readings", "spike_readings",
                                "flatline_hours", "invalid_hours", "pct_valid", "filled_hours", "pct_filled",
                                "excluded_hours", "longest_gap_hours", "area_units_consistent",
                                "eui_annualised", "quality_flag", "fail_reasons", "selected"],
    "assumptions.csv": ["key", "value", "resolved_value", "unit", "label", "source", "used_by"],
}
HOURLY_FILE = "fact_hourly_energy.csv"


def iso_date(s):
    return pd.to_datetime(s).dt.strftime("%Y-%m-%d")


def season(month):
    """Meteorological seasons, northern hemisphere (all buildings are in the USA or Ireland)."""
    return {12: "Winter", 1: "Winter", 2: "Winter", 3: "Spring", 4: "Spring", 5: "Spring",
            6: "Summer", 7: "Summer", 8: "Summer", 9: "Autumn", 10: "Autumn", 11: "Autumn"}[month]


def opening_hours_text(cfg, building_id, building_type):
    rule = param(cfg, "operating_hours_overrides").get(building_id) or param(cfg, "operating_hours")[building_type]
    return f"{rule['open']:02d}:00-{rule['close']:02d}:00 {','.join(rule['days'])} (assumption)"


def build_tables(cfg):
    year = json.loads((INTERIM / "run_info.json").read_text())["analysis_year"]
    b = pd.read_csv(INTERIM / "buildings.csv")
    annual = pd.read_parquet(INTERIM / "annual.parquet")
    daily = pd.read_parquet(INTERIM / "daily.parquet")
    monthly = pd.read_parquet(INTERIM / "monthly.parquet")
    hourly = pd.read_parquet(INTERIM / "hourly_kpi.parquet")
    anomalies = pd.read_parquet(INTERIM / "anomalies.parquet")
    opp = pd.read_parquet(INTERIM / "opportunities.parquet")

    t = {}
    t["dim_building.csv"] = pd.DataFrame({
        "building_id": b["building_id"], "site": b["site_id"], "type": b["building_type"],
        "floor_area_m2": b["floor_area_m2"].round(1), "year": year, "quality_flag": b["quality_flag"],
        "sub_type": b["sub_type"],
        "country": b["timezone"].map(lambda z: "Ireland" if z.startswith("Europe/Dublin") else
                                     "USA" if z.startswith("US/") else "unknown"),
        "timezone": b["timezone"], "lat": b["lat"], "lng": b["lng"],
        "opening_hours_assumed": [opening_hours_text(cfg, i, ty) for i, ty in zip(b["building_id"], b["building_type"])],
    })

    dates = pd.date_range(f"{year}-01-01", f"{year}-12-31", freq="D")
    t["dim_date.csv"] = pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d"), "year": dates.year, "quarter": dates.quarter,
        "month": dates.month, "month_name": dates.strftime("%b"),
        "month_start": dates.to_period("M").to_timestamp().strftime("%Y-%m-%d"),
        "year_month": dates.strftime("%Y-%m"), "week": dates.isocalendar().week.to_numpy(),
        "day_of_week": dates.dayofweek + 1, "day_name": dates.strftime("%a"),
        "is_weekend": dates.dayofweek >= 5, "season": [season(m) for m in dates.month],
    })

    area = b.set_index("building_id")["floor_area_m2"]
    d = daily.copy()
    d["kwh_per_m2"] = d["kwh"] / d["building_id"].map(area)
    d["date"] = iso_date(d["date"])
    t["fact_daily_energy.csv"] = d.round({"kwh": 2, "kwh_per_m2": 4, "baseload_kw": 2, "peak_kw": 2,
                                         "after_hours_kwh": 2, "temp_mean_c": 2, "hdd": 2, "cdd": 2})

    t[HOURLY_FILE] = pd.DataFrame({
        "building_id": hourly["building_id"], "timestamp": hourly["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S"),
        "date": iso_date(hourly["date"]), "hour": hourly["timestamp"].dt.hour, "kwh": hourly["kwh"].round(3),
        "is_open": hourly["is_open"], "filled_flag": hourly["filled_flag"], "quality_issue": hourly["issue"],
    })

    m = monthly.copy()
    m["month_start"] = iso_date(m["month_start"])
    t["fact_monthly_kpi.csv"] = m.round({"kwh": 2, "eui_month": 4, "co2_tonnes": 4, "load_factor": 4, "peak_kw": 2})

    t["fact_annual_kpi.csv"] = annual.round(4)

    an = anomalies.copy()
    an["date"] = iso_date(an["date"])
    an["timestamp"] = pd.to_datetime(an["timestamp"]).dt.strftime("%Y-%m-%d %H:%M:%S")
    t["fact_anomalies.csv"] = an.round({"actual_kwh": 2, "expected_kwh": 2, "deviation_kwh": 2})

    t["fact_opportunities.csv"] = opp.round({"kwh_saving": 1, "inr_saving": 0, "co2_saving_t": 3,
                                             "pct_of_building_kwh": 2})

    t["data_quality_report.csv"] = pd.read_csv(PROCESSED / "data_quality_report.csv")

    rows = []
    for key, a in cfg["assumptions"].items():
        value = a["value"]
        resolved = year if key == "analysis_year" else ""
        rows.append({"key": key, "value": json.dumps(value) if isinstance(value, (list, dict, bool)) else value,
                     "resolved_value": resolved, "unit": a["unit"], "label": a["label"],
                     "source": a["source"], "used_by": a["used_by"]})
    t["assumptions.csv"] = pd.DataFrame(rows)

    return {name: df[EXPECTED_COLUMNS[name]] for name, df in t.items()}


def main():
    cfg = load_config()
    banner("STEP 6: export Power BI-ready CSVs")
    tables = build_tables(cfg)
    limit_mb = param(cfg, "hourly_export_max_mb")
    snake = re.compile(r"^[a-z][a-z0-9_]*$")

    for name, df in tables.items():
        if name == HOURLY_FILE:
            est_mb = len(df.to_csv(index=False).encode("utf-8")) / 1e6
            if est_mb > limit_mb:
                (PROCESSED / name).unlink(missing_ok=True)
                print(f"SKIPPED {name}: {est_mb:.1f} MB > {limit_mb} MB limit")
                continue
        df.to_csv(PROCESSED / name, index=False, encoding="utf-8", lineterminator="\n")

    print(f"{'file':28s} {'rows':>9s} {'cols':>5s} {'MB':>7s}  check")
    for name in EXPECTED_COLUMNS:
        path = PROCESSED / name
        if not path.exists():
            print(f"{name:28s} (not written)")
            continue
        back = pd.read_csv(path)          # prove it loads
        ok = list(back.columns) == EXPECTED_COLUMNS[name] and len(back) > 0 \
            and all(snake.match(c) for c in back.columns)
        print(f"{name:28s} {len(back):9,d} {back.shape[1]:5d} {path.stat().st_size / 1e6:7.2f}  "
              f"{'OK' if ok else 'PROBLEM'}")
        if not ok:
            raise SystemExit(f"{name} failed the export check")
    print(f"\nAssumptions exported: {len(tables['assumptions.csv'])} rows from {CONFIG_PATH.name}")


if __name__ == "__main__":
    main()
