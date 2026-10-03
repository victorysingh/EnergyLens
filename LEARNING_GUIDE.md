# Learning guide

This guide is what makes the project yours. It assumes you are comfortable with Python and ML but have
**no energy background**. Read it with the code open. Examples use real numbers from this project's run
(2017 BDG2 data); `RESULTS.md` is the source of truth if a number changes after a re-run.

Contents: 1. Energy glossary · 2. File-by-file walkthrough · 3. Why these methods · 4. "Break it"
exercises · 5. Self-test (answers at the very bottom)

---

## 1. Energy glossary

**kW vs kWh.** A kilowatt (kW) is a *rate*: how fast energy is being used right now (power). A
kilowatt-hour (kWh) is an *amount*: energy used over time. A 2 kW heater running for 3 hours uses
2 × 3 = 6 kWh. Speed versus distance is the same idea. BDG2 gives one kWh reading per hour, so **each
hourly kWh number is also the average kW during that hour**. Example: `Rat_office_Jill`'s highest hour
was 1,977.7 kWh, so its peak demand was about 1,978 kW (at hourly resolution).

**Baseload.** The load that never switches off: servers, fridges, ventilation, emergency lighting,
equipment left on. Measured here as the 5th percentile of each day's 24 hourly readings, averaged over the
year. Example: `Panther_retail_Romeo` has a baseload of 392 kW against a peak of 611 kW, so at 3 a.m. it
still draws about two-thirds of its busiest-hour load. A high baseload is usually the cheapest thing to
investigate.

**Peak load (peak demand).** The highest kW in a period. It matters because commercial tariffs charge for
it separately (the KERC HT-2(b) tariff used here has a demand charge of ₹365 per kVA per month on top of the
energy charge), and because the grid connection must be sized for it.

**Load factor.** Average load ÷ peak load, between 0 and 1. Near 1 = flat, always-on (a data centre, or a
building that never really switches off). Low = peaky. Example: `Panther_retail_Romeo` 0.72 (flat);
`Fox_office_Molly` 0.19 (busy days, near-zero nights). A high load factor in an office or shop that is
supposed to close at night is a warning sign.

**EUI (Energy Use Intensity).** Annual energy ÷ floor area, in kWh/m²/yr. It lets you compare a big
building with a small one. Example: `Panther_retail_Romeo` used 3,833,752 kWh on 15,027.5 m², so
EUI = 255.1 kWh/m²/yr. Here it is **electricity-only** EUI; buildings heated with gas look better than
they are. Compare EUI only within the same building type and, ideally, the same climate.

**Degree days (HDD, CDD).** A simple measure of how much heating or cooling the weather demanded.
Pick a base temperature (here 18 °C, an assumption). Heating degree days for a day = max(0, 18 − daily mean
temperature); cooling degree days = max(0, daily mean − 18). A 30 °C day = 12 CDD; a 5 °C day = 13 HDD.
Adding them up over a month tells you how "hard" the month was for heating or cooling.

**Scope 2 emissions.** Greenhouse gas emissions from electricity you *buy* (they happen at the power
station, not on site). Scope 1 = burned on site (gas boiler); Scope 3 = everything else in the value
chain. **Location-based** Scope 2 multiplies kWh by the average emission factor of the local grid;
**market-based** uses the factor of what you contracted (green tariffs, renewable certificates). This
project computes location-based only.

**Emission factor.** Tonnes of CO2 per MWh of electricity. Here: 0.675 tCO2/MWh, the all-India weighted
average for FY 2025-26 from the CEA CO2 Baseline Database, Version 22.0 (the latest; it was checked on the
CEA website, not taken from memory). 1 MWh = 1,000 kWh, so 1,000,000 kWh × 0.675 / 1,000 = 675 t. **The
BDG2 buildings are in the USA and Ireland**, whose grids have different factors, so this is a demonstration
of the method only.

**Tariff.** The price of electricity. A commercial bill has an energy charge (₹/kWh), a demand charge
(₹/kVA of peak), taxes and surcharges. This project uses only the energy charge, ₹8.00/kWh (KERC HT-2(b)
commercial, effective April 2024), because savings in kWh are valued at the energy charge. It is labelled
"assumption" because these buildings are not billed in rupees.

**EMS vs BMS vs smart meter vs utility bill (as data sources).**

| source | what it records | typical resolution | strengths | limits |
|---|---|---|---|---|
| Utility bill | total kWh and maximum demand per billing period, cost | monthly (12 points a year) | the financial truth; what the company pays | far too coarse to see *when* or *why* energy is used; arrives late |
| Smart (revenue) meter | whole-building kWh per interval | 15, 30 or 60 min | accurate, continuous, comparable across sites | one number for the whole building: you see *that* it changed, not *what* changed |
| BMS (Building Management System) | control points: temperatures, setpoints, fan and valve status, equipment on/off, alarms | 1 to 15 min | explains *why* (e.g. chiller left on, setpoint changed) | built for control, not accounting; messy point names; often no energy data |
| EMS (Energy Management System) | software that collects meters and sub-meters (and sometimes BMS points) across many sites, with dashboards, alarms, targets and reports | follows its meters | portfolio view, M&V, reporting | only as good as the meters behind it |

**Where this project sits:** BDG2 is like the hourly main-meter data an EMS would hold for each building,
with no sub-meters and no BMS points. That is why the anomaly detectors can say "this day looks unusual"
but never "the chiller was left on". In a real retailer, the next step after an alert is to open the BMS
trends or ask the site team.

---

## 2. File-by-file walkthrough

**`config.yaml`**: every setting and assumption in one place, each with value, unit, label (ASSUMPTION or
METHOD), source or reason, and which script uses it. *Key idea:* no number that affects a result is hidden
in code; `06_export_powerbi.py` copies this block into `assumptions.csv`, and a test checks that every
setting the code reads is exported.

**`src/common.py`**: shared paths, `param()` to read config, and the small maths functions that tests
check directly: `eui_kwh_per_m2`, `co2_tonnes`, `run_lengths`, `fill_short_gaps`, `robust_z`,
`severity_bucket`, and the opening-hours helpers. *Key idea:* `run_lengths` labels each element of a
True/False series with the length of its run, which turns "gap of N hours" and "same value for N hours"
into one vectorised operation.

**`src/01_download.py`**: BDG2 stores its CSVs in Git LFS. The script reads the small LFS *pointer* file
(which states the SHA-256 and size), downloads the real file, and checks both. It logs URL, date and
checksum to `data/raw/SOURCES.md`. *Key idea:* verify what you downloaded; never trust a file because the
download "finished".

**`src/02_validate_clean.py`**: the data validation step, a core part of the target job.
1. Candidates: Retail and Office buildings with an electricity meter, at the 4 sites that have Retail
   buildings (so they share weather).
2. Year: the year where Retail data coverage is best (2017; several Panther meters read zero for months
   in 2016).
3. Checks in order (each reading counted once, by the first check that catches it): missing timestamp,
   missing value, negative, zero (a whole-building meter should never read exactly 0), spike (more than 3×
   the building's own 99th percentile), flatline (identical value for 24+ hours).
4. Invalid readings become gaps. Gaps of ≤ 3 hours are linearly interpolated and `filled_flag` marks
   every one; longer gaps stay empty.
5. Pass/fail: ≥ 95% valid hours, ≤ 2% filled, sqm and sqft agree, annualised EUI between 25 and
   1,000 kWh/m²/yr.
6. Selection: all passing Retail buildings + 4 random passing offices per site (fixed seed).

*Key ideas:* count everything you change; never fill silently; reject buildings for stated reasons. The
EUI sanity window caught two "Retail" buildings with impossible values (4 and 1,175 kWh/m²/yr), which
means the meter and the floor area do not describe the same thing.

**`src/03_kpis.py`**: daily, monthly and annual KPIs: kWh, kWh/m², baseload, peak, load factor,
after-hours kWh and share, CO2, EUI, and benchmarking (rank, percentile, peer median within type). *Key
ideas:* annualisation (`kwh_annualised = measured × 8,760 / valid hours`) so gaps do not flatter a
building; `after_hours_time_share` next to `after_hours_share`, because an office open 50 of 168 hours a
week would show 70% "after-hours energy" even with a perfectly flat load; `weekend_weekday_ratio` as a
reality check on the assumed opening hours.

**`src/04_anomalies.py`**: three detectors (section 3 explains why).
* MAD baseline: expected load per hour = rolling median of the 15 nearest observations with the same
  hour-of-day and weekday/weekend; robust z = (actual − expected) / (1.4826 × MAD), with the scale floored
  at 10% of the building's mean load; an hour is flagged if |z| ≥ 3.5 for at least 2 hours in a row.
* Isolation Forest per building on hour, weekday, opening flag, load, lagged loads (1 h, 24 h, 168 h),
  24-hour rolling mean and temperature.
* Weather view: daily kWh = a + b·HDD + c·CDD + d·weekend (least squares per building); days whose
  residual has |robust z| ≥ 3.5 are flagged.
Hourly flags are grouped into one event per building-day per method, with a severity bucket and a plain
reason tag. It also writes `reports/mad_sensitivity.csv`, the trade-off table behind the calibration.

**`src/05_savings.py`**: three overlapping estimates: after-hours excess above baseload (upper bound),
baseload cut by 5/10/15% (what-if), worst-quartile buildings reaching their type median (benchmark gap).
*Key idea:* label what kind of number each estimate is, and never add overlapping estimates.

**`src/06_export_powerbi.py`**: writes the star-schema CSVs with fixed columns (the "contract" that the
tests and Power BI rely on), checks each file loads back, and skips the hourly table if it would exceed
100 MB (it is about 16 MB, so it is exported).

**`src/07_report.py`**: figures, `RESULTS.md`, the static preview page, and the generated blocks in the
README and the Power BI build guide. *Key idea:* no number in any document is typed by
hand. It also checks that the manual anomaly notes still match the current example plots.

**`src/plotstyle.py`**: one consistent chart style (palette, thin lines, data-source caption on every
figure). **`src/00_reset.py`**: deletes generated outputs (`make reset` / `make reset-all`).

**`tests/test_pipeline.py`**: fixture tests (EUI 175.2 on a flat 2 kWh building of 100 m²; CO2; gap
filling; each validation check counted once; Isolation Forest deterministic) and output tests (columns,
no negatives, no duplicate keys, every fill flagged, star-schema keys resolve, assumptions exported).

**`notebooks/exploration.ipynb`**: short EDA of the cleaned data (profiles, temperature, EUI spread,
where detectors fire). **`powerbi/`**: the kit to build the report yourself.

---

## 3. Why these methods

**Why a MAD-based z-score instead of a plain z-score?** A plain z-score uses the mean and standard
deviation, and both are pulled towards the outliers you are trying to find. Take six readings: 10, 10, 11,
9, 10, 100. Mean = 25, standard deviation ≈ 36.8, so the 100 has z ≈ 2.0 and would **not** be flagged at
3. The median is 10 and the MAD (median absolute deviation) is 0.5, so its robust z is
(100 − 10) / (1.4826 × 0.5) ≈ 121: obviously flagged. (1.4826 × MAD estimates the standard deviation when
the data is normal, so the robust z reads like an ordinary z.) The 3.5 cut-off is the one Iglewicz and
Hoaglin recommend for this score.

**Why compare against the same hour and day type?** A shop at 3 a.m. and at 3 p.m. are different
situations. "Expected" must come from comparable hours, and the rolling window lets it follow the seasons.

**Why the scale floor and the 2-hour rule? (an honest calibration story)** The first run flagged 23.6% of
building-days. Looking at the plots showed why: a tiny, steady night load (about 1.5 kW) has an almost
zero MAD, so a normal small wiggle got z ≈ 113; and opening or closing an hour early made a one-hour blip
at the ramp. Flooring the scale at 10% of the building's mean load and requiring 2 consecutive flagged
hours brought it to 9.9%. `reports/mad_sensitivity.csv` shows the other options. Without ground truth no
setting is "correct"; the goal was an alert volume a person could actually review.

**Why Isolation Forest as a second opinion?** It needs no assumption about the distribution, and it looks
at combinations of features: a normal load at an abnormal hour, or a sudden jump from the previous hour.
Trees isolate unusual points in fewer random splits. Scaling is not needed because each split is a
threshold on one feature.

**Why weather normalisation?** A hot day makes air-conditioning work harder. Without adjusting for
weather, every heatwave looks like waste and every mild day looks like a saving. The daily regression on
HDD and CDD (plus a weekend term) says how much of the day's use the weather explains, and flags days the
weather does *not* explain.

**When each method fails**

| method | fails when | seen in this project? |
|---|---|---|
| MAD baseline | a permanent schedule change (flags every day until the window catches up); holidays and closures (flagged as `unexpected_low`); more than half of the window is abnormal (the median itself moves) | yes: the Veterans Day closure (example 5) |
| Isolation Forest | there are no real anomalies: it still flags its contamination rate (1%) of hours; it cannot say *why* (our reason tags are borrowed from the baseline); lag features make one spike affect the following hours too | yes: it flags exactly ~1% of scored hours by design |
| Weather regression | the building's heating is not electric, or schedules matter more than weather; the 18 °C base is wrong for the building | yes: R² ranges 0.12–0.86 (median 0.44); several Dublin buildings have *negative* cooling coefficients because Dublin rarely goes above 18 °C, so the term is noise and seasonal schedules leak in. Regression coefficients are not physics |
| Spike check (3 × P99) | spikes make up more than ~1% of readings: they raise P99 and hide themselves | found while writing the tests: with only 60 hours of data, one spike lifted P99 enough to escape |

---

## 4. "Break it" exercises

Do these one at a time. After each change run `mingw32-make clean analyze export` (or `make` if you have
GNU make), compare `RESULTS.md` with the previous version (`git diff RESULTS.md` if you use git), then
**undo the change**.

1. **Flatline threshold.** In `config.yaml` set `flatline_min_hours` from 24 to 6. Watch the flatline
   count in the console and in `data_quality_report.csv`. *What to notice:* meters with coarse resolution
   repeat values naturally, so a short threshold turns normal data into "invalid" data, and buildings can
   start failing `pct_valid`. The threshold decides how much data you throw away.
2. **Double the tariff.** Set `tariff_inr_per_kwh` to 16.0. *What to notice:* every INR figure doubles
   exactly; kWh, CO2 and the ranking do not change. The tariff only rescales money; it never changes which
   building to look at first.
3. **Remove the weather feature.** In `src/04_anomalies.py`, delete `"temp_c"` from `IF_FEATURES`.
   *What to notice:* compare Isolation Forest event counts and the MAD/IF overlap. Hot-afternoon hours that
   looked normal *given the temperature* may now be flagged, or the other way round.
4. **Change one building's opening hours.** Under `operating_hours_overrides` put
   `{Wolf_retail_Toshia: {open: 8, close: 18, days: [Mon, Tue, Wed, Thu, Fri]}}`. *What to notice:* its
   after-hours share and after-hours excess jump, and the Sunday 5 Feb event in `fact_anomalies.csv`
   changes its reason tag from `daytime_spike` to `after_hours_load` (the example plots may also change,
   because Isolation Forest uses the opening flag as a feature). One assumption changes the story told
   about the same data.
5. **Stop treating zeros as invalid.** Set `treat_zero_as_missing` to false. *What to notice:* the year
   coverage line printed by step 2 (the 2016 Panther zeros now count as "valid"), the zero-reading count,
   and baseloads on days with zero readings. One cleaning rule can change which year you analyse.

---

## 5. Self-test

Answer in your own words first; answers are at the very bottom.

1. A building's meter shows 250 kWh for the hour 14:00–15:00. What was its average power in that hour?
2. Why can't you compare the raw annual kWh of two buildings to say which is more efficient?
3. What does a load factor of 0.9 suggest about a shop that closes at 21:00?
4. Why is baseload defined as a low percentile of the day rather than the minimum hour?
5. Give one reason a zero reading on a whole-building electricity meter is treated as invalid.
6. Why are filled values flagged instead of quietly replaced?
7. A building has 300 excluded hours. How does the pipeline stop that making its EUI look better?
8. Why is the MAD scale floored at 10% of the building's mean load?
9. Isolation Forest flagged about 1% of hours in every building. Does that mean 1% of hours are faulty?
10. The two anomaly methods agree on only 155 building-days. Is that a problem? What would you do?
11. Why must the after-hours share always be shown next to the after-hours *time* share?
12. Why are the three savings estimates never added together?
13. Is the CO2 figure in this project the real carbon footprint of these buildings? Why or why not?
14. What is the difference between location-based and market-based Scope 2?
15. You get access to a real store's BMS. What would you check first after an `after_hours_load` alert?

<br><br><br><br><br><br><br><br>

<details>
<summary><b>Answers (open only after trying)</b></summary>

1. 250 kW. One hour of energy in kWh equals the average kW during that hour.
2. Bigger buildings use more. Divide by floor area (EUI) and compare within the same type and climate.
3. It hardly switches anything off at night: average is close to peak. Look at the night baseload.
4. A single odd hour (a short dropout) would set the minimum; the 5th percentile is robust to it.
5. A whole building always draws something (fridges, servers, emergency lights). Exactly 0 almost always
   means the meter or the data transfer dropped out. BDG2's own cleaning treats it the same way.
6. So nothing is silently altered: anyone can see, count and exclude interpolated values, and the tests can
   prove every change is flagged.
7. It annualises: measured kWh × (hours in year ÷ valid hours), so missing hours are scaled up, not
   treated as zero use.
8. A very steady or very small load has a tiny MAD, so tiny normal wiggles became huge z-scores (z ≈ 113 in
   the first run). The floor stops that.
9. No. The contamination setting forces it to flag that share. It ranks hours by unusualness; it does not
   estimate how many faults exist.
10. Not necessarily: they look at different things (one hour vs its usual level, vs a combination of
    features). With no ground truth, inspect events from both "only" groups and the overlap, and get
    labels (site feedback, BMS logs) to measure accuracy properly.
11. A flat load would put the same share of energy as of time outside opening hours (70% for an office
    open 50 of 168 hours). Only energy share *above* time share, or above baseload, suggests waste.
12. They overlap: cutting baseload also cuts after-hours load, and the benchmark gap includes both. Adding
    them counts the same kWh two or three times.
13. No. It applies India's grid factor to buildings in the USA and Ireland. It demonstrates the method; the
    real figure needs each site's local grid factor.
14. Location-based uses the average factor of the local grid; market-based uses the factor of the
    electricity contracted (green tariffs, renewable certificates, power purchase agreements).
15. The trends for the flagged hours: HVAC on/off status and schedules, setpoints, lighting circuits,
    overrides; whether a holiday, event, restock or cleaning shift was planned; whether the BMS time zone or
    clock is right.

</details>
