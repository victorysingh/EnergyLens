// =============================================================================
// power_query.m: Power Query (M) for every table, with EXPLICIT data types.
//
// When to use this: the simple route (Get data > Text/CSV, then Load) usually works. Use these
// queries if Power BI guesses a type wrongly, e.g. numbers come in as text because your Windows
// region uses a comma as the decimal separator. The "en-US" culture below fixes that.
//
// HOW TO USE
//   1. Home > Transform data > Manage Parameters > New Parameter
//        Name: DataFolder   Type: Text
//        Current value: the full path to data\processed\ WITH a trailing backslash, e.g.
//        C:\path\to\retail-energy-analytics\data\processed\
//   2. Home > New Source > Blank Query, then Home > Advanced Editor, paste ONE query below
//      (from "let" to the end of "in ..."), click Done, and rename the query to the table name
//      shown above it (e.g. dim_building). Repeat for each table.
//   3. Close & Apply.
// =============================================================================


// ---------- dim_building ----------
let
    Source = Csv.Document(File.Contents(DataFolder & "dim_building.csv"), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Headers = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Headers, {
        {"building_id", type text}, {"site", type text}, {"type", type text}, {"floor_area_m2", type number},
        {"year", Int64.Type}, {"quality_flag", type text}, {"sub_type", type text}, {"country", type text},
        {"timezone", type text}, {"lat", type number}, {"lng", type number}, {"opening_hours_assumed", type text}
    }, "en-US")
in
    Typed


// ---------- dim_date ----------
let
    Source = Csv.Document(File.Contents(DataFolder & "dim_date.csv"), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Headers = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Headers, {
        {"date", type date}, {"year", Int64.Type}, {"quarter", Int64.Type}, {"month", Int64.Type},
        {"month_name", type text}, {"month_start", type date}, {"year_month", type text}, {"week", Int64.Type},
        {"day_of_week", Int64.Type}, {"day_name", type text}, {"is_weekend", type logical}, {"season", type text}
    }, "en-US")
in
    Typed


// ---------- fact_daily_energy ----------
let
    Source = Csv.Document(File.Contents(DataFolder & "fact_daily_energy.csv"), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Headers = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Headers, {
        {"building_id", type text}, {"date", type date}, {"kwh", type number}, {"kwh_per_m2", type number},
        {"baseload_kw", type number}, {"peak_kw", type number}, {"after_hours_kwh", type number},
        {"temp_mean_c", type number}, {"hdd", type number}, {"cdd", type number}, {"filled_flag", type logical},
        {"valid_hours", Int64.Type}, {"complete_day", type logical}
    }, "en-US")
in
    Typed


// ---------- fact_hourly_energy ----------
let
    Source = Csv.Document(File.Contents(DataFolder & "fact_hourly_energy.csv"), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Headers = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Headers, {
        {"building_id", type text}, {"timestamp", type datetime}, {"date", type date}, {"hour", Int64.Type},
        {"kwh", type number}, {"is_open", type logical}, {"filled_flag", type logical}, {"quality_issue", type text}
    }, "en-US")
in
    Typed


// ---------- fact_monthly_kpi ----------
let
    Source = Csv.Document(File.Contents(DataFolder & "fact_monthly_kpi.csv"), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Headers = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Headers, {
        {"building_id", type text}, {"year_month", type text}, {"month_start", type date}, {"kwh", type number},
        {"eui_month", type number}, {"co2_tonnes", type number}, {"load_factor", type number},
        {"peak_kw", type number}, {"valid_hours", Int64.Type}
    }, "en-US")
in
    Typed


// ---------- fact_annual_kpi ----------
let
    Source = Csv.Document(File.Contents(DataFolder & "fact_annual_kpi.csv"), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Headers = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Headers, {
        {"building_id", type text}, {"year", Int64.Type}, {"kwh_measured", type number}, {"kwh_annualised", type number},
        {"valid_hours", Int64.Type}, {"eui_kwh_m2", type number}, {"co2_tonnes", type number}, {"baseload_kw", type number},
        {"peak_kw", type number}, {"mean_kw", type number}, {"load_factor", type number}, {"after_hours_kwh", type number},
        {"after_hours_share", type number}, {"after_hours_time_share", type number}, {"weekend_weekday_ratio", type number},
        {"eui_rank_in_type", Int64.Type}, {"n_in_type", Int64.Type}, {"eui_percentile_in_type", type number},
        {"peer_median_eui", type number}, {"peer_p25_eui", type number}, {"gap_to_median_eui", type number},
        {"gap_to_best_quartile_eui", type number}
    }, "en-US")
in
    Typed


// ---------- fact_anomalies ----------
let
    Source = Csv.Document(File.Contents(DataFolder & "fact_anomalies.csv"), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Headers = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    // weather_regression events have no timestamp (whole days): turn "" into null before typing
    Blanks = Table.ReplaceValue(Headers, "", null, Replacer.ReplaceValue, {"timestamp"}),
    Typed = Table.TransformColumnTypes(Blanks, {
        {"anomaly_id", Int64.Type}, {"building_id", type text}, {"date", type date}, {"timestamp", type datetime},
        {"method", type text}, {"score", type number}, {"severity", type text}, {"reason", type text},
        {"flagged_hours", Int64.Type}, {"actual_kwh", type number}, {"expected_kwh", type number},
        {"deviation_kwh", type number}
    }, "en-US")
in
    Typed


// ---------- fact_opportunities ----------
let
    Source = Csv.Document(File.Contents(DataFolder & "fact_opportunities.csv"), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Headers = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Headers, {
        {"opportunity_id", Int64.Type}, {"rank", Int64.Type}, {"building_id", type text}, {"opportunity_type", type text},
        {"scenario", type text}, {"estimate_label", type text}, {"kwh_saving", type number}, {"inr_saving", type number},
        {"co2_saving_t", type number}, {"pct_of_building_kwh", type number}, {"is_headline", type logical},
        {"basis", type text}
    }, "en-US")
in
    Typed


// ---------- assumptions (no relationship; text panel) ----------
let
    Source = Csv.Document(File.Contents(DataFolder & "assumptions.csv"), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Headers = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    // value stays TEXT on purpose: it mixes numbers, lists and words
    Typed = Table.TransformColumnTypes(Headers, {
        {"key", type text}, {"value", type text}, {"resolved_value", type text}, {"unit", type text},
        {"label", type text}, {"source", type text}, {"used_by", type text}
    }, "en-US")
in
    Typed


// ---------- data_quality_report (no relationship; includes rejected buildings) ----------
let
    Source = Csv.Document(File.Contents(DataFolder & "data_quality_report.csv"), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Headers = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Headers, {
        {"building_id", type text}, {"site_id", type text}, {"building_type", type text}, {"floor_area_m2", type number},
        {"year", Int64.Type}, {"expected_hours", Int64.Type}, {"missing_timestamps", Int64.Type},
        {"duplicate_timestamps", Int64.Type}, {"missing_values", Int64.Type}, {"negative_readings", Int64.Type},
        {"zero_readings", Int64.Type}, {"spike_readings", Int64.Type}, {"flatline_hours", Int64.Type},
        {"invalid_hours", Int64.Type}, {"pct_valid", type number}, {"filled_hours", Int64.Type},
        {"pct_filled", type number}, {"excluded_hours", Int64.Type}, {"longest_gap_hours", Int64.Type},
        {"area_units_consistent", type logical}, {"eui_annualised", type number}, {"quality_flag", type text},
        {"fail_reasons", type text}, {"selected", type logical}
    }, "en-US")
in
    Typed
