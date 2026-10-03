"""Step 4: anomaly detection, two methods plus a weather-normalised view.

Method 1  MAD baseline (statistical, explainable)
          Expected load for each hour = rolling median of nearby hours with the
          same hour-of-day and day-type (weekday/weekend). Distance from it is
          measured in robust z-scores (median absolute deviation, MAD).
Method 2  Isolation Forest (machine learning second opinion)
          Learns what "normal" combinations of hour, weekday, load, lagged load
          and temperature look like for each building and isolates rare ones.
View 3    Weather-normalised daily model
          Daily kWh = a + b*HDD + c*CDD + d*weekend. Days far from the model
          are flagged, so a hot day is not mistaken for waste.

There is NO ground truth in real meter data: nobody labelled which hours were
truly faulty. So this step reports counts and overlap, not precision/recall.
"""

import json

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

import plotstyle as ps
from common import (FIGURES, INTERIM, ROOT, banner, load_config, param, robust_z, run_lengths,
                    severity_bucket)


# ---------------------------------------------------------------------------
# Reason tags in plain language
# ---------------------------------------------------------------------------
def reason_tag(kwh, expected, is_open, dropout_frac):
    """Why an hour looks odd, judged by direction and opening hours."""
    high = kwh > expected
    return np.select(
        [high & ~is_open, high & is_open, ~high & (kwh < dropout_frac * expected)],
        ["after_hours_load", "daytime_spike", "meter_dropout_suspect"],
        default="unexpected_low",
    )


# ---------------------------------------------------------------------------
# Method 1: MAD-based statistical baseline
# ---------------------------------------------------------------------------
def nan_mad(window):
    return np.nanmedian(np.abs(window - np.nanmedian(window)))


def mad_baseline(h, cfg):
    win, minp = param(cfg, "baseline_window_obs"), param(cfg, "baseline_min_obs")
    h = h.sort_values(["building_id", "timestamp"]).copy()
    h["day_type"] = np.where(h["timestamp"].dt.dayofweek >= 5, "weekend", "weekday")
    h["hour"] = h["timestamp"].dt.hour
    groups = h.groupby(["building_id", "hour", "day_type"])["kwh"]
    h["expected_kwh"] = groups.transform(lambda s: s.rolling(win, center=True, min_periods=minp).median())
    h["mad"] = groups.transform(lambda s: s.rolling(win, center=True, min_periods=minp).apply(nan_mad, raw=True))

    h["building_mean_kwh"] = h.groupby("building_id")["kwh"].transform("mean")
    h["reason"] = reason_tag(h["kwh"], h["expected_kwh"], h["is_open"], param(cfg, "dropout_frac_of_expected"))
    h["z"], h["scale"], h["mad_flag"] = score_mad(h, param(cfg, "min_scale_frac_of_building_mean"),
                                                  param(cfg, "min_flag_run_hours"), cfg)
    return h


def score_mad(h, floor_frac, min_run, cfg):
    """Robust z-score and flag for every hour, for one choice of floor/persistence.

    scale = max(1.4826 * MAD, floor_frac * building mean load). The floor stops a
    building with a very steady (or very small) load turning tiny wiggles into
    huge z-scores. An hour is flagged only if |z| >= threshold for at least
    `min_run` consecutive hours (persistence rule against one-hour blips).
    """
    floor = floor_frac * h["building_mean_kwh"]
    # robust_z divides by 1.4826*MAD; flooring the MAD at floor/1.4826 floors the scale at `floor`
    mad = np.maximum(h["mad"], floor / 1.4826)
    z = pd.Series(robust_z(h["kwh"], h["expected_kwh"], mad), index=h.index)
    z[h["filled_flag"]] = np.nan          # never judge an interpolated value
    over = z.abs() >= param(cfg, "mad_z_threshold")
    run = over.groupby(h["building_id"]).transform(run_lengths)
    return z, 1.4826 * mad, over & (run >= min_run)


def mad_sensitivity(h, cfg):
    """Re-score with other floor/persistence settings to show the trade-off."""
    n_days = h.groupby(["building_id", "date"]).ngroups
    rows = []
    for frac in (0.05, 0.10, 0.15):
        for min_run in (1, 2, 3):
            _, _, flag = score_mad(h, frac, min_run, cfg)
            days = h[flag].groupby(["building_id", "date"]).ngroups
            rows.append({"min_scale_frac_of_building_mean": frac, "min_flag_run_hours": min_run,
                         "pct_hours_flagged": round(100 * flag.mean(), 2), "building_days_flagged": days,
                         "pct_building_days": round(100 * days / n_days, 1),
                         "chosen": frac == param(cfg, "min_scale_frac_of_building_mean")
                         and min_run == param(cfg, "min_flag_run_hours")})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Method 2: Isolation Forest
# ---------------------------------------------------------------------------
IF_FEATURES = ["hour", "dow", "is_open", "kwh", "lag1", "lag24", "lag168", "roll24_mean", "temp_c"]


def isolation_forest(h, cfg):
    seed = cfg["project"]["random_seed"]
    parts = []
    for b, g in h.groupby("building_id"):
        g = g.sort_values("timestamp").copy()
        g["dow"] = g["timestamp"].dt.dayofweek
        g["lag1"] = g["kwh"].shift(1)
        g["lag24"] = g["kwh"].shift(24)
        g["lag168"] = g["kwh"].shift(168)
        g["roll24_mean"] = g["kwh"].shift(1).rolling(24, min_periods=18).mean()
        usable = g[IF_FEATURES].notna().all(axis=1) & ~g["filled_flag"]
        X = g.loc[usable, IF_FEATURES].astype(float)
        model = IsolationForest(n_estimators=param(cfg, "if_n_estimators"),
                                contamination=param(cfg, "if_contamination"), random_state=seed)
        g["if_flag"] = False
        g.loc[usable, "if_flag"] = model.fit_predict(X) == -1
        g["if_score"] = np.nan
        g.loc[usable, "if_score"] = -model.score_samples(X)     # higher = more isolated = more anomalous
        g["if_score_pct"] = g["if_score"].rank(pct=True) * 100
        parts.append(g)
    return pd.concat(parts, ignore_index=True)


# ---------------------------------------------------------------------------
# Hourly flags -> daily events
# ---------------------------------------------------------------------------
def daily_events(h, flag_col, score_col, method, severity_fn):
    """One event per building-day that has at least one flagged hour."""
    f = h[h[flag_col]].copy()
    f["abs_score"] = f[score_col].abs()
    rows = []
    for (b, d), g in f.groupby(["building_id", "date"]):
        top = g.loc[g["abs_score"].idxmax()]
        counts = g.groupby("reason")["abs_score"].agg(["size", "max"]).sort_values(["size", "max"], ascending=False)
        rows.append({
            "building_id": b, "date": d, "timestamp": top["timestamp"], "method": method,
            "score": round(float(top[score_col]), 3), "severity_basis": float(top["severity_basis"]),
            "reason": counts.index[0], "flagged_hours": len(g),
            "actual_kwh": g["kwh"].sum(), "expected_kwh": g["expected_kwh"].sum(),
        })
    ev = pd.DataFrame(rows)
    ev["severity"] = severity_fn(ev["severity_basis"])
    ev["deviation_kwh"] = ev["actual_kwh"] - ev["expected_kwh"]
    return ev.drop(columns="severity_basis")


# ---------------------------------------------------------------------------
# View 3: weather-normalised daily regression
# ---------------------------------------------------------------------------
def weather_view(daily, cfg):
    events, models = [], []
    _, med, hi = param(cfg, "severity_cutoffs_z")   # first value = the flag threshold
    for b, d in daily[daily["complete_day"]].groupby("building_id"):
        d = d.copy()
        d["weekend"] = (d["date"].dt.dayofweek >= 5).astype(float)
        X = np.column_stack([np.ones(len(d)), d["hdd"], d["cdd"], d["weekend"]])
        y = d["kwh"].to_numpy()
        coef, *_ = np.linalg.lstsq(X, y, rcond=None)
        d["expected_kwh"] = X @ coef
        resid = y - d["expected_kwh"]
        r2 = 1 - (resid ** 2).sum() / ((y - y.mean()) ** 2).sum()
        mad = np.median(np.abs(resid - np.median(resid)))
        d["z"] = robust_z(resid, np.median(resid), mad)
        models.append({"building_id": b, "n_days": len(d), "intercept_kwh": coef[0], "kwh_per_hdd": coef[1],
                       "kwh_per_cdd": coef[2], "weekend_kwh": coef[3], "r2": r2})
        flag = d[d["z"].abs() >= param(cfg, "weather_resid_z_threshold")]
        for _, r in flag.iterrows():
            events.append({
                "building_id": b, "date": r["date"], "timestamp": pd.NaT, "method": "weather_regression",
                "score": round(float(r["z"]), 3),
                "severity": severity_bucket([abs(r["z"])], med, hi).iloc[0],
                "reason": "weather_adjusted_high" if r["z"] > 0 else "weather_adjusted_low",
                "flagged_hours": 24, "actual_kwh": r["kwh"], "expected_kwh": r["expected_kwh"],
                "deviation_kwh": r["kwh"] - r["expected_kwh"],
            })
    return pd.DataFrame(events), pd.DataFrame(models)


# ---------------------------------------------------------------------------
# Example plots
# ---------------------------------------------------------------------------
def plot_example(h, event, cfg, year, path):
    import matplotlib.pyplot as plt
    b, day = event["building_id"], event["date"]
    w = h[(h["building_id"] == b) & h["date"].between(day - pd.Timedelta(days=3), day + pd.Timedelta(days=3))]
    thr = param(cfg, "mad_z_threshold")
    scale = w["scale"]

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.fill_between(w["timestamp"], w["expected_kwh"] - thr * scale, w["expected_kwh"] + thr * scale,
                    color=ps.SERIES[0], alpha=0.10, linewidth=0, label=f"normal band (expected ± {thr} robust z)")
    ax.plot(w["timestamp"], w["expected_kwh"], color=ps.MUTED, linewidth=1.5, label="expected (rolling median)")
    ax.plot(w["timestamp"], w["kwh"], color=ps.SERIES[0], label="actual kWh")
    m = w[w["mad_flag"]]
    ax.scatter(m["timestamp"], m["kwh"], s=60, color=ps.CRITICAL, edgecolor=ps.SURFACE, linewidth=2,
               zorder=5, label="flagged: MAD baseline")
    i = w[w["if_flag"]]
    ax.scatter(i["timestamp"], i["kwh"], s=90, marker="D", facecolor="none", edgecolor=ps.INK,
               linewidth=1.2, zorder=6, label="flagged: Isolation Forest")
    ax.set_title(f"{b}: {day:%a %d %b %Y}  ·  {event['reason']}  ·  severity {event['severity']}")
    ax.set_ylabel("kWh per hour (= average kW)")
    ax.set_ylim(bottom=0)
    ax.legend(loc="upper left", ncol=3, fontsize=8)
    ps.caption(fig, year, "Opening hours are an assumption.")
    ps.save(fig, path)


def main():
    cfg = load_config()
    banner("STEP 4: anomalies")
    ps.apply()
    year = json.loads((INTERIM / "run_info.json").read_text())["analysis_year"]
    h = pd.read_parquet(INTERIM / "hourly_kpi.parquet")
    daily = pd.read_parquet(INTERIM / "daily.parquet")

    _, med, hi = param(cfg, "severity_cutoffs_z")          # first value = the flag threshold
    _, p_med, p_hi = param(cfg, "if_severity_cutoffs_pct")

    h = mad_baseline(h, cfg)
    h = isolation_forest(h, cfg)
    h["severity_basis"] = h["z"].abs()
    mad_ev = daily_events(h, "mad_flag", "z", "mad_baseline", lambda s: severity_bucket(s, med, hi))
    h["severity_basis"] = h["if_score_pct"]
    if_ev = daily_events(h, "if_flag", "if_score", "isolation_forest",
                         lambda s: severity_bucket(s, p_med, p_hi))
    wx_ev, wx_models = weather_view(daily, cfg)

    events = pd.concat([mad_ev, if_ev, wx_ev], ignore_index=True)
    events = events.sort_values(["method", "building_id", "date"]).reset_index(drop=True)
    events.insert(0, "anomaly_id", np.arange(1, len(events) + 1))
    events.to_parquet(INTERIM / "anomalies.parquet", index=False)
    wx_models.to_csv(INTERIM / "weather_models.csv", index=False)
    sensitivity = mad_sensitivity(h, cfg)
    sensitivity.to_csv(ROOT / "reports" / "mad_sensitivity.csv", index=False)
    print("MAD baseline sensitivity (share of building-days flagged):")
    print(sensitivity.to_string(index=False))
    h.drop(columns=["severity_basis"]).to_parquet(INTERIM / "hourly_scored.parquet", index=False)

    # ---- evaluation: counts and overlap (no ground truth exists) ----------
    def keys(ev):
        return set(zip(ev["building_id"], ev["date"]))
    k_mad, k_if, k_wx = keys(mad_ev), keys(if_ev), keys(wx_ev)
    both = k_mad & k_if
    evaluation = {
        "hourly_flags": {"mad_baseline": int(h["mad_flag"].sum()), "isolation_forest": int(h["if_flag"].sum()),
                         "hours_scored_mad": int(h["z"].notna().sum()),
                         "hours_scored_if": int(h["if_score"].notna().sum())},
        "events_per_method": events["method"].value_counts().to_dict(),
        "events_by_severity": {m: g["severity"].value_counts().to_dict() for m, g in events.groupby("method")},
        "events_by_reason": {m: g["reason"].value_counts().to_dict() for m, g in events.groupby("method")},
        "buildings_with_events": {m: int(g["building_id"].nunique()) for m, g in events.groupby("method")},
        "overlap_building_days": {
            "mad_and_if": len(both), "mad_only": len(k_mad - k_if), "if_only": len(k_if - k_mad),
            "jaccard_mad_if": round(len(both) / len(k_mad | k_if), 3) if (k_mad | k_if) else None,
            "mad_and_weather": len(k_mad & k_wx), "if_and_weather": len(k_if & k_wx),
            "all_three": len(both & k_wx),
        },
        "high_severity_mad_events": int(((mad_ev["severity"] == "high")).sum()),
        "high_severity_mad_and_if": int(mad_ev[mad_ev["severity"].eq("high")]
                                        .apply(lambda r: (r["building_id"], r["date"]) in k_if, axis=1).sum()),
        "weather_model_r2_median": float(wx_models["r2"].median()),
        "weather_model_r2_min": float(wx_models["r2"].min()),
        "weather_model_r2_max": float(wx_models["r2"].max()),
    }

    # ---- 5 example plots: strongest MAD events also flagged by IF, 5 different buildings
    cand = mad_ev[mad_ev.apply(lambda r: (r["building_id"], r["date"]) in k_if, axis=1)]
    cand = cand.reindex(cand["score"].abs().sort_values(ascending=False).index)
    picks = cand.drop_duplicates("building_id").head(5)
    if len(picks) < 5:  # fall back to strongest MAD-only events
        rest = mad_ev[~mad_ev["building_id"].isin(picks["building_id"])]
        rest = rest.reindex(rest["score"].abs().sort_values(ascending=False).index).drop_duplicates("building_id")
        picks = pd.concat([picks, rest.head(5 - len(picks))])
    examples = []
    for n, (_, ev) in enumerate(picks.iterrows(), start=1):
        name = f"anomaly_example_{n}.png"
        plot_example(h, ev, cfg, year, FIGURES / name)
        examples.append({"figure": name, "building_id": ev["building_id"], "date": f"{ev['date']:%Y-%m-%d}",
                         "peak_hour": f"{ev['timestamp']:%H:%M}", "reason": ev["reason"],
                         "severity": ev["severity"], "robust_z": ev["score"],
                         "flagged_hours": int(ev["flagged_hours"]),
                         "deviation_kwh": round(float(ev["deviation_kwh"]), 1)})
    evaluation["examples"] = examples
    (INTERIM / "anomaly_eval.json").write_text(json.dumps(evaluation, indent=2, default=str), encoding="utf-8")

    print(json.dumps({k: v for k, v in evaluation.items() if k != "examples"}, indent=2, default=str))
    print("\nExample plots:")
    for e in examples:
        print(" ", e)


if __name__ == "__main__":
    main()
