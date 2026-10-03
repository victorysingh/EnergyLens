"""Shared helpers used by every pipeline script.

Keeping paths, config loading and the small pure functions (EUI, CO2, gap
filling, robust z-score) in one module means:
  * every script reads the same config.yaml, and
  * the tests can import and check the maths directly.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

# Windows consoles default to cp1252, which cannot print "₹", "²" or "−".
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# Paths (all relative to the project root, so the project can be moved)
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.yaml"
RAW = ROOT / "data" / "raw"
INTERIM = ROOT / "data" / "interim"
PROCESSED = ROOT / "data" / "processed"
FIGURES = ROOT / "reports" / "figures"

for _d in (RAW, INTERIM, PROCESSED, FIGURES):
    _d.mkdir(parents=True, exist_ok=True)

SQFT_TO_M2 = 0.09290304  # exact: 1 ft = 0.3048 m, so 1 ft^2 = 0.3048^2 m^2


def load_config(path=CONFIG_PATH):
    """Read config.yaml into a plain dict."""
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def param(cfg, key):
    """Return the value of one entry in the `assumptions:` block of config.yaml.

    Every script reads settings through this function, which lets the tests
    check that every key used in src/ is also exported to assumptions.csv.
    """
    return cfg["assumptions"][key]["value"]


DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def operating_hours_for(cfg, building_id, building_type):
    """(open_hour, close_hour, set_of_weekday_numbers) for one building.

    Uses the per-building override if there is one, else the type default.
    Weekday numbers follow pandas: Mon=0 ... Sun=6.
    """
    rule = param(cfg, "operating_hours_overrides").get(building_id)
    if rule is None:
        rule = param(cfg, "operating_hours")[building_type]
    days = {DAY_NAMES.index(d) for d in rule["days"]}
    return rule["open"], rule["close"], days


def is_open(timestamps, open_hour, close_hour, open_days):
    """True for timestamps inside the assumed opening hours [open, close)."""
    ts = pd.DatetimeIndex(timestamps)
    return (ts.hour >= open_hour) & (ts.hour < close_hour) & ts.dayofweek.isin(list(open_days))


def banner(title):
    """Print a visible section header in the console output."""
    print("\n" + "=" * 70 + f"\n{title}\n" + "=" * 70)


# ---------------------------------------------------------------------------
# Small pure functions (unit-tested in tests/test_pipeline.py)
# ---------------------------------------------------------------------------
def eui_kwh_per_m2(annual_kwh, floor_area_m2):
    """Energy Use Intensity = annual kWh / floor area in m^2  (kWh/m^2/yr)."""
    return annual_kwh / floor_area_m2


def co2_tonnes(kwh, factor_t_per_mwh):
    """Scope 2 (location-based) emissions in tonnes CO2.

    The factor is in tCO2/MWh. 1 MWh = 1000 kWh, so tonnes = kWh / 1000 * factor.
    """
    return kwh / 1000.0 * factor_t_per_mwh


def run_lengths(mask):
    """For a boolean Series, give every True element the length of the
    consecutive True run it belongs to (0 for False elements).

    Example: [F, T, T, F, T] -> [0, 2, 2, 0, 1]
    """
    mask = mask.astype(bool)
    run_id = (mask != mask.shift()).cumsum()
    lengths = mask.groupby(run_id).transform("sum")
    return lengths.where(mask, 0).astype(int)


def fill_short_gaps(series, max_gap_hours):
    """Linearly interpolate gaps of at most `max_gap_hours` consecutive NaNs.

    Longer gaps are left as NaN (excluded later). Returns (filled, was_filled)
    where `was_filled` is True exactly for the values that were interpolated,
    so nothing is changed silently.
    """
    gap_len = run_lengths(series.isna())
    short_gap = (gap_len > 0) & (gap_len <= max_gap_hours)
    interpolated = series.interpolate(method="linear", limit_area="inside")
    filled = series.where(~short_gap, interpolated)
    was_filled = short_gap & filled.notna()
    return filled, was_filled


def robust_z(values, median, mad):
    """MAD-based z-score. 1.4826 * MAD estimates the standard deviation for
    normally distributed data, so the result reads like an ordinary z-score
    but is not dragged around by the outliers we are trying to find."""
    scale = 1.4826 * np.asarray(mad, dtype=float)
    scale = np.where(scale > 0, scale, np.nan)
    return (np.asarray(values, dtype=float) - np.asarray(median, dtype=float)) / scale


def severity_bucket(abs_score, med, high):
    """Map the score of an already-flagged item to 'low' / 'med' / 'high'.

    Anything below `med` is 'low' (it was flagged, so it is at least low),
    `med` <= score < `high` is 'med', and score >= `high` is 'high'.
    """
    return pd.cut(
        pd.Series(abs_score).reset_index(drop=True),
        bins=[-np.inf, med, high, np.inf],
        labels=["low", "med", "high"],
        right=False,
    ).astype(str)
