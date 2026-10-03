# Anomaly examples: manual inspection notes

> **What this file is:** notes written by the AI assistant during the build, after
> looking at the five example plots that `src/04_anomalies.py` produces and at the
> daily totals behind them, for JP to review. These are **observations, not
> verified causes**.
> Nobody at these buildings confirmed anything; BDG2 has no fault labels.
>
> The five examples are picked automatically: the strongest MAD-baseline events
> that Isolation Forest also flagged, one per building. `src/07_report.py`
> checks that the examples below still match the current run and warns in
> RESULTS.md if they do not (for example after a config change).

| # | figure | building | date | what the data shows | likely explanation (unverified) | verdict |
|---|---|---|---|---|---|---|
| 1 | anomaly_example_1.png | Wolf_retail_Toshia | 2017-02-05 | Sunday used 2,124 kWh with a full daytime profile (peak 172 kW). Sat 4 Feb used 676 kWh. But this building's schedule is irregular overall: Wed 1 Feb (472 kWh) and Thu 9 Feb (988 kWh) were low, and Sat 11 Feb (2,095 kWh) was high | Irregular use of the building (events, timetable changes) that no weekday/weekend rule captures. The reason tag says `daytime_spike` only because Retail is *assumed* to open 7 days | Real deviation from the usual pattern; the cause is unknown. Also evidence that the opening-hours assumption does not fit this building |
| 2 | anomaly_example_2.png | Rat_office_Jill | 2017-11-02 | On Wed 1 and Thu 2 Nov the afternoon load jumped to about 1,820-1,930 kW against a normal peak of about 820 kW, while the night baseload fell from about 235 kW to about 141 kW. Sat 4 Nov is missing entirely in the raw data | A temporary large load, a plant change or a metering change. Two days in a row with both an unusual peak and an unusual night suggests something real changed, not a single glitch | Strong, both methods agree. Worth a question to the site team in a real project |
| 3 | anomaly_example_3.png | Fox_office_Molly | 2017-08-03 | Load stayed at 20.8 and 17.2 kWh at 18:00 and 19:00, against an expected 8.8 and 4.9 kWh: shutdown about 2 hours late. Only 24 kWh extra in total | Someone worked late, or a schedule overran | Real but tiny. Shows that **"high" severity means statistically unusual, not expensive**: the robust z is 18 because the building's normal evening load is so steady |
| 4 | anomaly_example_4.png | Wolf_office_Rochelle | 2017-07-09 | Sunday used 509 kWh with a weekday-like profile; the next day, Monday 10 Jul, used only 217 kWh (weekend-like). Sat 8 Jul used 261 kWh | Either the working day moved from Monday to Sunday, or the data is shifted by a day for a short period. The data alone cannot tell which | Real pattern break; cause ambiguous. A good example of why anomalies need a human check |
| 5 | anomaly_example_5.png | Panther_retail_Kristina | 2017-11-10 | Friday used 499 kWh and never left baseload (peak 23.8 kW); the Wednesday and Thursday before used about 1,070-1,110 kWh with peaks near 70-77 kW | Consistent with a holiday closure: the US federal Veterans Day holiday was observed on Fri 10 Nov 2017 because 11 Nov fell on a Saturday. Holidays are not in the model | A true "unusual day", but **not waste**: closures show up as `unexpected_low`. A holiday calendar would remove this kind of alert |

## What the five examples teach

* The detectors find **real changes in behaviour**, but a flag is a prompt for a
  question, not a diagnosis.
* Two of the five (1 and 5) are explained by things the model does not know:
  the building's real schedule and public holidays. Adding a holiday calendar and
  learning each building's actual opening days from its own data would be the
  first improvements.
* Severity is about how unusual a reading is, not about kWh or money; sort by
  `deviation_kwh` when the question is "where is the money?".
