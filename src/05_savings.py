"""Step 5: savings opportunities, always as ESTIMATES under stated assumptions.

Three opportunity types (they OVERLAP, so never add them together):
  after_hours_excess   kWh used outside the assumed opening hours above the
                       building's own baseload. An UPPER BOUND: some of that
                       load is legitimate (cleaning, restocking, IT, cooling).
  baseload_reduction   What-if: cut the always-on baseload by 5/10/15%.
                       Scenario inputs, not predictions.
  benchmark_gap        If a building at or above the 75th-percentile EUI of its
                       type reached the type median EUI.

Money uses an assumed INR tariff and CO2 uses the CEA India factor; the
buildings are in the USA and Ireland, so both are for illustration only.
All kWh are scaled to a full year (same "annualised" basis as EUI).
"""

import json

import numpy as np
import pandas as pd

from common import INTERIM, banner, co2_tonnes, load_config, param


def opportunities(hourly, annual, cfg):
    tariff = param(cfg, "tariff_inr_per_kwh")
    factor = param(cfg, "emission_factor_t_per_mwh")
    a = annual.set_index("building_id")
    annualise = a["expected_hours"] / a["valid_hours"]
    rows = []

    # 1. after-hours load above the building's own baseload floor
    h = hourly[~hourly["is_open"]].copy()
    h["excess"] = (h["kwh"] - h["building_id"].map(a["baseload_kw"])).clip(lower=0)
    excess = h.groupby("building_id")["excess"].sum() * annualise
    for b, kwh in excess.items():
        rows.append((b, "after_hours_excess", "upper bound", kwh, "upper-bound estimate",
                     f"after-hours kWh above baseload {a.at[b, 'baseload_kw']:.1f} kW, assumed opening hours"))

    # 2. baseload reduction scenarios
    for r in param(cfg, "baseload_reduction_scenarios"):
        for b in a.index:
            kwh = r * a.at[b, "baseload_kw"] * a.at[b, "expected_hours"]
            rows.append((b, "baseload_reduction", f"{r:.0%}", kwh, "what-if scenario",
                         f"{r:.0%} x baseload {a.at[b, 'baseload_kw']:.1f} kW x {a.at[b, 'expected_hours']} h"))

    # 3. benchmark gap: worst-quartile buildings reaching the peer median
    start, target = param(cfg, "benchmark_from_percentile"), param(cfg, "benchmark_target_percentile")
    for t, g in annual.groupby("building_type"):
        target_eui = np.percentile(g["eui_kwh_m2"], target)
        start_eui = np.percentile(g["eui_kwh_m2"], start)
        for _, b in g[g["eui_kwh_m2"] >= start_eui].iterrows():
            kwh = (b["eui_kwh_m2"] - target_eui) * b["floor_area_m2"]
            rows.append((b["building_id"], "benchmark_gap", f"P{start}+ to P{target}", kwh, "benchmark gap",
                         f"EUI {b['eui_kwh_m2']:.0f} -> {t} P{target} {target_eui:.0f} kWh/m2/yr "
                         f"x {b['floor_area_m2']:,.0f} m2"))

    opp = pd.DataFrame(rows, columns=["building_id", "opportunity_type", "scenario", "kwh_saving",
                                      "estimate_label", "basis"])
    opp = opp.merge(annual[["building_id", "building_type", "kwh_annualised"]], on="building_id")
    opp["inr_saving"] = opp["kwh_saving"] * tariff
    opp["co2_saving_t"] = co2_tonnes(opp["kwh_saving"], factor)
    opp["pct_of_building_kwh"] = 100 * opp["kwh_saving"] / opp["kwh_annualised"]
    opp["is_headline"] = opp["opportunity_type"] == param(cfg, "headline_opportunity")

    # Rank one row per building and opportunity type (the middle baseload
    # scenario stands in for the three), largest INR first.
    not_ranked = opp["opportunity_type"].eq("baseload_reduction") & \
        opp["scenario"].ne(f"{param(cfg, 'ranking_baseload_scenario'):.0%}")
    opp["rank"] = opp["inr_saving"].where(~not_ranked).rank(ascending=False, method="first")
    opp = opp.sort_values(["rank", "opportunity_type", "building_id"], na_position="last").reset_index(drop=True)
    opp.insert(0, "opportunity_id", np.arange(1, len(opp) + 1))
    return opp.drop(columns="kwh_annualised")


def main():
    cfg = load_config()
    banner("STEP 5: savings opportunities (estimates)")
    hourly = pd.read_parquet(INTERIM / "hourly_kpi.parquet")
    annual = pd.read_parquet(INTERIM / "annual.parquet")

    opp = opportunities(hourly, annual, cfg)
    opp.to_parquet(INTERIM / "opportunities.parquet", index=False)

    total_kwh = annual["kwh_annualised"].sum()
    summary = {}
    for (t, s), g in opp.groupby(["opportunity_type", "scenario"]):
        summary[f"{t} | {s}"] = {
            "buildings": int(g["building_id"].nunique()), "kwh": float(g["kwh_saving"].sum()),
            "inr": float(g["inr_saving"].sum()), "co2_t": float(g["co2_saving_t"].sum()),
            "pct_of_portfolio_kwh": float(100 * g["kwh_saving"].sum() / total_kwh),
        }
    (INTERIM / "savings_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    pd.set_option("display.width", 220)
    print(f"Tariff {param(cfg, 'tariff_inr_per_kwh')} INR/kWh (ASSUMPTION), "
          f"factor {param(cfg, 'emission_factor_t_per_mwh')} tCO2/MWh (ASSUMPTION, demo)\n")
    print(pd.DataFrame(summary).T.round(1).to_string())
    print("\nTop 10 ranked opportunities (overlapping types - do not add):")
    top = opp.dropna(subset=["rank"]).head(10)
    print(top[["rank", "building_id", "opportunity_type", "scenario", "kwh_saving", "inr_saving",
               "co2_saving_t", "pct_of_building_kwh"]].round(1).to_string(index=False))


if __name__ == "__main__":
    main()
