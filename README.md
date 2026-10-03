# Retail energy analytics pipeline + Power BI kit

A Python pipeline that validates, cleans and analyses a year of **real hourly electricity data** for 25
retail and office buildings from the **public Building Data Genome Project 2 (BDG2)** dataset. It computes
energy KPIs (EUI, baseload, peak, load factor, after-hours use), Scope 2 carbon, peer benchmarks, anomalies
(two methods plus a weather-normalised check) and savings estimates, then exports a star-schema dataset
for Power BI.

> **Scope, honestly:** this is an **analysis of a public dataset**. It is not a deployed or real-time
> system, it is not connected to any EMS or BMS, and the buildings are not any retailer's stores (BDG2
> buildings are anonymised; they are called "buildings" throughout). The tariff (INR), the emission factor
> (CEA, India), the opening hours and the savings scenarios are **assumptions**, listed with sources in
> `config.yaml` and `data/processed/assumptions.csv`. The buildings are in the USA and Ireland, so INR and
> CO2 figures demonstrate the method only. **No synthetic data is used.**

## Status

| part | status |
|---|---|
| Data pipeline (download, validation, cleaning) | Done: runs end-to-end with `make all`; 28 tests pass |
| Analysis (KPIs, anomalies, savings) | Done: results in [RESULTS.md](RESULTS.md) |
| Power BI kit (data model, DAX, spec, build guide) | Done: see [powerbi/](powerbi/) |
| **Power BI report** | **Power BI report: NOT YET BUILT (kit ready)** |

The last line changes only when JP has built the report in Power BI Desktop (see the checklist in
[powerbi/BUILD_GUIDE.md](powerbi/BUILD_GUIDE.md)).

## Data source and citation

Building Data Genome Project 2: <https://github.com/buds-lab/building-data-genome-project-2>. The files
used are the raw hourly electricity meters, the building metadata and the weather data (calendar year
2017). Download URLs, dates and SHA-256 checksums are logged in `data/raw/SOURCES.md` after `make data`.

> Miller, C., Kathirgamanathan, A., Picchetti, B. et al. The Building Data Genome Project 2, energy meter
> data from the ASHRAE Great Energy Predictor III competition. *Sci Data* 7, 368 (2020).
> https://doi.org/10.1038/s41597-020-00712-x

External assumption sources: CEA *CO2 Baseline Database for the Indian Power Sector*, Version 22.0
(emission factor), and the KERC electricity tariff schedule HT-2(b) published by BESCOM (tariff). Exact
URLs are in `config.yaml`.

## How to run

Requirements: Python 3.11+ and about 400 MB of free disk space.

```bash
cd retail-energy-analytics
python -m pip install -r requirements.txt
make all            # download → validate/clean → KPIs, anomalies, savings → export → tests
```

On Windows without GNU make, use `mingw32-make all` (MSYS2), or run the steps directly:

```bash
python src/01_download.py        # make data     (downloads ~194 MB, verifies checksums)
python src/02_validate_clean.py  # make clean    (validation and cleaning; NOT "delete outputs")
python src/03_kpis.py            # make analyze
python src/04_anomalies.py
python src/05_savings.py
python src/06_export_powerbi.py  # make export
python src/07_report.py
python -m pytest -q tests        # make test
```

`make reset` deletes generated outputs; `make reset-all` also deletes the downloaded data.
`make notebook` re-executes `notebooks/exploration.ipynb`. The run is deterministic (fixed seed 42).
Power BI-ready CSVs are written to `data/processed/`; figures to `reports/figures/`; a static preview
page (clearly marked as **not** the Power BI report) to `reports/preview_dashboard.html`.

## Key findings

Generated from the latest run by `src/07_report.py` (details and caveats in [RESULTS.md](RESULTS.md)):

<!-- FINDINGS:START -->
1. **Data quality:** validating 92 candidate buildings (11 Retail + 81 Office) for 2017 flagged 1.78% of 805,920 hourly readings as invalid (12,282 missing values, 1,308 zero readings, 730 flatline hours, 1 spike). 10 buildings failed (5 eui_implausible, 5 pct_valid<95.0); 25 were kept (9 Retail, 16 Office).
2. **EUI spread:** electricity EUI runs from 51 to 418 kWh/m²/yr across the 9 Retail buildings (median 147) and from 45 to 240 across the 16 offices (median 143). The gap between the best and worst quartile (P75 − P25) is 161 kWh/m²/yr for Retail and 81 for Office.
3. **After-hours use:** offices use 49%–68% of their electricity outside the assumed 08:00–18:00 weekday hours (which cover 30% of the week). After-hours load above each building's own baseload adds up to 2,342,873 kWh/yr (11.1% of portfolio use): an upper bound, worth ₹1.87 crore (INR 18,742,985) at the assumed ₹8.00/kWh.
4. **Anomalies:** the MAD baseline flagged 906 building-days (266 high severity) and Isolation Forest 599. They agree on only 155 building-days (Jaccard 0.115). With no ground truth, that is disagreement to investigate, not an accuracy score.
5. **Carbon and benchmark gap:** with the CEA India factor (0.675 tCO2/MWh, applied for demonstration only) the portfolio's 21,101,830 kWh/yr equals 14,244 tCO2. Bringing the 7 worst-quartile buildings to their type's median EUI would avoid 3,761,700 kWh/yr (17.8% of portfolio use, 2,539 tCO2). That is a benchmark gap, not a forecast.
<!-- FINDINGS:END -->

## Limitations

- **Location mismatch:** the CEA emission factor and KERC tariff are Indian; the buildings are in the USA
  and Ireland. CO2 and INR values illustrate the method, not the buildings' real footprint or cost.
- **No ground truth for anomalies:** results are counts and agreement between methods, not precision or
  recall. Five example events were inspected by eye ([notes](reports/anomaly_inspection_notes.md)).
- **Assumed operating hours** (Retail 09:00–21:00 daily, Office 08:00–18:00 weekdays) drive the
  after-hours figures; a weekend/weekday check shows they do not fit every building.
- **Gap filling:** gaps of up to 3 hours are interpolated and flagged; longer gaps are excluded and annual
  totals scaled up to a full year.
- **Electricity only, one year, hourly:** no gas or heating data, no year-over-year comparison, no
  sub-hourly peaks; small peer groups, so ranks move easily.
- **Metadata issue:** the Dublin site's longitude has the wrong sign in BDG2's metadata; it is reported,
  not changed.
- **MAD thresholds were calibrated** after a first run flagged 23.6% of building-days; the trade-off
  table is in `reports/mad_sensitivity.csv`.

## Repository layout

```
config.yaml            all settings and assumptions (each with source and label)
src/                   01_download … 07_report (pipeline), common.py, plotstyle.py, 00_reset.py
data/raw/              downloaded BDG2 files + SOURCES.md (CSV files gitignored)
data/processed/        Power BI-ready CSVs, data_quality_report.csv, assumptions.csv
reports/               figures/, preview_dashboard.html, anomaly_inspection_notes.md, mad_sensitivity.csv
powerbi/               DATA_MODEL.md, measures.dax, power_query.m, REPORT_SPEC.md, BUILD_GUIDE.md, theme.json
notebooks/             exploration.ipynb (EDA)
tests/                 test_pipeline.py (pytest)
RESULTS.md · LEARNING_GUIDE.md · LICENSE
```

## How this was built

The pipeline, documents and Power BI kit were built with AI assistance (Claude, an AI coding assistant),
working from a written project brief with explicit honesty rules: no invented numbers, every assumption
labelled, and the Power BI report not claimed until it is actually built. The emission factor and tariff
were taken from the official CEA and KERC/BESCOM documents, not from memory. JP reviews and learns the
project using [LEARNING_GUIDE.md](LEARNING_GUIDE.md) and builds the Power BI report personally using
[powerbi/BUILD_GUIDE.md](powerbi/BUILD_GUIDE.md).

**Review status: NOT YET REVIEWED BY JP.** Change this line to "Reviewed by JP on <date>" only after
working through the learning guide's self-test and "break it" exercises.
