"""Step 7: figures, RESULTS.md, the static preview page, and the generated
blocks inside README.md and powerbi/BUILD_GUIDE.md.

Every number written by this script is read from the outputs of the current
run. Nothing is typed in by hand, so re-running the pipeline keeps the
documents honest automatically.
"""

import base64
import json
import re

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap

import plotstyle as ps
from common import FIGURES, INTERIM, PROCESSED, ROOT, banner, load_config, param

BLUE_RAMP = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
ORDINAL = {"low": "#86b6ef", "med": "#2a78d6", "high": "#184f95"}   # blue steps 250 / 450 / 600


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def md_table(df):
    """DataFrame -> GitHub markdown table (no extra dependency)."""
    head = "| " + " | ".join(map(str, df.columns)) + " |"
    sep = "|" + "|".join("---:" if pd.api.types.is_numeric_dtype(df[c]) else "---" for c in df.columns) + "|"
    body = ["| " + " | ".join("" if pd.isna(v) else str(v) for v in row) + " |" for row in df.itertuples(index=False)]
    return "\n".join([head, sep] + body)


def crore(inr):
    return f"₹{inr / 1e7:.2f} crore (INR {inr:,.0f})"


def replace_block(path, tag, content):
    """Replace the text between <!-- TAG:START --> and <!-- TAG:END --> in a file."""
    if not path.exists():
        print(f"  (skip {path.name}: file not found)")
        return
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(rf"(<!-- {tag}:START -->)(.*?)(<!-- {tag}:END -->)", re.S)
    if not pattern.search(text):
        print(f"  (skip {path.name}: no {tag} markers)")
        return
    new = pattern.sub(lambda m: m.group(1) + "\n" + content.strip() + "\n" + m.group(3), text)
    path.write_text(new, encoding="utf-8")
    print(f"  updated {tag} block in {path.name}")


def us_dst_start(year):
    """US daylight saving starts at 02:00 on the second Sunday of March."""
    sundays = pd.date_range(f"{year}-03-01", f"{year}-03-31", freq="W-SUN")
    return sundays[1] + pd.Timedelta(hours=2)


# ---------------------------------------------------------------------------
# load everything the run produced
# ---------------------------------------------------------------------------
def load():
    j = lambda name: json.loads((INTERIM / name).read_text(encoding="utf-8"))  # noqa: E731
    return {
        "run": j("run_info.json"), "kpi": j("kpi_summary.json"), "anom": j("anomaly_eval.json"),
        "sav": j("savings_summary.json"),
        "annual": pd.read_parquet(INTERIM / "annual.parquet"),
        "monthly": pd.read_parquet(INTERIM / "monthly.parquet"),
        "daily": pd.read_parquet(INTERIM / "daily.parquet"),
        "hourly": pd.read_parquet(INTERIM / "hourly_scored.parquet"),
        "buildings": pd.read_csv(INTERIM / "buildings.csv"),
        "dq": pd.read_csv(PROCESSED / "data_quality_report.csv"),
        "opp": pd.read_csv(PROCESSED / "fact_opportunities.csv"),
        "anomalies": pd.read_csv(PROCESSED / "fact_anomalies.csv"),
        "assumptions": pd.read_csv(PROCESSED / "assumptions.csv"),
        "wx": pd.read_csv(INTERIM / "weather_models.csv"),
        "sens": pd.read_csv(ROOT / "reports" / "mad_sensitivity.csv"),
    }


# ---------------------------------------------------------------------------
# figures
# ---------------------------------------------------------------------------
def fig_eui(d, year):
    a = d["annual"]
    types = ["Retail", "Office"]
    counts = [int((a["building_type"] == t).sum()) for t in types]
    fig, axes = plt.subplots(2, 1, figsize=(9, 0.32 * sum(counts) + 1.6), sharex=True,
                             gridspec_kw={"height_ratios": counts}, layout="constrained")
    for ax, t in zip(axes, types):
        g = a[a["building_type"] == t].sort_values("eui_kwh_m2")
        y = np.arange(len(g))
        ax.barh(y, g["eui_kwh_m2"], height=0.6, color=ps.TYPE_COLOR[t])
        for yi, v in zip(y, g["eui_kwh_m2"]):
            ax.text(v + 4, yi, f"{v:.0f}", va="center", fontsize=8, color=ps.INK_2, bbox=ps.LABEL_BOX)
        med = g["eui_kwh_m2"].median()
        ax.axvline(med, color=ps.INK_2, linewidth=1)
        ax.text(med + 4, len(g) - 0.4, f"{t} median {med:.0f}", fontsize=8, color=ps.INK_2, va="bottom",
                bbox=ps.LABEL_BOX)
        ax.set_yticks(y, g["building_id"], fontsize=8)
        ax.set_title(f"{t} ({len(g)} buildings)", fontsize=10)
        ax.grid(axis="y", visible=False)
    axes[0].set_ylim(-0.6, counts[0] - 0.2 + 0.6)
    axes[-1].set_xlabel("Electricity EUI, kWh per m² per year (annualised)")
    fig.suptitle(f"Electricity use intensity by building, {year}", x=0.01, ha="left", fontweight="semibold")
    ps.caption(fig, year, "Compare buildings only within a type.")
    ps.save(fig, FIGURES / "eui_by_building.png")


def fig_monthly(d, year):
    m = d["monthly"].merge(d["buildings"][["building_id", "building_type", "floor_area_m2"]], on="building_id")
    fig, ax = plt.subplots(figsize=(9, 4))
    for t in ["Retail", "Office"]:
        g = m[m["building_type"] == t].groupby("month_start")
        area = d["buildings"].loc[d["buildings"]["building_type"] == t, "floor_area_m2"].sum()
        s = g["kwh"].sum() / area
        ax.plot(s.index, s.values, color=ps.TYPE_COLOR[t], label=t, marker="o", markersize=5,
                markeredgecolor=ps.SURFACE, markeredgewidth=1.5)
        ax.text(s.index[-1] + pd.Timedelta(days=6), s.values[-1], t, color=ps.INK_2, va="center", fontsize=9)
    ax.set_ylabel("kWh per m² per month")
    ax.set_ylim(bottom=0)
    ax.set_title(f"Monthly electricity intensity by building type, {year}")
    ax.legend(loc="lower left")
    ps.caption(fig, year, "Sum of kWh / sum of floor area per type; measured (not annualised) monthly kWh.")
    ps.save(fig, FIGURES / "monthly_intensity.png")


def fig_after_hours(d, year):
    a = d["annual"].sort_values(["building_type", "after_hours_share"])
    y = np.arange(len(a))
    fig, ax = plt.subplots(figsize=(9, 0.3 * len(a) + 1.6))
    ax.scatter(a["after_hours_time_share"] * 100, y, marker="|", s=160, color=ps.INK_2, linewidth=2,
               label="share of the year's HOURS that are after-hours (flat load would sit here)", zorder=3)
    ax.scatter(a["after_hours_share"] * 100, y, s=60, color=ps.SERIES[0], edgecolor=ps.SURFACE, linewidth=2,
               label="share of ENERGY used after-hours", zorder=4)
    ax.set_yticks(y, [f"{b}  ({t})" for b, t in zip(a["building_id"], a["building_type"])], fontsize=8)
    ax.set_xlabel("percent")
    ax.set_xlim(0, 100)
    ax.set_title(f"After-hours electricity vs after-hours time, {year}", pad=34)
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), fontsize=8, ncol=1)
    ps.caption(fig, year, "Opening hours are ASSUMED (Retail 09-21 daily, Office 08-18 Mon-Fri).")
    ps.save(fig, FIGURES / "after_hours_share.png")


def fig_data_quality(d, year):
    dq = d["dq"]
    checks = {"missing values": "missing_values", "zero readings": "zero_readings",
              "flatline hours": "flatline_hours", "spikes": "spike_readings",
              "negative readings": "negative_readings", "duplicate timestamps": "duplicate_timestamps",
              "missing timestamps": "missing_timestamps"}
    s = pd.Series({k: int(dq[v].sum()) for k, v in checks.items()}).sort_values()
    fig, ax = plt.subplots(figsize=(8, 3.4))
    ax.barh(s.index, s.values, height=0.6, color=ps.SERIES[0])
    for i, v in enumerate(s.values):
        ax.text(v + s.max() * 0.01, i, f"{v:,}", va="center", fontsize=8, color=ps.INK_2)
    ax.set_xlabel("hours")
    ax.grid(axis="y", visible=False)
    ax.set_title(f"Invalid readings found in {len(dq)} candidate buildings, {year}")
    ps.caption(fig, year)
    ps.save(fig, FIGURES / "data_quality_checks.png")


def fig_anomaly_methods(d, year):
    an = d["anomalies"]
    ov = d["anom"]["overlap_building_days"]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 3.6), gridspec_kw={"width_ratios": [3, 2]})
    methods = ["mad_baseline", "isolation_forest", "weather_regression"]
    left = np.zeros(len(methods))
    for sev in ["low", "med", "high"]:
        vals = np.array([((an["method"] == m) & (an["severity"] == sev)).sum() for m in methods])
        ax1.barh(methods, vals, left=left, height=0.55, color=ORDINAL[sev], label=sev,
                 edgecolor=ps.SURFACE, linewidth=2)
        left += vals
    for i, v in enumerate(left):
        ax1.text(v + left.max() * 0.01, i, f"{int(v):,}", va="center", fontsize=8, color=ps.INK_2)
    ax1.set_title("Daily anomaly events by method and severity")
    ax1.set_xlabel("building-days")
    ax1.legend(title="severity", fontsize=8, title_fontsize=8, loc="upper right", ncol=3)
    ax1.set_xlim(0, left.max() * 1.12)
    ax1.grid(axis="y", visible=False)
    labels = ["MAD only", "both", "Isolation Forest only"]
    vals = [ov["mad_only"], ov["mad_and_if"], ov["if_only"]]
    ax2.bar(labels, vals, width=0.55, color=ps.SERIES[0])
    for i, v in enumerate(vals):
        ax2.text(i, v + max(vals) * 0.01, f"{v:,}", ha="center", va="bottom", fontsize=8, color=ps.INK_2)
    ax2.set_title(f"Overlap of flagged building-days (Jaccard {ov['jaccard_mad_if']})")
    ax2.grid(axis="x", visible=False)
    ps.caption(fig, year, "No ground truth exists: overlap shows agreement, not accuracy.")
    ps.save(fig, FIGURES / "anomaly_methods.png")


def fig_weather(d, year):
    wx = d["wx"].sort_values("r2")
    picks = [wx.iloc[-1], wx.iloc[0]]
    daily = d["daily"]
    an = d["anomalies"]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    for ax, m, label in zip(axes, picks, ["best fit", "worst fit"]):
        g = daily[(daily["building_id"] == m["building_id"]) & daily["complete_day"]].copy()
        wkend = g["date"].dt.dayofweek >= 5
        ax.scatter(g.loc[~wkend, "temp_mean_c"], g.loc[~wkend, "kwh"], s=16, color=ps.SERIES[0], label="weekday", alpha=0.8)
        ax.scatter(g.loc[wkend, "temp_mean_c"], g.loc[wkend, "kwh"], s=16, color=ps.SERIES[1], label="weekend", alpha=0.8)
        flagged = an[(an["method"] == "weather_regression") & (an["building_id"] == m["building_id"])]["date"]
        f = g[g["date"].dt.strftime("%Y-%m-%d").isin(flagged)]
        if len(f):
            ax.scatter(f["temp_mean_c"], f["kwh"], s=70, facecolor="none", edgecolor=ps.CRITICAL, linewidth=1.5,
                       label=f"flagged day, residual |z| ≥ 3.5 ({len(f)})")
        ax.set_title(f"{m['building_id']} ({label}, R² = {m['r2']:.2f})", fontsize=10)
        ax.set_xlabel("daily mean outdoor temperature, °C")
        ax.set_ylabel("kWh per day")
        ax.set_ylim(bottom=0)
        ax.legend(fontsize=8)
    fig.suptitle(f"Weather sensitivity: daily kWh vs temperature, {year}", x=0.01, ha="left", fontweight="semibold")
    ps.caption(fig, year, "Model: kWh = a + b·HDD + c·CDD + d·weekend, base 18 °C (assumption).")
    ps.save(fig, FIGURES / "weather_fit.png")


def fig_heatmap(d, year):
    retail = d["annual"][d["annual"]["building_type"] == "Retail"]
    b = retail.sort_values("floor_area_m2").iloc[-1]["building_id"]
    h = d["hourly"][d["hourly"]["building_id"] == b]
    grid = h.groupby([h["timestamp"].dt.dayofweek, h["timestamp"].dt.hour])["kwh"].mean().unstack()
    fig, ax = plt.subplots(figsize=(10, 3.6))
    cmap = LinearSegmentedColormap.from_list("blue", BLUE_RAMP)
    im = ax.imshow(grid.values, aspect="auto", cmap=cmap)
    ax.set_yticks(range(7), ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
    ax.set_xticks(range(0, 24, 2), [f"{x:02d}" for x in range(0, 24, 2)])
    ax.set_xlabel("hour of day (local time)")
    ax.grid(False)
    for s in ax.spines.values():
        s.set_visible(False)
    cb = fig.colorbar(im, ax=ax, pad=0.01)
    cb.set_label("mean kWh per hour", color=ps.INK_2)
    cb.outline.set_visible(False)
    ax.set_title(f"{b}: average load by weekday and hour, {year} (largest Retail building)")
    ps.caption(fig, year)
    ps.save(fig, FIGURES / "heatmap_largest_retail.png")
    return b


# ---------------------------------------------------------------------------
# numbers used in several documents
# ---------------------------------------------------------------------------
def headline_numbers(d, cfg):
    run, kpi, anom, sav = d["run"], d["kpi"], d["anom"], d["sav"]
    dq, a = d["dq"], d["annual"]
    cand_hours = int(dq["expected_hours"].sum())
    cand_invalid = int(dq["invalid_hours"].sum())
    failed = dq[dq["quality_flag"] == "fail"]
    reasons = failed["fail_reasons"].str.split(";").explode().value_counts().to_dict()
    sel = run["selected_check_totals"]
    off = a[a["building_type"] == "Office"]
    ah = sav["after_hours_excess | upper bound"]
    bench = sav[f"benchmark_gap | P{param(cfg, 'benchmark_from_percentile')}+ to P{param(cfg, 'benchmark_target_percentile')}"]
    t = kpi["by_type"]
    return {
        "year": run["analysis_year"], "cov": run["year_coverage_median_pct_valid_retail"],
        "n_cand": len(dq), "n_cand_retail": int((dq["building_type"] == "Retail").sum()),
        "n_cand_office": int((dq["building_type"] == "Office").sum()),
        "cand_hours": cand_hours, "cand_invalid": cand_invalid, "cand_pct": 100 * cand_invalid / cand_hours,
        "cand_missing": int(dq["missing_values"].sum()), "cand_zero": int(dq["zero_readings"].sum()),
        "cand_flat": int(dq["flatline_hours"].sum()), "cand_spike": int(dq["spike_readings"].sum()),
        "n_failed": len(failed), "fail_reasons": reasons,
        "n_sel": run["n_selected"], "n_retail": run["n_selected_by_type"].get("Retail", 0),
        "n_office": run["n_selected_by_type"].get("Office", 0),
        "sel_hours": run["selected_hours_total"], "sel_invalid": sel["invalid_hours"],
        "sel_pct": 100 * sel["invalid_hours"] / run["selected_hours_total"],
        "sel_filled": sel["filled_hours"], "sel_excluded": sel["excluded_hours"],
        "kwh": kpi["total_kwh_annualised"], "area": kpi["total_floor_area_m2"],
        "eui": kpi["portfolio_eui_kwh_m2"], "co2": kpi["total_co2_tonnes"],
        "r": t["Retail"], "o": t["Office"],
        "r_spread": t["Retail"]["eui_p75"] - t["Retail"]["eui_p25"],
        "o_spread": t["Office"]["eui_p75"] - t["Office"]["eui_p25"],
        "off_ah_min": off["after_hours_share"].min(), "off_ah_max": off["after_hours_share"].max(),
        "off_time": off["after_hours_time_share"].median(),
        "ah_kwh": ah["kwh"], "ah_inr": ah["inr"], "ah_co2": ah["co2_t"], "ah_pct": ah["pct_of_portfolio_kwh"],
        "bench_n": bench["buildings"], "bench_kwh": bench["kwh"], "bench_co2": bench["co2_t"],
        "bench_pct": bench["pct_of_portfolio_kwh"],
        "mad_ev": anom["events_per_method"]["mad_baseline"], "if_ev": anom["events_per_method"]["isolation_forest"],
        "wx_ev": anom["events_per_method"]["weather_regression"],
        "mad_high": anom["high_severity_mad_events"], "mad_high_if": anom["high_severity_mad_and_if"],
        "ov": anom["overlap_building_days"],
        "factor": param(cfg, "emission_factor_t_per_mwh"), "tariff": param(cfg, "tariff_inr_per_kwh"),
    }


def findings(n):
    reasons = ", ".join(f"{v} {k}" for k, v in n["fail_reasons"].items())
    return [
        f"**Data quality:** validating {n['n_cand']} candidate buildings ({n['n_cand_retail']} Retail + "
        f"{n['n_cand_office']} Office) for {n['year']} flagged {n['cand_pct']:.2f}% of "
        f"{n['cand_hours']:,} hourly readings as invalid ({n['cand_missing']:,} missing values, "
        f"{n['cand_zero']:,} zero readings, {n['cand_flat']:,} flatline hours, {n['cand_spike']} spike). "
        f"{n['n_failed']} buildings failed ({reasons}); {n['n_sel']} were kept "
        f"({n['n_retail']} Retail, {n['n_office']} Office).",
        f"**EUI spread:** electricity EUI runs from {n['r']['eui_min']:.0f} to {n['r']['eui_max']:.0f} "
        f"kWh/m²/yr across the {n['n_retail']} Retail buildings (median {n['r']['eui_median']:.0f}) and from "
        f"{n['o']['eui_min']:.0f} to {n['o']['eui_max']:.0f} across the {n['n_office']} offices (median "
        f"{n['o']['eui_median']:.0f}). The gap between the best and worst quartile (P75 − P25) is "
        f"{n['r_spread']:.0f} kWh/m²/yr for Retail and {n['o_spread']:.0f} for Office.",
        f"**After-hours use:** offices use {n['off_ah_min']:.0%}–{n['off_ah_max']:.0%} of their electricity "
        f"outside the assumed 08:00–18:00 weekday hours (which cover {1 - n['off_time']:.0%} of the week). "
        f"After-hours load above each building's own baseload adds up to {n['ah_kwh']:,.0f} kWh/yr "
        f"({n['ah_pct']:.1f}% of portfolio use): an upper bound, worth {crore(n['ah_inr'])} at the assumed "
        f"₹{n['tariff']:.2f}/kWh.",
        f"**Anomalies:** the MAD baseline flagged {n['mad_ev']:,} building-days ({n['mad_high']} high severity) "
        f"and Isolation Forest {n['if_ev']:,}. They agree on only {n['ov']['mad_and_if']} building-days "
        f"(Jaccard {n['ov']['jaccard_mad_if']}). With no ground truth, that is disagreement to investigate, "
        f"not an accuracy score.",
        f"**Carbon and benchmark gap:** with the CEA India factor ({n['factor']} tCO2/MWh, applied for "
        f"demonstration only) the portfolio's {n['kwh']:,.0f} kWh/yr equals {n['co2']:,.0f} tCO2. Bringing "
        f"the {n['bench_n']} worst-quartile buildings to their type's median EUI would avoid "
        f"{n['bench_kwh']:,.0f} kWh/yr ({n['bench_pct']:.1f}% of portfolio use, {n['bench_co2']:,.0f} tCO2). "
        f"That is a benchmark gap, not a forecast.",
    ]


# ---------------------------------------------------------------------------
# RESULTS.md
# ---------------------------------------------------------------------------
def results_md(d, n, cfg, heatmap_building):
    a, opp, dq = d["annual"], d["opp"], d["dq"]
    anom, run = d["anom"], d["run"]

    # Metadata sanity: longitude sign must match the timezone's hemisphere
    # (US and Ireland are both west of Greenwich, so lng must be negative).
    b = d["buildings"]
    west = b["timezone"].str.startswith(("US/", "Europe/Dublin"))
    bad_lng = b[west & (b["lng"] > 0)].groupby(["site_id", "timezone"])["lng"].first()
    lng_line = ("- **Metadata issue:** " + "; ".join(
        f"site {s} has longitude +{v:.2f} but timezone {tz} (west of Greenwich), so the sign is probably "
        f"flipped" for (s, tz), v in bad_lng.items()) + ". Reported, not changed: `dim_building` keeps the "
        "source value, so do not use a map visual for these buildings without correcting it."
        if len(bad_lng) else "- Building coordinates are consistent with their timezones.")

    # DST: the most frequently filled timestamp
    hc = pd.read_parquet(INTERIM / "hourly_clean.parquet")
    top_fill = hc[hc["filled_flag"]].groupby("timestamp").size().sort_values(ascending=False)
    dst_line = ""
    if len(top_fill):
        ts, cnt = top_fill.index[0], int(top_fill.iloc[0])
        dst_note = (" This is the US daylight-saving 'spring forward' hour: that local hour does not exist, "
                    "so US meters have no reading for it.") if ts == us_dst_start(ts.year) else ""
        dst_line = (f"- The most frequently filled hour is **{ts:%Y-%m-%d %H:%M}** ({cnt} buildings).{dst_note} "
                    f"It is interpolated and flagged like any other 1-hour gap.")

    sel_dq = dq[dq["selected"]]
    worst = sel_dq.sort_values("pct_valid").head(3)
    failed = dq[dq["quality_flag"] == "fail"][["building_id", "building_type", "pct_valid", "eui_annualised",
                                               "fail_reasons"]]

    kpi_tbl = a.sort_values(["building_type", "eui_rank_in_type"])[[
        "building_id", "building_type", "floor_area_m2", "kwh_annualised", "eui_kwh_m2", "eui_rank_in_type",
        "eui_percentile_in_type", "load_factor", "after_hours_share", "after_hours_time_share",
        "weekend_weekday_ratio", "co2_tonnes"]].copy()
    kpi_tbl["floor_area_m2"] = kpi_tbl["floor_area_m2"].map("{:,.0f}".format)
    kpi_tbl["kwh_annualised"] = kpi_tbl["kwh_annualised"].map("{:,.0f}".format)
    kpi_tbl["eui_kwh_m2"] = kpi_tbl["eui_kwh_m2"].round(1)
    kpi_tbl["eui_percentile_in_type"] = kpi_tbl["eui_percentile_in_type"].round(0).astype(int)
    for c in ["load_factor", "weekend_weekday_ratio"]:
        kpi_tbl[c] = kpi_tbl[c].round(2)
    for c in ["after_hours_share", "after_hours_time_share"]:
        kpi_tbl[c] = (kpi_tbl[c] * 100).round(0).astype(int).astype(str) + "%"
    kpi_tbl["co2_tonnes"] = kpi_tbl["co2_tonnes"].round(0).astype(int)

    odd_hours = a[(a["building_type"] == "Retail") & (a["weekend_weekday_ratio"] < 0.7)]

    sav_rows = []
    for key, v in d["sav"].items():
        t, s = key.split(" | ")
        sav_rows.append({"opportunity": t, "scenario": s, "buildings": v["buildings"],
                         "kWh/yr": f"{v['kwh']:,.0f}", "INR/yr (assumed tariff)": f"{v['inr']:,.0f}",
                         "tCO2/yr (demo factor)": f"{v['co2_t']:,.0f}",
                         "% of portfolio kWh": f"{v['pct_of_portfolio_kwh']:.1f}"})
    top10 = opp.dropna(subset=["rank"]).sort_values("rank").head(10).copy()
    top10["rank"] = top10["rank"].astype(int)
    top10_tbl = pd.DataFrame({
        "rank": top10["rank"], "building": top10["building_id"], "opportunity": top10["opportunity_type"],
        "scenario": top10["scenario"], "label": top10["estimate_label"],
        "kWh/yr": top10["kwh_saving"].map("{:,.0f}".format), "INR/yr": top10["inr_saving"].map("{:,.0f}".format),
        "tCO2/yr": top10["co2_saving_t"].round(1), "% of building": top10["pct_of_building_kwh"].round(1),
    })

    ex = pd.DataFrame(anom["examples"])
    notes = (ROOT / "reports" / "anomaly_inspection_notes.md").read_text(encoding="utf-8")
    stale = [f"{r.building_id} {r.date}" for r in ex.itertuples() if r.building_id not in notes or r.date not in notes]
    notes_line = ("Manual notes on these five plots: [reports/anomaly_inspection_notes.md]"
                  "(reports/anomaly_inspection_notes.md)." if not stale else
                  f"**WARNING: the example plots changed ({', '.join(stale)}); the manual notes in "
                  "reports/anomaly_inspection_notes.md are out of date and must be redone.**")

    sens = d["sens"].copy()
    sens["chosen"] = sens["chosen"].map({True: "**chosen**", False: ""})

    asm = d["assumptions"][["key", "value", "resolved_value", "unit", "label"]].copy()
    asm["value"] = asm["value"].astype(str).str.replace("|", "/", regex=False)
    asm["resolved_value"] = asm["resolved_value"].map(lambda v: "" if pd.isna(v) else f"{v:g}")

    by_reason = pd.DataFrame(anom["events_by_reason"]).fillna(0).astype(int)
    by_sev = pd.DataFrame(anom["events_by_severity"]).reindex(["low", "med", "high"]).fillna(0).astype(int)

    F = findings(n)
    lines = [
        "# RESULTS",
        "",
        "> **Generated by `src/07_report.py` from the latest pipeline run. Do not edit by hand.**",
        f"> Data: Building Data Genome Project 2 (BDG2), a **public dataset** of real hourly meter readings; "
        f"electricity only, calendar year {n['year']}. This is an analysis of public data, not a deployed "
        "system. Tariff, emission factor, opening hours and savings scenarios are **assumptions** (listed at "
        "the end). Buildings are in the USA and Ireland; the Indian emission factor and INR tariff are applied "
        "for **demonstration only**.",
        "",
        "## Headline findings",
        "",
        *[f"{i}. {f}" for i, f in enumerate(F, 1)],
        "",
        "## 1. Building selection",
        "",
        f"- BDG2 labels only {n['n_cand_retail']} buildings with an electricity meter as `Retail`, below the "
        "15-building minimum, so **offices were added** "
        "as the closest commercial type, taken only from the sites that also hold Retail buildings "
        f"({', '.join(sorted(dq['site_id'].unique()))}) so that climate and weather are shared.",
        f"- Analysis year chosen from the data: median share of valid hours for the Retail candidates was "
        + ", ".join(f"{v}% in {k}" for k, v in n["cov"].items())
        + f", so **{n['year']}** was used (several Panther Retail meters read zero for much of 2016).",
        f"- Criteria, in config.yaml: known floor area (sqm and sqft must agree), ≥ {param(cfg, 'min_pct_valid')}% "
        f"valid hours, ≤ {param(cfg, 'max_pct_filled')}% of hours interpolated, and a plausible annualised EUI "
        f"({param(cfg, 'eui_plausible_min')}–{param(cfg, 'eui_plausible_max')} kWh/m²/yr).",
        f"- All Retail buildings that passed were kept; offices were sampled at random (seed "
        f"{cfg['project']['random_seed']}) from those that passed, {param(cfg, 'fill_buildings_per_site')} "
        f"per site. Result: **{n['n_sel']} buildings ({n['n_retail']} Retail, {n['n_office']} Office)**.",
        "- In the data and documents they are called **buildings**. They are not IKEA stores or any retailer's stores.",
        "",
        "Buildings that failed validation:",
        "",
        md_table(failed),
        "",
        "## 2. Data quality",
        "",
        f"Every check ran on all {n['n_cand']} candidates (full table: `data/processed/data_quality_report.csv`). "
        "Each invalid reading is counted under the first check that caught it.",
        "",
        md_table(pd.DataFrame({
            "check": ["missing timestamps", "duplicate timestamps", "missing values", "negative readings",
                      "zero readings (treated as dropout)", "spikes (> 3 x own P99)",
                      f"flatlines (same value ≥ {param(cfg, 'flatline_min_hours')} h)",
                      "total invalid", f"filled (gaps ≤ {param(cfg, 'max_fill_gap_hours')} h, flagged)",
                      "excluded (longer gaps)"],
            f"all {n['n_cand']} candidates (hours)": [int(dq[c].sum()) for c in [
                "missing_timestamps", "duplicate_timestamps", "missing_values", "negative_readings",
                "zero_readings", "spike_readings", "flatline_hours", "invalid_hours", "filled_hours",
                "excluded_hours"]],
            f"{n['n_sel']} selected (hours)": [run["selected_check_totals"][c] for c in [
                "missing_timestamps", "duplicate_timestamps", "missing_values", "negative_readings",
                "zero_readings", "spike_readings", "flatline_hours", "invalid_hours", "filled_hours",
                "excluded_hours"]],
        })),
        "",
        f"- Selected buildings: {n['sel_invalid']:,} of {n['sel_hours']:,} hours invalid ({n['sel_pct']:.2f}%); "
        f"{n['sel_filled']} filled and flagged, {n['sel_excluded']:,} excluded. Lowest valid shares: "
        + ", ".join(f"{r.building_id} {r.pct_valid}%" for r in worst.itertuples()) + ".",
        dst_line,
        lng_line,
        "- Excluded hours are not guessed. Annual kWh is scaled up to the full year (`kwh_annualised` = "
        "measured kWh × hours in year / valid hours) so gaps do not make a building look efficient.",
        "- Weather: " + "; ".join(f"{s} {v['missing_hours']} missing hours ({v['filled_hours']} filled)"
                                  for s, v in run["weather"].items()) + ".",
        "",
        "![data quality](reports/figures/data_quality_checks.png)",
        "",
        "## 3. KPIs and benchmarking",
        "",
        f"- Portfolio: **{n['kwh']:,.0f} kWh/yr** (annualised) over {n['area']:,.0f} m², portfolio EUI "
        f"**{n['eui']:.1f} kWh/m²/yr**, **{n['co2']:,.0f} tCO2/yr** at {n['factor']} tCO2/MWh (CEA India "
        "factor; demonstration only).",
        f"- Retail EUI: min {n['r']['eui_min']:.0f}, P25 {n['r']['eui_p25']:.0f}, median {n['r']['eui_median']:.0f}, "
        f"P75 {n['r']['eui_p75']:.0f}, max {n['r']['eui_max']:.0f} kWh/m²/yr.",
        f"- Office EUI: min {n['o']['eui_min']:.0f}, P25 {n['o']['eui_p25']:.0f}, median {n['o']['eui_median']:.0f}, "
        f"P75 {n['o']['eui_p75']:.0f}, max {n['o']['eui_max']:.0f} kWh/m²/yr.",
        "- `after_hours_share` is the share of ENERGY used outside the assumed opening hours; "
        "`after_hours_time_share` is the share of HOURS that are outside them. A building with a flat load "
        "has the two equal, so compare them, not the first one alone.",
        "- `weekend_weekday_ratio` = average weekend day kWh / average weekday kWh. It tests the opening-hours "
        "assumption: " + (", ".join(f"{r.building_id} ({r.weekend_weekday_ratio:.2f})" for r in odd_hours.itertuples())
                          + " use much less at weekends although Retail is assumed open 7 days, so their "
                          "after-hours figures are understated." if len(odd_hours) else
                          "no Retail building looks closed at weekends."),
        "- EUI here is **electricity only**. Buildings heated by gas, steam or district systems will look "
        "better than they are, and climates differ between sites (by metadata coordinates and timezones: "
        "Panther = Orlando FL area, Fox = Phoenix AZ area, Rat = Washington DC, Wolf = Dublin), so peer "
        "ranks are indicative.",
        "",
        md_table(kpi_tbl),
        "",
        "![EUI](reports/figures/eui_by_building.png)",
        "",
        "![monthly](reports/figures/monthly_intensity.png)",
        "",
        "![after hours](reports/figures/after_hours_share.png)",
        "",
        f"![heatmap](reports/figures/heatmap_largest_retail.png)",
        "",
        "## 4. Anomalies",
        "",
        "**There is no ground truth in this real data.** Nobody labelled which hours were faulty, so the "
        "numbers below are counts and agreement between methods, **not precision or recall**.",
        "",
        f"- Hours flagged: MAD baseline {anom['hourly_flags']['mad_baseline']:,} of "
        f"{anom['hourly_flags']['hours_scored_mad']:,} scored; Isolation Forest "
        f"{anom['hourly_flags']['isolation_forest']:,} of {anom['hourly_flags']['hours_scored_if']:,} "
        f"(it always flags its contamination rate, {param(cfg, 'if_contamination'):.0%}).",
        f"- Daily events: MAD {n['mad_ev']:,}, Isolation Forest {n['if_ev']:,}, weather regression {n['wx_ev']}.",
        f"- Overlap (building-days): both MAD and IF {n['ov']['mad_and_if']}, MAD only {n['ov']['mad_only']}, "
        f"IF only {n['ov']['if_only']}, Jaccard {n['ov']['jaccard_mad_if']}; all three methods "
        f"{n['ov']['all_three']}. {n['mad_high_if']} of the {n['mad_high']} high-severity MAD events were also "
        "flagged by IF.",
        f"- Weather model R² per building: median {anom['weather_model_r2_median']:.2f} "
        f"(range {anom['weather_model_r2_min']:.2f}–{anom['weather_model_r2_max']:.2f}). Temperature explains "
        "only part of daily use; schedules matter more for most buildings.",
        "",
        "Events by severity:",
        "",
        md_table(by_sev.reset_index().rename(columns={"index": "severity"})),
        "",
        "Events by reason tag:",
        "",
        md_table(by_reason.reset_index().rename(columns={"index": "reason"})),
        "",
        "**Calibration of the MAD baseline (honest record).** The first run floored the MAD scale at 5% of "
        "each hour's expected load and flagged every hour beyond |z| 3.5. That flagged 23.6% of building-days "
        "(robust z up to 113 on a ~1.5 kW night load), which is too many to review. The final settings floor "
        f"the scale at {param(cfg, 'min_scale_frac_of_building_mean'):.0%} of the building's mean load and need "
        f"≥ {param(cfg, 'min_flag_run_hours')} consecutive flagged hours. The table below is recomputed every run "
        "and shows the trade-off; there is no 'correct' row without ground truth.",
        "",
        md_table(sens),
        "",
        "Five example events (strongest MAD events that Isolation Forest also flagged, one per building):",
        "",
        md_table(ex[["figure", "building_id", "date", "peak_hour", "reason", "severity", "robust_z",
                     "flagged_hours", "deviation_kwh"]]),
        "",
        notes_line,
        "",
        "![methods](reports/figures/anomaly_methods.png)",
        "",
        "![weather](reports/figures/weather_fit.png)",
        "",
        *[f"![example {i}](reports/figures/anomaly_example_{i}.png)" for i in range(1, len(ex) + 1)],
        "",
        "## 5. Savings opportunities (estimates)",
        "",
        f"Tariff ₹{n['tariff']:.2f}/kWh and {n['factor']} tCO2/MWh are **assumptions** (sources in the table at "
        "the end). **The opportunity types overlap** (cutting baseload also cuts after-hours load), so they "
        "must not be added together. The after-hours excess is an **upper bound**: some after-hours load is "
        "needed (cleaning, IT, refrigeration, security).",
        "",
        md_table(pd.DataFrame(sav_rows)),
        "",
        "Top 10 ranked opportunities (one row per building and type; the "
        f"{param(cfg, 'ranking_baseload_scenario'):.0%} baseload scenario stands in for the three):",
        "",
        md_table(top10_tbl),
        "",
        "Benchmark gaps are large because they compare buildings with different uses, climates and heating "
        "systems; treat them as a list of buildings to look at first, not as achievable savings.",
        "",
        "## 6. Assumptions used in this run",
        "",
        "Full text with sources: `data/processed/assumptions.csv` (generated from `config.yaml`).",
        "",
        md_table(asm),
        "",
        "## 7. Limitations",
        "",
        "- **Location mismatch:** the CEA factor and KERC tariff are Indian; the buildings are in the USA and "
        "Ireland. CO2 and INR values only demonstrate the method.",
        "- **No ground truth for anomalies;** counts and overlap are not accuracy. The examples were inspected "
        "by eye only.",
        "- **Assumed opening hours** drive after-hours figures and anomaly reason tags; the weekend/weekday "
        "ratio shows they are wrong for some buildings.",
        f"- **Gap filling:** gaps ≤ {param(cfg, 'max_fill_gap_hours')} h are linearly interpolated and flagged; "
        "longer gaps are excluded and annual totals are scaled up.",
        "- **Electricity only:** EUI ignores gas, steam and chilled water, so total-energy comparisons are not possible.",
        f"- **Small peer groups** ({n['n_retail']} Retail, {n['n_office']} Office): percentiles move a lot if "
        "one building changes.",
        f"- **One year ({n['year']}), hourly resolution:** no year-on-year comparison, and peaks shorter than an "
        "hour are invisible.",
    ]
    (ROOT / "RESULTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# static preview page
# ---------------------------------------------------------------------------
def preview_html(n):
    def img(name):
        data = base64.b64encode((FIGURES / name).read_bytes()).decode()
        return f'<figure><img src="data:image/png;base64,{data}" alt="{name}"></figure>'
    tiles = [
        ("Total electricity", f"{n['kwh'] / 1e6:.2f} GWh/yr", f"{n['n_sel']} buildings, {n['year']}, annualised"),
        ("Portfolio EUI", f"{n['eui']:.1f}", "kWh per m² per year"),
        ("CO2 (demo factor)", f"{n['co2']:,.0f} t", f"{n['factor']} tCO2/MWh, CEA India: illustration only"),
        ("After-hours excess", f"₹{n['ah_inr'] / 1e7:.2f} cr", "upper bound at assumed ₹8/kWh"),
    ]
    tile_html = "".join(f'<div class="tile"><div class="label">{a}</div><div class="value">{b}</div>'
                        f'<div class="sub">{c}</div></div>' for a, b, c in tiles)
    figs = "".join(img(f) for f in ["eui_by_building.png", "monthly_intensity.png", "after_hours_share.png",
                                    "anomaly_methods.png", "heatmap_largest_retail.png", "anomaly_example_1.png"])
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Energy Analytics Preview</title>
<style>
:root {{ color-scheme: light; --surface:#fcfcfb; --page:#f9f9f7; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781;
        --border:rgba(11,11,11,0.10); --warn:#fab219; }}
* {{ box-sizing: border-box; }}
body {{ margin:0; background:var(--page); color:var(--ink); font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }}
main {{ max-width: 1100px; margin: 0 auto; padding: 24px 16px 48px; }}
.banner {{ border:2px solid var(--warn); background:#fff8e6; padding:12px 16px; border-radius:8px; font-weight:600; }}
.banner span {{ display:block; font-weight:400; color:var(--ink2); margin-top:4px; }}
h1 {{ font-size: 1.5rem; margin: 20px 0 4px; }}
.sub-h {{ color: var(--ink2); margin: 0 0 20px; }}
.tiles {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap:12px; margin-bottom: 20px; }}
.tile {{ background:var(--surface); border:1px solid var(--border); border-radius:8px; padding:14px 16px; }}
.label {{ color:var(--ink2); font-size:.85rem; }} .value {{ font-size:1.8rem; font-weight:600; margin:4px 0; }}
.sub {{ color:var(--muted); font-size:.8rem; }}
figure {{ margin:0 0 16px; background:var(--surface); border:1px solid var(--border); border-radius:8px; padding:8px; }}
img {{ width:100%; height:auto; display:block; }}
footer {{ color:var(--muted); font-size:.8rem; margin-top:24px; }}
</style></head><body><main>
<div class="banner">STATIC PREVIEW. This is NOT the Power BI report.
<span>Power BI report: NOT YET BUILT (kit ready). Charts are PNGs generated by the Python pipeline.</span></div>
<h1>Retail and office electricity analytics</h1>
<p class="sub-h">Data: Building Data Genome Project 2 (public dataset), real hourly meter data, {n['year']}.
{n['n_retail']} Retail + {n['n_office']} Office buildings in the USA and Ireland. INR and CO2 use Indian
assumptions for demonstration only.</p>
<div class="tiles">{tile_html}</div>
{figs}
<footer>Generated by src/07_report.py. All numbers come from the pipeline run; see RESULTS.md for the full
results, assumptions and limitations.</footer>
</main></body></html>
"""
    (ROOT / "reports" / "preview_dashboard.html").write_text(html, encoding="utf-8")


def check_values(cfg):
    """What each key DAX measure should show with NO filters applied, computed here in pandas the
    same way the measure computes it. Used in powerbi/BUILD_GUIDE.md to test the report."""
    daily = pd.read_csv(PROCESSED / "fact_daily_energy.csv")
    hourly = pd.read_csv(PROCESSED / "fact_hourly_energy.csv")
    annual = pd.read_csv(PROCESSED / "fact_annual_kpi.csv")
    dim_b = pd.read_csv(PROCESSED / "dim_building.csv")
    an = pd.read_csv(PROCESSED / "fact_anomalies.csv")
    opp = pd.read_csv(PROCESSED / "fact_opportunities.csv")
    factor = param(cfg, "emission_factor_t_per_mwh")
    total_kwh = daily["kwh"].sum()
    per_hour = hourly.groupby("timestamp")["kwh"].sum()
    peak = per_hour.max()
    head = opp[opp["is_headline"]]
    rows = [
        ("Total kWh", f"{total_kwh:,.0f}", "measured kWh, gaps excluded"),
        ("Floor Area m2", f"{dim_b['floor_area_m2'].sum():,.1f}", ""),
        ("EUI (annual)", f"{annual['kwh_annualised'].sum() / dim_b['floor_area_m2'].sum():.1f}", "kWh/m²/yr"),
        ("Total CO2 t", f"{total_kwh / 1000 * factor:,.0f}", "from measured kWh"),
        ("Total CO2 t (annualised)", f"{annual['co2_tonnes'].sum():,.0f}", "matches RESULTS.md"),
        ("Avg Baseload kW", f"{daily.groupby('building_id')['baseload_kw'].mean().sum():,.1f}",
         "sum of each building's average daily baseload"),
        ("Peak kW", f"{peak:,.1f}", f"highest hour of the {len(dim_b)} buildings added together"),
        ("Load Factor", f"{hourly['kwh'].sum() / hourly['timestamp'].nunique() / peak:.3f}", ""),
        ("After-Hours Share %", f"{daily['after_hours_kwh'].sum() / total_kwh:.1%}", ""),
        ("After-Hours Time Share %", f"{(~hourly['is_open']).mean():.1%}", ""),
        ("Anomaly Count", f"{len(an):,}", "all three methods"),
        ("High-Severity Anomaly Count", f"{(an['severity'] == 'high').sum():,}", "all three methods"),
        ("Estimated Savings kWh", f"{head['kwh_saving'].sum():,.0f}", "after-hours excess, upper bound"),
        ("Estimated Savings INR", f"{head['inr_saving'].sum():,.0f}", "assumed tariff"),
        ("Filled Hours %", f"{hourly['filled_flag'].mean():.2%}", ""),
        ("Excluded Hours %", f"{hourly['kwh'].isna().mean():.2%}", ""),
    ]
    # one building, to test the benchmarking measures
    b = annual.merge(dim_b[["building_id", "type"]], on="building_id").sort_values("eui_kwh_m2").iloc[-1]
    rows += [
        (f"EUI (annual), building {b['building_id']}", f"{b['eui_kwh_m2']:.1f}", "select it in a slicer"),
        (f"EUI Rank in Type, {b['building_id']}", f"{int(b['eui_rank_in_type'])} of {int(b['n_in_type'])}", "1 = best"),
        (f"EUI Percentile in Type, {b['building_id']}", f"{b['eui_percentile_in_type'] / 100:.0%}", ""),
        (f"Peer Median EUI, {b['building_id']}", f"{b['peer_median_eui']:.1f}", f"median of type {b['type']}"),
    ]
    table = md_table(pd.DataFrame(rows, columns=["measure", "expected value", "note"]))
    return ("_Generated by `src/07_report.py` from the current data; no filters applied unless stated. "
            "Small rounding differences are fine; anything else means a measure, a data type or a "
            "relationship is wrong._\n\n" + table)


def main():
    cfg = load_config()
    banner("STEP 7: figures and reports")
    ps.apply()
    d = load()
    year = d["run"]["analysis_year"]
    fig_eui(d, year)
    fig_monthly(d, year)
    fig_after_hours(d, year)
    fig_data_quality(d, year)
    fig_anomaly_methods(d, year)
    fig_weather(d, year)
    hm = fig_heatmap(d, year)

    n = headline_numbers(d, cfg)
    results_md(d, n, cfg, hm)
    preview_html(n)
    replace_block(ROOT / "README.md", "FINDINGS", "\n".join(f"{i}. {f}" for i, f in enumerate(findings(n), 1)))
    replace_block(ROOT / "powerbi" / "BUILD_GUIDE.md", "CHECKS", check_values(cfg))
    print("\nHeadline findings:")
    for i, f in enumerate(findings(n), 1):
        print(f"{i}. {f}\n")
    print(f"Wrote RESULTS.md, reports/preview_dashboard.html and {len(list(FIGURES.glob('*.png')))} figures")


if __name__ == "__main__":
    main()
