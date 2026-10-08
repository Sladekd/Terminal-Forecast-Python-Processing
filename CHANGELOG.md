# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-10-08

First release as the installable package `taf-decoder`. The notebook code was
rewritten as a token-based parser with a fixed, documented output schema.

### Added
- `decode_taf()` returning typed `Taf` / `Group` / `Wind` / `Cloud` objects.
- Three DataFrame layouts: `groups`, `timeline` (publication layout) and `hourly`.
- `decode_many()` for bulk decoding that records errors and warnings per report instead of stopping.
- `reference_time=` for TAFs without an Ogimet `YYYYMMDDHHMM` stamp.
- `becmg=` (`overlap`/`start`/`end`) and `fill_temporary=` options for the timeline.
- Decoding of `MPS`/`KMH` winds, `dddVddd`, statute-mile visibility, `NDV` and directional
  visibility, vertical visibility, `SKC`/`NCD`/`CLR`, `TX`/`TN`, `INTER`, `PROB` without `TEMPO`,
  `NIL`, `CNL`, `AUTO`, `RMK`, legacy `DDHHHH` validity.
- Wind converted to knots (`wind_speed_kt`, `wind_gust_kt`) and `ceiling_ft`.
- `download_ogimet()` with retries, quota detection and correct last day of month;
  `read_ogimet_file()` / `split_ogimet_text()`.
- `plot_wind()` returning a matplotlib `Axes`.
- `taf-decoder` command line tool (CSV, JSON or table output).
- Test suite including property-based tests; CI on Linux, macOS and Windows, Python 3.9–3.14,
  pandas 1.4–3.x.

### Fixed (compared with the notebooks)
- Crash on pandas ≥ 3.0 (`fillna(method="ffill")` was removed).
- Wrong end date for forecasts crossing a month boundary (e.g. `3118/0118` ended on the 1st of
  the *same* month); year boundary likewise.
- Validity/group end `24` hours.
- Cloud layers forward-filled column by column, mixing layers of different groups; BECMG cloud
  groups now replace all layers.
- TEMPO/PROB groups inherited elements from the previous *TEMPO* group; they now inherit from the
  prevailing state.
- `FM` groups were converted to one-hour BECMG groups and inherited old conditions; they now
  replace all conditions.
- `PROB30`/`PROB40` without `TEMPO` were assigned the wrong group code.
- Gusts were not captured by the decoding notebook.
- `build_TAF_url` ignored its `stations` and `mon` arguments; Ogimet URLs used day 31 for every
  month.
- Inconsistent cloud column names (`cloud` vs `type0`) depending on the branch taken.
- Plotting saved PNG/PDF files to the working directory on every call.
- Regular expressions without raw strings (SyntaxWarning on Python ≥ 3.12).

### Deprecated
- `process_taf_to_df()` – use `taf_to_dataframe(text, kind="timeline")`.
- `clean_taf_ogimet_file()` – use `read_ogimet_file()`.

[0.1.0]: https://github.com/Sladekd/Terminal-Forecast-Python-Processing/releases/tag/v0.1.0
