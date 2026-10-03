"""Step 2: validate and clean the hourly electricity data, then select buildings.

Real BDG2 layout (checked by printing the files, not assumed):
  electricity.csv  wide: `timestamp` + one column per building_id, hourly kWh,
                   local time, 2016-01-01 00:00 to 2017-12-31 23:00
  metadata.csv     one row per building: building_id, site_id,
                   primaryspaceusage, sqm, sqft, electricity ("Yes"/NaN), ...
  weather.csv      long: timestamp, site_id, airTemperature (deg C), ...

Order of work:
  1. Candidate pool = Retail + Office buildings with an electricity meter, at
     sites that have at least one Retail building (so weather is shared).
  2. Pick the analysis year (the one where Retail data coverage is best).
  3. Run every check on every candidate and COUNT what each check finds.
  4. Turn invalid readings into gaps, fill only short gaps, flag every fill.
  5. Pass/fail each building against thresholds in config.yaml.
  6. Select all passing Retail buildings + a seeded random sample of passing
     offices per site.
"""

import json

import numpy as np
import pandas as pd

from common import (INTERIM, PROCESSED, RAW, SQFT_TO_M2, banner,
                    fill_short_gaps, load_config, param, run_lengths)


# ---------------------------------------------------------------------------
# 1. Candidate pool
# ---------------------------------------------------------------------------
def candidate_pool(cfg):
    meta = pd.read_csv(RAW / "metadata.csv")
    primary = param(cfg, "primary_building_types")
    fill = param(cfg, "fill_building_types")
    has_meter = meta["electricity"].eq("Yes")

    primary_sites = meta.loc[has_meter & meta["primaryspaceusage"].isin(primary), "site_id"].unique()
    pool = meta[has_meter
                & meta["primaryspaceusage"].isin(primary + fill)
                & meta["site_id"].isin(primary_sites)].copy()
    print(f"Retail-labelled buildings in BDG2: {meta['primaryspaceusage'].eq('Retail').sum()}, "
          f"with an electricity meter: {(has_meter & meta['primaryspaceusage'].eq('Retail')).sum()}")
    print(f"Sites with Retail buildings: {sorted(primary_sites)}")
    print(f"Candidate pool: {len(pool)} buildings "
          f"({pool['primaryspaceusage'].value_counts().to_dict()})")
    return pool


# ---------------------------------------------------------------------------
# 2. Analysis year
# ---------------------------------------------------------------------------
def valid_mask(values, treat_zero_as_missing):
    """Present (not NaN), not negative, and (optionally) not zero."""
    ok = values.notna() & values.ge(0)
    return ok & values.ne(0) if treat_zero_as_missing else ok


def choose_year(elec, primary_ids, cfg):
    setting = param(cfg, "analysis_year")
    coverage = {}
    for year, block in elec.groupby(elec.index.year):
        ok = valid_mask(block[primary_ids], param(cfg, "treat_zero_as_missing"))
        coverage[int(year)] = round(float(ok.mean().median() * 100), 2)
    print(f"Median % valid hours of Retail candidates by year: {coverage}")
    year = max(coverage, key=coverage.get) if setting == "auto" else int(setting)
    print(f"Analysis year: {year} (setting: {setting})")
    return year, coverage


# ---------------------------------------------------------------------------
# 3 + 4. Checks, then cleaning, for one building
# ---------------------------------------------------------------------------
def validate_building(raw, expected_index, cfg):
    """Run all checks on one building's hourly series.

    Returns (hourly DataFrame, dict of counts). The `issue` column records WHY a
    reading was removed; `filled_flag` marks every interpolated value.
    Each reading is counted under the first check that catches it, so the
    counts add up to the total number of invalid hours.
    """
    n_duplicates = int(raw.index.duplicated(keep="first").sum())
    raw = raw[~raw.index.duplicated(keep="first")]
    missing_ts = ~expected_index.isin(raw.index)
    s = raw.reindex(expected_index)

    issue = pd.Series("", index=s.index, dtype=object)
    issue[missing_ts] = "missing_timestamp"
    issue[(issue == "") & s.isna()] = "missing_value"
    issue[(issue == "") & s.lt(0)] = "negative"
    if param(cfg, "treat_zero_as_missing"):
        issue[(issue == "") & s.eq(0)] = "zero"

    still_ok = issue == ""
    p99 = s[still_ok].quantile(0.99)
    issue[still_ok & s.gt(param(cfg, "spike_multiple_of_p99") * p99)] = "spike"

    # Flatline: identical consecutive values. NaN never equals NaN, so gaps
    # break runs. A new run starts wherever the value changes.
    run_id = (s != s.shift()).cumsum()
    run_len = s.groupby(run_id).transform("size")
    still_ok = issue == ""
    issue[still_ok & run_len.ge(param(cfg, "flatline_min_hours"))] = "flatline"

    clean = s.where(issue == "")
    kwh, filled = fill_short_gaps(clean, param(cfg, "max_fill_gap_hours"))

    counts = issue.value_counts()
    n = len(expected_index)
    invalid = int((issue != "").sum())
    report = {
        "expected_hours": n,
        "missing_timestamps": int(counts.get("missing_timestamp", 0)),
        "duplicate_timestamps": n_duplicates,
        "missing_values": int(counts.get("missing_value", 0)),
        "negative_readings": int(counts.get("negative", 0)),
        "zero_readings": int(counts.get("zero", 0)),
        "spike_readings": int(counts.get("spike", 0)),
        "flatline_hours": int(counts.get("flatline", 0)),
        "invalid_hours": invalid,
        "pct_valid": round(100 * (n - invalid) / n, 2),
        "filled_hours": int(filled.sum()),
        "pct_filled": round(100 * filled.sum() / n, 2),
        "excluded_hours": int(kwh.isna().sum()),
        "longest_gap_hours": int(run_lengths(clean.isna()).max()),
        "p99_kwh": round(float(p99), 3),
        "kwh_after_cleaning": float(kwh.sum()),
    }
    hourly = pd.DataFrame({"timestamp": expected_index, "kwh_raw": s.values,
                           "kwh": kwh.values, "issue": issue.values,
                           "filled_flag": filled.values})
    return hourly, report


# ---------------------------------------------------------------------------
# 5. Pass / fail
# ---------------------------------------------------------------------------
def judge(row, cfg):
    """Return (quality_flag, fail_reasons) for one row of the quality report."""
    reasons = []
    if row["pct_valid"] < param(cfg, "min_pct_valid"):
        reasons.append(f"pct_valid<{param(cfg, 'min_pct_valid')}")
    if row["pct_filled"] > param(cfg, "max_pct_filled"):
        reasons.append(f"pct_filled>{param(cfg, 'max_pct_filled')}")
    if not row["area_units_consistent"]:
        reasons.append("sqm_sqft_mismatch")
    if not (param(cfg, "eui_plausible_min") <= row["eui_annualised"] <= param(cfg, "eui_plausible_max")):
        reasons.append("eui_implausible")
    if reasons:
        return "fail", ";".join(reasons)
    return ("pass" if row["invalid_hours"] == 0 else "pass_with_fixes"), ""


# ---------------------------------------------------------------------------
# 6. Selection
# ---------------------------------------------------------------------------
def select_buildings(report, cfg):
    rng = np.random.default_rng(cfg["project"]["random_seed"])
    passed = report[report["quality_flag"] != "fail"]
    primary = passed[passed["building_type"].isin(param(cfg, "primary_building_types"))]
    chosen = list(primary["building_id"])

    fill = passed[passed["building_type"].isin(param(cfg, "fill_building_types"))]
    k = param(cfg, "fill_buildings_per_site")
    for site in sorted(fill["site_id"].unique()):
        ids = sorted(fill.loc[fill["site_id"] == site, "building_id"])
        chosen += sorted(rng.choice(ids, size=min(k, len(ids)), replace=False))

    lo, hi = param(cfg, "min_buildings"), param(cfg, "max_buildings")
    if not lo <= len(chosen) <= hi:
        raise SystemExit(f"Selected {len(chosen)} buildings, outside the {lo}-{hi} range. "
                         "Adjust fill_buildings_per_site in config.yaml.")
    return chosen


# ---------------------------------------------------------------------------
# Weather
# ---------------------------------------------------------------------------
def clean_weather(sites, year, cfg):
    w = pd.read_csv(RAW / "weather.csv", usecols=["timestamp", "site_id", "airTemperature"],
                    parse_dates=["timestamp"])
    w = w[w["site_id"].isin(sites) & (w["timestamp"].dt.year == year)]
    expected = pd.date_range(f"{year}-01-01", f"{year}-12-31 23:00", freq="h")
    frames, notes = [], {}
    for site, g in w.groupby("site_id"):
        n_dup = int(g.duplicated("timestamp").sum())
        temp = g.drop_duplicates("timestamp").set_index("timestamp")["airTemperature"].reindex(expected)
        n_missing = int(temp.isna().sum())
        filled_temp, was_filled = fill_short_gaps(temp, param(cfg, "weather_max_fill_gap_hours"))
        notes[site] = {"duplicate_timestamps": n_dup, "missing_hours": n_missing,
                       "filled_hours": int(was_filled.sum()),
                       "still_missing": int(filled_temp.isna().sum())}
        frames.append(pd.DataFrame({"site_id": site, "timestamp": expected,
                                    "temp_c": filled_temp.values,
                                    "temp_filled_flag": was_filled.values}))
    return pd.concat(frames, ignore_index=True), notes


def main():
    cfg = load_config()
    banner("STEP 2: validate and clean")

    pool = candidate_pool(cfg)
    primary_ids = list(pool.loc[pool["primaryspaceusage"].isin(param(cfg, "primary_building_types")), "building_id"])

    elec = pd.read_csv(RAW / "electricity.csv", usecols=["timestamp"] + list(pool["building_id"]),
                       parse_dates=["timestamp"]).set_index("timestamp")
    print(f"electricity.csv: {len(elec):,} rows from {elec.index.min()} to {elec.index.max()}")

    year, coverage = choose_year(elec, primary_ids, cfg)
    year_block = elec[elec.index.year == year]
    expected_index = pd.date_range(f"{year}-01-01", f"{year}-12-31 23:00", freq="h")

    rows, hourly = [], {}
    for _, b in pool.iterrows():
        h, rep = validate_building(year_block[b["building_id"]], expected_index, cfg)
        area_ok = abs(b["sqm"] - b["sqft"] * SQFT_TO_M2) <= param(cfg, "area_tolerance_m2")
        usable = rep["expected_hours"] - rep["excluded_hours"]
        rep.update({
            "building_id": b["building_id"], "site_id": b["site_id"],
            "building_type": b["primaryspaceusage"], "floor_area_m2": b["sqm"],
            "year": year, "area_units_consistent": bool(area_ok),
            # annualised = scale the measured kWh up to a full year of hours
            "eui_annualised": round(rep["kwh_after_cleaning"] * rep["expected_hours"] / usable / b["sqm"], 1),
        })
        rows.append(rep)
        hourly[b["building_id"]] = h

    report = pd.DataFrame(rows)
    report[["quality_flag", "fail_reasons"]] = report.apply(lambda r: pd.Series(judge(r, cfg)), axis=1)
    selected = select_buildings(report, cfg)
    report["selected"] = report["building_id"].isin(selected)

    cols = ["building_id", "site_id", "building_type", "floor_area_m2", "year", "expected_hours",
            "missing_timestamps", "duplicate_timestamps", "missing_values", "negative_readings",
            "zero_readings", "spike_readings", "flatline_hours", "invalid_hours", "pct_valid",
            "filled_hours", "pct_filled", "excluded_hours", "longest_gap_hours",
            "area_units_consistent", "eui_annualised", "quality_flag", "fail_reasons", "selected"]
    report = report[cols].sort_values(["selected", "building_type", "building_id"],
                                      ascending=[False, False, True])
    report.to_csv(PROCESSED / "data_quality_report.csv", index=False)

    # ---- console summary: the count for every check -----------------------
    check_cols = ["missing_timestamps", "duplicate_timestamps", "missing_values", "negative_readings",
                  "zero_readings", "spike_readings", "flatline_hours", "filled_hours", "excluded_hours"]
    print("\nCheck totals over ALL candidates (hours):")
    print(report[check_cols].sum().to_string())
    print("\nPass/fail by type:")
    print(report.groupby(["building_type", "quality_flag"]).size().to_string())
    print("\nFailed buildings:")
    print(report.loc[report["quality_flag"] == "fail",
                     ["building_id", "pct_valid", "pct_filled", "eui_annualised", "fail_reasons"]].to_string(index=False))
    sel = report[report["selected"]]
    print(f"\nSelected {len(sel)} buildings: {sel['building_type'].value_counts().to_dict()}")
    print(sel[["building_id", "floor_area_m2", "pct_valid", "filled_hours", "excluded_hours",
               "eui_annualised", "quality_flag"]].to_string(index=False))

    # ---- interim outputs for the next steps -------------------------------
    long = pd.concat([hourly[b].assign(building_id=b) for b in selected], ignore_index=True)
    long = long[["building_id", "timestamp", "kwh_raw", "kwh", "issue", "filled_flag"]]
    long.to_parquet(INTERIM / "hourly_clean.parquet", index=False)

    meta = pool.set_index("building_id").loc[selected].reset_index()
    buildings = pd.DataFrame({
        "building_id": meta["building_id"], "site_id": meta["site_id"],
        "building_type": meta["primaryspaceusage"], "sub_type": meta["sub_primaryspaceusage"],
        "floor_area_m2": meta["sqm"], "floor_area_sqft": meta["sqft"],
        "timezone": meta["timezone"], "lat": meta["lat"], "lng": meta["lng"],
        "year_built": meta["yearbuilt"],
    }).merge(report[["building_id", "quality_flag"]], on="building_id")
    buildings.to_csv(INTERIM / "buildings.csv", index=False)

    weather, weather_notes = clean_weather(sorted(buildings["site_id"].unique()), year, cfg)
    weather.to_parquet(INTERIM / "weather_hourly.parquet", index=False)
    print(f"\nWeather checks per site: {weather_notes}")

    run_info = {
        "analysis_year": year,
        "year_coverage_median_pct_valid_retail": coverage,
        "n_candidates": int(len(report)),
        "n_candidates_by_type": report["building_type"].value_counts().to_dict(),
        "n_failed": int((report["quality_flag"] == "fail").sum()),
        "n_selected": len(selected),
        "n_selected_by_type": sel["building_type"].value_counts().to_dict(),
        "selected_check_totals": {c: int(sel[c].sum()) for c in check_cols + ["invalid_hours"]},
        "selected_hours_total": int(sel["expected_hours"].sum()),
        "weather": weather_notes,
    }
    (INTERIM / "run_info.json").write_text(json.dumps(run_info, indent=2), encoding="utf-8")
    print(f"\nWrote {PROCESSED / 'data_quality_report.csv'}, {INTERIM / 'hourly_clean.parquet'}, "
          f"buildings.csv, weather_hourly.parquet, run_info.json")


if __name__ == "__main__":
    main()
