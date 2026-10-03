# Report spec: 4 pages, deliberately simple

Measures are in `measures.dax`; tables and relationships are in `DATA_MODEL.md`.
Every page carries the same honest **subtitle**: a card or text box bound to the `[Report Subtitle]`
measure ("Data: Building Data Genome Project 2 (public dataset, real meter data)… demonstration only").

## Look and feel

| item | choice |
|---|---|
| theme | import `powerbi/theme.json` (View > Themes > Browse for themes) |
| page background | `#fcfcfb` (near-white) |
| text | `#0b0b0b` titles, `#52514e` labels; font **Segoe UI** (Semibold for titles) |
| accent | **one** accent, blue `#2a78d6`, used for the main series |
| building type colours | Retail `#2a78d6` (blue), Office `#eb6834` (orange): the same in every visual |
| anomaly / "bad" colour | `#d03b3b` (red), only for high severity, and always together with the word "high" |
| heatmap | single-hue blue scale, light `#cde2fb` to dark `#184f95` |
| gridlines | light grey, solid, thin; no 3-D, no pie charts, no second y-axis |

Accessibility: never let colour alone carry meaning (severity is also written as text); keep data labels
on bars; every visual has a title that states the question it answers.

Canvas: 16:9, 1280 × 720. Layout grid: slicers in one row at the top, KPI cards under them, charts below.

---

## Page 1: Portfolio Overview

*Question: how much electricity do these buildings use, how efficiently, and is there an opportunity?*

| # | visual | fields | answers |
|---|---|---|---|
| 1 | Slicers (dropdown) | `dim_building[type]`, `dim_building[site]` | "which buildings am I looking at?" |
| 2 | Card | `[Total kWh]` (display units: Millions) | total electricity used in the selection |
| 3 | Card | `[EUI (annual)]` (1 decimal, suffix "kWh/m²/yr") | how intensively floor area uses electricity |
| 4 | Card | `[Total CO2 t (annualised)]`; card title "CO2 t/yr (CEA India factor, demo)" | carbon at the demonstration factor |
| 5 | Card | `[Estimated Savings INR]`; title "After-hours excess, upper bound (₹, assumed tariff)" | size of the headline opportunity |
| 6 | Line chart | X: `dim_date[month_start]`; Y: `[Total kWh per m2]`; Legend: `dim_building[type]` | is use seasonal; do Retail and Office differ per m²? |
| 7 | Line and clustered column chart | X: `dim_building[building_id]` (sort by `[EUI (annual)]` descending); Column Y: `[EUI (annual)]`; Line Y: `[Peer Median EUI]`; tooltip: `[EUI Rank in Type]`, `[Peers in Type]` | which buildings use the most per m², against their own type's median? Put a type slicer next to it or use small multiples by `type` |
| 8 | Text box | "EUI is electricity only and compares buildings within a type. Sites are in Florida, Arizona, Washington DC and Dublin, so climate differs." | prevents over-reading the ranking |

## Page 2: Building Drill-down

*Question: how does one building behave hour by hour, and when did it do something unusual?*

| # | visual | fields | answers |
|---|---|---|---|
| 1 | Slicer (dropdown, **single select**) | `dim_building[building_id]` | pick the building |
| 2 | Slicer (between) | `dim_date[date]` | zoom into a period |
| 3 | Cards | `[EUI (annual)]`, `[EUI Rank in Type]` (with `[Peers in Type]` in the title), `[Load Factor]`, `[After-Hours Share %]` vs `[After-Hours Time Share %]` | the building's key numbers at a glance |
| 4 | Line chart | X: `dim_date[date]`; Y: `[Total kWh]` and `[kWh on Anomaly Days]`. Format: series `kWh on Anomaly Days` → line stroke 0, markers on, red `#d03b3b`, size 6 | daily use, with anomaly days marked |
| 5 | Matrix (heatmap) | Rows: `dim_date[day_name]` (sorted by `day_of_week`); Columns: `fact_hourly_energy[hour]`; Values: `[Avg kWh per Hour]`. Format: Cell elements → Background colour → gradient `#cde2fb` → `#184f95`; turn off totals | when is the building busy; is night load high; are weekends different? |
| 6 | Card or table | `dim_building[opening_hours_assumed]`, `fact_annual_kpi[weekend_weekday_ratio]` | shows the opening hours are an assumption, and whether the data agrees |

## Page 3: Anomalies and Waste

*Question: where and when did consumption look abnormal, and how much after-hours use is there?*

| # | visual | fields | answers |
|---|---|---|---|
| 1 | Slicers | `fact_anomalies[method]`, `fact_anomalies[severity]`, `dim_building[type]` | filter the event list |
| 2 | Cards | `[Anomaly Count]`, `[High-Severity Anomaly Count]` | how many events |
| 3 | Table | `dim_building[building_id]`, `fact_anomalies[date]`, `[method]`, `[severity]`, `[reason]`, `[flagged_hours]`, `[deviation_kwh]`; sort by `deviation_kwh` descending; conditional font colour red on `severity` = "high" | the events to look at first, biggest kWh impact on top |
| 4 | Stacked bar chart | Y: `fact_anomalies[reason]`; X: `[Anomaly Count]`; Legend: `fact_anomalies[method]` | what kind of anomalies, and do methods agree? |
| 5 | Clustered bar chart | Y: `dim_building[building_id]`; X: `[After-Hours Share %]` and `[After-Hours Time Share %]` | which buildings use more energy after hours than a flat load would? |
| 6 | Text box | "There is no ground truth in this data. An anomaly is a prompt to ask a question, not a confirmed fault. 'High' severity means statistically unusual, not expensive." | honest reading |

## Page 4: Opportunities and Assumptions

*Question: where are the biggest estimated savings, and what are they based on?*

| # | visual | fields | answers |
|---|---|---|---|
| 1 | Slicers | `fact_opportunities[opportunity_type]`, `fact_opportunities[scenario]` | pick one estimate type at a time |
| 2 | Table | `fact_opportunities[rank]`, `dim_building[building_id]`, `[opportunity_type]`, `[scenario]`, `[estimate_label]`, `[kwh_saving]`, `[inr_saving]`, `[co2_saving_t]`, `[pct_of_building_kwh]`, `[basis]`; visual-level filter `rank` is not blank; sort by `rank` | the ranked opportunity list |
| 3 | Cards | `[Estimated Savings kWh]`, `[Estimated Savings INR]`, `[Estimated Savings tCO2]`, all titled "after-hours excess (upper bound)" | headline, never a sum of overlapping types |
| 4 | Table (assumptions panel) | `assumptions[key]`, `[value]`, `[unit]`, `[source]`; visual-level filter `label` = "ASSUMPTION" | what the money and carbon numbers depend on |
| 5 | Table | `data_quality_report[building_id]`, `[building_type]`, `[pct_valid]`, `[filled_hours]`, `[excluded_hours]`, `[quality_flag]`, `[fail_reasons]` | which buildings were kept or rejected, and why |
| 6 | Text box: **Data quality & limitations** | text below | what not to conclude |

Text for the **Data quality & limitations** box (copy as is):

> Public BDG2 data, real hourly meter readings, one year. Invalid readings (missing, zero, flatline, spike)
> were removed; gaps up to 3 hours were interpolated and flagged; longer gaps were excluded and annual totals
> scaled up. The tariff (INR) and emission factor (CEA India) are assumptions applied to buildings in the USA
> and Ireland for demonstration. Opening hours are assumed. Savings are estimates: the after-hours figure is an
> upper bound and the opportunity types overlap, so they must not be added. Anomalies have no ground truth.

## Do not use

* **Map visual:** the source metadata has the Dublin site's longitude with the wrong sign (+6.26 instead of
  −6.26), which would put those buildings in the Netherlands. See RESULTS.md, section 2.
* **Pie or donut charts** for shares: use bars.
* **Totals across opportunity types:** use the headline measures only.
