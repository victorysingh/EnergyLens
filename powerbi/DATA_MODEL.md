# Data model (star schema)

All tables are CSV files in `data/processed/`, written by `src/06_export_powerbi.py`.
Power BI names each table after its file, so `fact_daily_energy.csv` becomes `fact_daily_energy`.

## Why a star schema

A star schema keeps descriptions (which building, which date) in small **dimension** tables and the numbers
in long **fact** tables that only hold keys and values. One slicer on a dimension then filters every fact
table the same way, the DAX stays simple, and nothing is double-counted because each building or date
exists exactly once.

## Diagram

```
                         ┌──────────────────────┐
                         │     dim_building     │  1 row per building (25)
                         │  building_id  (key)  │
                         └──────────┬───────────┘
             ┌───────────┬──────────┼───────────┬──────────────┬──────────────────┐
             │ *         │ *        │ *         │ *            │ *                │ *
   fact_daily_energy  fact_hourly  fact_monthly_kpi  fact_annual_kpi  fact_anomalies  fact_opportunities
             │ *         │ *        │ *                            │ *
             └───────────┴────┬─────┴──────────────────────────────┘
                              │ 1
                         ┌────┴─────────────────┐
                         │       dim_date       │  1 row per day of the analysis year (365)
                         │  date  (key)         │  Mark as date table
                         └──────────────────────┘

  Not related (stand-alone, used as text panels):  assumptions,  data_quality_report
```

## Tables

| table | grain (one row per…) | key columns | notes |
|---|---|---|---|
| `dim_building` | building | `building_id` | site, type (Retail/Office), floor area m², quality flag, assumed opening hours |
| `dim_date` | calendar day | `date` | year, month, month name, week, day of week, weekend flag, season |
| `fact_daily_energy` | building × day | `building_id`, `date` | kWh, kWh/m², baseload kW, peak kW, after-hours kWh, temperature, HDD/CDD, filled flag |
| `fact_hourly_energy` | building × hour | `building_id`, `date` | hourly kWh (= average kW), `is_open`, filled flag, quality issue. For the heatmap and peak |
| `fact_monthly_kpi` | building × month | `building_id`, `month_start` | kWh, EUI for the month, CO2, load factor |
| `fact_annual_kpi` | building × year | `building_id` | annualised kWh, EUI, rank and percentile in type, peer median, after-hours shares |
| `fact_anomalies` | anomaly event (building × day × method) | `building_id`, `date` | method, score, severity, reason tag, flagged hours, deviation kWh |
| `fact_opportunities` | building × opportunity × scenario | `building_id` | kWh / INR / tCO2 estimates, label, `is_headline`, `rank` |
| `assumptions` | setting | `key` | every assumption with value, unit, label, source. **No relationship** |
| `data_quality_report` | candidate building (92, incl. rejected) | `building_id` | **No relationship**: it includes buildings that are not in `dim_building` |

## Relationships to create

All are **one-to-many (1 → \*)**, **single** cross-filter direction (dimension filters fact), **active**.

| from (1 side) | to (\* side) |
|---|---|
| `dim_building[building_id]` | `fact_daily_energy[building_id]` |
| `dim_building[building_id]` | `fact_hourly_energy[building_id]` |
| `dim_building[building_id]` | `fact_monthly_kpi[building_id]` |
| `dim_building[building_id]` | `fact_annual_kpi[building_id]` |
| `dim_building[building_id]` | `fact_anomalies[building_id]` |
| `dim_building[building_id]` | `fact_opportunities[building_id]` |
| `dim_date[date]` | `fact_daily_energy[date]` |
| `dim_date[date]` | `fact_hourly_energy[date]` |
| `dim_date[date]` | `fact_anomalies[date]` |
| `dim_date[date]` | `fact_monthly_kpi[month_start]` |

`fact_annual_kpi` and `fact_opportunities` cover the whole year, so they have **no date relationship**: a
date slicer does not change them (that is intended; say so in the visual title).

Why single direction: with both directions on, a filter on one fact table could flow back through a
dimension into another fact table and produce surprising numbers or "ambiguous path" errors.

## Columns to hide (right-click → Hide in report view)

Hide these so report builders use the dimension columns and the measures instead:

* every fact table's `building_id`, `date` and `month_start` (use `dim_building` / `dim_date` columns in visuals)
* `dim_date[day_of_week]`, `dim_date[month]` (used only for **Sort by column**: `day_name` by `day_of_week`,
  `month_name` by `month`)
* raw numeric columns that have a measure (e.g. `fact_daily_energy[kwh]`): use `[Total kWh]` instead, so
  every visual sums the same way

Keep visible: `dim_building[type]`, `[site]`, `[building_id]`, `dim_date[date]`, `[month_name]`,
`[day_name]`, `fact_hourly_energy[hour]`, `fact_anomalies[severity]`, `[reason]`, `[method]`,
`fact_opportunities[opportunity_type]`, `[scenario]`.

## Data types to check after import

| column type | examples | Power BI type |
|---|---|---|
| keys and labels | `building_id`, `type`, `severity`, `reason` | Text |
| dates | `date`, `month_start` | **Date** (not Date/Time) |
| timestamps | `fact_hourly_energy[timestamp]`, `fact_anomalies[timestamp]` | Date/Time |
| flags | `filled_flag`, `is_open`, `is_weekend`, `complete_day`, `is_headline`, `selected` | True/False |
| numbers | kWh, kW, m², shares, scores | Decimal number |
| integers | `hour`, `valid_hours`, `flagged_hours`, `rank`, `week` | Whole number |

`fact_anomalies[timestamp]` is blank for `weather_regression` events (they are whole days); that is expected.
`fact_daily_energy[kwh]` is blank for a day with no valid readings (the data was excluded, not guessed).
