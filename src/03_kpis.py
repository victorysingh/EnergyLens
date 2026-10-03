"""Step 3: energy KPIs per building per day, month and year.

Key ideas
  * An hourly kWh reading is also the AVERAGE kW over that hour, so the
    largest hourly reading is the peak demand in kW (at hourly resolution).
  * EUI = annual kWh / floor area. A building with a few excluded hours has
    its measured kWh scaled up to a full year ("annualised") so gaps do not
    make it look more efficient than it is.
  * CO2 (Scope 2, location-based) = kWh x grid emission factor. The factor is
    India's (CEA); the buildings are not in India, so it is a demonstration.
  * Benchmarking compares a building only with buildings of the same type.
"""

import json

import numpy as np
import pandas as pd

from common import (INTERIM, banner, co2_tonnes, eui_kwh_per_m2, is_open,
                    load_config, operating_hours_for, param)


def add_operating_hours(hourly, buildings, cfg):
    """Add `is_open` (assumed opening hours) to every hourly row."""
    hourly["is_open"] = False
    for _, b in buildings.iterrows():
        rows = hourly["building_id"] == b["building_id"]
        open_h, close_h, days = operating_hours_for(cfg, b["building_id"], b["building_type"])
        hourly.loc[rows, "is_open"] = is_open(hourly.loc[rows, "timestamp"], open_h, close_h, days)
    return hourly


def daily_table(hourly, cfg):
    base = param(cfg, "degree_day_base_c")
    pct = param(cfg, "baseload_percentile") / 100
    hourly["after_hours_kwh"] = hourly["kwh"].where(~hourly["is_open"])
    g = hourly.groupby(["building_id", "date"])
    daily = g.agg(
        kwh=("kwh", "sum"),
        valid_hours=("kwh", "count"),
        filled_hours=("filled_flag", "sum"),
        peak_kw=("kwh", "max"),
        baseload_kw=("kwh", lambda s: s.quantile(pct)),
        after_hours_kwh=("after_hours_kwh", "sum"),
        temp_mean_c=("temp_c", "mean"),
    ).reset_index()
    daily.loc[daily["valid_hours"] == 0, ["kwh", "after_hours_kwh"]] = np.nan
    daily["complete_day"] = daily["valid_hours"] == 24
    daily["filled_flag"] = daily["filled_hours"] > 0
    daily["hdd"] = (base - daily["temp_mean_c"]).clip(lower=0)
    daily["cdd"] = (daily["temp_mean_c"] - base).clip(lower=0)
    return daily


def monthly_table(hourly, buildings, cfg):
    factor = param(cfg, "emission_factor_t_per_mwh")
    hourly["month_start"] = hourly["timestamp"].dt.to_period("M").dt.to_timestamp()
    m = hourly.groupby(["building_id", "month_start"]).agg(
        kwh=("kwh", "sum"), valid_hours=("kwh", "count"), peak_kw=("kwh", "max"),
    ).reset_index()
    m = m.merge(buildings[["building_id", "floor_area_m2"]], on="building_id")
    m["year_month"] = m["month_start"].dt.strftime("%Y-%m")
    m["eui_month"] = eui_kwh_per_m2(m["kwh"], m["floor_area_m2"])
    m["co2_tonnes"] = co2_tonnes(m["kwh"], factor)
    m["mean_kw"] = m["kwh"] / m["valid_hours"]
    m["load_factor"] = m["mean_kw"] / m["peak_kw"]
    return m.drop(columns="floor_area_m2")


def annual_table(hourly, daily, buildings, cfg, year):
    factor = param(cfg, "emission_factor_t_per_mwh")
    expected_hours = len(pd.date_range(f"{year}-01-01", f"{year}-12-31 23:00", freq="h"))
    g = hourly.groupby("building_id")
    a = pd.DataFrame({
        "kwh_measured": g["kwh"].sum(),
        "valid_hours": g["kwh"].count(),
        "peak_kw": g["kwh"].max(),
        "after_hours_kwh": g["after_hours_kwh"].sum(),
        "open_hours_in_year": g["is_open"].sum(),
    })
    # Baseload from complete days only, so a half-missing day cannot drag it down.
    a["baseload_kw"] = daily[daily["complete_day"]].groupby("building_id")["baseload_kw"].mean()
    a = a.reset_index().merge(buildings[["building_id", "site_id", "building_type", "floor_area_m2"]],
                              on="building_id")
    a["year"] = year
    a["expected_hours"] = expected_hours
    a["kwh_annualised"] = a["kwh_measured"] * expected_hours / a["valid_hours"]
    a["eui_kwh_m2"] = eui_kwh_per_m2(a["kwh_annualised"], a["floor_area_m2"])
    a["co2_tonnes"] = co2_tonnes(a["kwh_annualised"], factor)
    a["mean_kw"] = a["kwh_measured"] / a["valid_hours"]
    a["load_factor"] = a["mean_kw"] / a["peak_kw"]
    a["baseload_share"] = a["baseload_kw"] / a["mean_kw"]
    a["after_hours_share"] = a["after_hours_kwh"] / a["kwh_measured"]
    # Share of the year's HOURS that are after-hours. A perfectly flat load would
    # have after_hours_share == after_hours_time_share, so compare the two.
    a["after_hours_time_share"] = 1 - a["open_hours_in_year"] / expected_hours

    # Reality check on the opening-hours ASSUMPTION: a building that is really
    # closed at weekends uses far less on Sat/Sun than on weekdays.
    full = daily[daily["complete_day"]].assign(weekend=lambda d: d["date"].dt.dayofweek >= 5)
    by_daytype = full.groupby(["building_id", "weekend"])["kwh"].mean().unstack()
    a["weekend_weekday_ratio"] = a["building_id"].map(by_daytype[True] / by_daytype[False])

    # ---- benchmarking inside each building type ---------------------------
    by_type = a.groupby("building_type")["eui_kwh_m2"]
    a["n_in_type"] = by_type.transform("size")
    a["eui_rank_in_type"] = by_type.rank(method="min").astype(int)          # 1 = lowest EUI = best
    a["eui_percentile_in_type"] = 100 * (a["eui_rank_in_type"] - 1) / (a["n_in_type"] - 1)
    a["peer_median_eui"] = by_type.transform("median")
    a["peer_p25_eui"] = by_type.transform(lambda s: np.percentile(s, 25))   # best-quartile threshold
    a["peer_p75_eui"] = by_type.transform(lambda s: np.percentile(s, 75))
    a["gap_to_median_eui"] = a["eui_kwh_m2"] - a["peer_median_eui"]
    a["gap_to_best_quartile_eui"] = a["eui_kwh_m2"] - a["peer_p25_eui"]
    return a.sort_values(["building_type", "eui_rank_in_type"])


def main():
    cfg = load_config()
    banner("STEP 3: KPIs")
    year = json.loads((INTERIM / "run_info.json").read_text())["analysis_year"]
    buildings = pd.read_csv(INTERIM / "buildings.csv")
    hourly = pd.read_parquet(INTERIM / "hourly_clean.parquet")
    weather = pd.read_parquet(INTERIM / "weather_hourly.parquet")

    hourly = hourly.merge(buildings[["building_id", "site_id"]], on="building_id")
    hourly = hourly.merge(weather[["site_id", "timestamp", "temp_c"]], on=["site_id", "timestamp"], how="left")
    hourly["date"] = hourly["timestamp"].dt.normalize()
    hourly = add_operating_hours(hourly, buildings, cfg)

    daily = daily_table(hourly, cfg)
    monthly = monthly_table(hourly, buildings, cfg)
    annual = annual_table(hourly, daily, buildings, cfg, year)

    hourly.to_parquet(INTERIM / "hourly_kpi.parquet", index=False)
    daily.to_parquet(INTERIM / "daily.parquet", index=False)
    monthly.to_parquet(INTERIM / "monthly.parquet", index=False)
    annual.to_parquet(INTERIM / "annual.parquet", index=False)

    total_kwh = annual["kwh_annualised"].sum()
    total_area = annual["floor_area_m2"].sum()
    summary = {
        "year": year,
        "n_buildings": int(len(annual)),
        "total_kwh_measured": float(annual["kwh_measured"].sum()),
        "total_kwh_annualised": float(total_kwh),
        "total_floor_area_m2": float(total_area),
        "portfolio_eui_kwh_m2": float(total_kwh / total_area),
        "total_co2_tonnes": float(annual["co2_tonnes"].sum()),
        "after_hours_share_portfolio": float(annual["after_hours_kwh"].sum() / annual["kwh_measured"].sum()),
        "by_type": {
            t: {
                "n": int(len(g)),
                "eui_min": float(g["eui_kwh_m2"].min()), "eui_p25": float(np.percentile(g["eui_kwh_m2"], 25)),
                "eui_median": float(g["eui_kwh_m2"].median()), "eui_p75": float(np.percentile(g["eui_kwh_m2"], 75)),
                "eui_max": float(g["eui_kwh_m2"].max()),
                "after_hours_share_median": float(g["after_hours_share"].median()),
                "load_factor_median": float(g["load_factor"].median()),
            }
            for t, g in annual.groupby("building_type")
        },
    }
    (INTERIM / "kpi_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    pd.set_option("display.width", 200)
    show = ["building_id", "building_type", "floor_area_m2", "kwh_annualised", "eui_kwh_m2", "co2_tonnes",
            "baseload_kw", "peak_kw", "load_factor", "after_hours_share", "eui_rank_in_type",
            "eui_percentile_in_type", "gap_to_median_eui"]
    print(annual[show].round(2).to_string(index=False))
    print(f"\nPortfolio ({len(annual)} buildings, {year}): {total_kwh:,.0f} kWh (annualised), "
          f"EUI {total_kwh / total_area:.1f} kWh/m2/yr, CO2 {summary['total_co2_tonnes']:,.0f} t "
          f"(demonstration factor {param(cfg, 'emission_factor_t_per_mwh')} tCO2/MWh)")
    print(f"daily rows {len(daily):,}, monthly rows {len(monthly):,}; complete days "
          f"{daily['complete_day'].mean():.1%}")


if __name__ == "__main__":
    main()
