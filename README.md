# taf-decoder

[![CI](https://github.com/Sladekd/Terminal-Forecast-Python-Processing/actions/workflows/ci.yml/badge.svg)](https://github.com/Sladekd/Terminal-Forecast-Python-Processing/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/taf-decoder.svg)](https://pypi.org/project/taf-decoder/)
[![Python](https://img.shields.io/pypi/pyversions/taf-decoder.svg)](https://pypi.org/project/taf-decoder/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Decode aviation **TAF** (Terminal Aerodrome Forecast) reports into tidy
[pandas](https://pandas.pydata.org) DataFrames, download TAF archives from
[Ogimet](https://www.ogimet.com) and plot forecast wind.

The methods are described in
*Sládek D. et al. (2024), Analyses of European terminal aerodrome weather forecasts in 2022 and 2023,
Aviation 28(2), 100–114, [doi:10.3846/aviation.2024.21690](https://doi.org/10.3846/aviation.2024.21690).*

## Installation

```bash
pip install taf-decoder            # decoder only (needs pandas)
pip install "taf-decoder[plot]"    # + matplotlib for plot_wind
```

Python 3.9 or newer, pandas 1.4 or newer (including pandas 3).

## Quick start

```python
from taf_decoder import decode_taf

taf = decode_taf(
    "202308030500 TAF LKTB 030500Z 0306/0406 17007KT 9999 SCT025 "
    "TEMPO 0306/0309 19013KT RA BKN025 BECMG 0322/0400 VRB02KT="
)
taf.station, taf.issue_time, taf.valid_from, taf.valid_to
# ('LKTB', datetime(2023, 8, 3, 5, 0), datetime(2023, 8, 3, 6, 0), datetime(2023, 8, 4, 6, 0))

taf.groups[1].wind          # Wind(direction=190, speed=13, gust=None, unit='KT', ...)
df = taf.to_dataframe("timeline")
```

### Year and month

A TAF only contains day and hour. The year and month are taken from

1. a leading `YYYYMMDDHHMM` stamp (as in Ogimet exports), else
2. `reference_time=` (any `datetime`, `date`, ISO string or `YYYYMMDDHHMM` near the issue time), else
3. the current UTC time.

The calendar month closest to that reference is chosen, so forecasts crossing a month or year
boundary (`3118/0118`, `3122/0106`) and `24`-hour notation (`0306/0324`) resolve correctly.
All datetimes are UTC (timezone-naive).

```python
decode_taf("TAF EDDT 311700Z 3118/0124 24015KT 9999 FEW040=", reference_time="2020-07-31")
```

## Three table layouts

| `kind`      | One row per …                     | Use for |
|-------------|-----------------------------------|---------|
| `"groups"`  | forecast group, exactly as written | archiving, verification of individual groups |
| `"timeline"`| prevailing state + each TEMPO/PROB group | the representation from the publication |
| `"hourly"`  | hour × active group               | plotting, hourly statistics, joining with METARs |

```python
from taf_decoder import taf_to_dataframe

taf_to_dataframe(text, kind="timeline")
taf.to_dataframe("hourly", becmg="start")
```

**Timeline rules** (ICAO Annex 3):

* `BECMG` changes only the elements it mentions; everything else is inherited.
  A new set of cloud layers (or `NSC`) replaces *all* previous layers, `NSW` ends weather,
  `CAVOK` clears weather and clouds, and visibility/weather/clouds cancel a previous `CAVOK`.
* `FM` replaces all conditions from its start time.
* `becmg=` sets when a `BECMG` change takes effect: `"overlap"` (default, as in the publication:
  the old state lasts until the end of the BECMG period, the new one starts at its beginning),
  `"start"` or `"end"`.
* `TEMPO`/`PROB`/`INTER` rows take elements they do not mention from the prevailing state at
  their start (`fill_temporary=False` to disable).

### Columns

All layouts share one schema, so frames from many TAFs concatenate cleanly:

| Column | Meaning |
|---|---|
| `station`, `issue_time`, `valid_from`, `valid_to` | header |
| `amendment`, `correction`, `nil`, `cancelled` | header flags (`TAF AMD`, `TAF COR`, `NIL`, `CNL`) |
| `group_index`, `change`, `probability`, `group_code` | group position, `BASE`/`BECMG`/`FM`/`TEMPO`/`PROB`/`INTER`, 30/40, numeric code from the publication (0 base, 1 TEMPO, 2 PROB30, 3 PROB30 TEMPO, 4 PROB40, 5 PROB40 TEMPO, 6 BECMG, 7 FM, 8 INTER) |
| `prevailing`, `start`, `end` | prevailing state vs temporary group; period (end exclusive) |
| `wind_dir`, `wind_variable`, `wind_speed`, `wind_gust`, `wind_unit` | wind as reported (`wind_dir` empty for `VRB`) |
| `wind_speed_kt`, `wind_gust_kt` | converted to knots (from `KT`, `MPS`, `KMH`) |
| `wind_var_from`, `wind_var_to` | variable direction `dddVddd` |
| `visibility_m`, `visibility_raw`, `cavok` | metres (`CAVOK` = 10000, statute miles converted) and the original text |
| `weather`, `nsw` | e.g. `"-SHRA BR"`; `NSW` flag |
| `cloud_cover_N`, `cloud_height_ft_N`, `cloud_type_N` | layers (N = 1…4, more if present), height in feet |
| `no_clouds`, `ceiling_ft` | `NSC`/`SKC`/`NCD`/`CLR`; lowest BKN/OVC/VV |
| `max_temp_c`, `max_temp_time`, `min_temp_c`, `min_temp_time` | `TX`/`TN` groups |
| `raw_group`, `unparsed` | original group text; tokens that could not be decoded |

Integers use pandas' nullable `Int64`, flags `boolean`, times `datetime64`.

## Many TAFs and Ogimet archives

```python
from taf_decoder import download_ogimet, read_ogimet_file, decode_many

download_ogimet(["EDDT", "LKTB"], 2020, 7, save_dir="data")   # writes data/TAF202007.txt
tafs = read_ogimet_file("data/TAF202007.txt")                   # report_time, taf
df = decode_many(tafs["taf"], kind="timeline")
```

`decode_many` never stops on a bad report (unless `errors="raise"`): each row carries
`taf_index` (position in the input), `warnings` and `error`, so problems are visible and
countable:

```python
df.drop_duplicates("taf_index")["error"].notna().sum()   # undecodable reports
df["unparsed"].dropna().value_counts()                   # tokens to look at
```

`download_ogimet` retries transient network errors, raises `OgimetError` when Ogimet reports
its quota limit or returns nothing, and has no dependencies beyond the standard library.
Please respect Ogimet's limits (one request at a time, pause between months) and credit the
Ogimet database in publications.

## Plotting

```python
from taf_decoder import plot_wind

ax = plot_wind(text)                       # TAF string, Taf, timeline or hourly frame
ax.figure.savefig("wind.png")              # or plot_wind(text, save_path="wind.png")
```

![Wind speed and gust forecast](https://raw.githubusercontent.com/Sladekd/Terminal-Forecast-Python-Processing/main/docs/img/plot_wind.png)

## Command line

```bash
taf-decoder "TAF LKTB 030500Z 0306/0406 17007KT 9999 SCT025=" --reference-time 2023-08-03
taf-decoder -f data/TAF202007.txt -k timeline -o decoded.csv
cat tafs.txt | taf-decoder --format json
```

The exit code is 1 if any report could not be decoded. `--strict` also fails on unparsed tokens.

## What is decoded

Header: `TAF`, `AMD`, `COR`, `RTD`, `AUTO`, `NIL`, `CNL`, `RMK`, issue time, validity
(`DDHH/DDHH` and legacy `DDHHHH`). Change groups: `BECMG`, `TEMPO`, `FMDDHHMM` (also `FM DDHHMM`),
`PROB30`, `PROB40`, `PROB30/40 TEMPO`, `INTER`. Elements: wind (`KT`/`MPS`/`KMH`, `VRB`, gusts,
3-digit speeds, `dddVddd`), visibility (metres, `NDV`, directional, statute miles incl. `1 1/2SM`,
`P6SM`, `M1/4SM`), `CAVOK`, present weather (intensity, descriptor, phenomena, `VC`), `NSW`,
clouds (`FEW`/`SCT`/`BKN`/`OVC` with `CB`/`TCU`, `///`), vertical visibility, `NSC`/`SKC`/`NCD`/`CLR`,
`TX`/`TN` temperatures. Anything else (e.g. wind shear, military icing/turbulence codes) is kept
in `unparsed` and reported in `warnings`, never dropped silently.

## Migrating from the notebooks

The original notebooks are kept in [`notebooks/`](notebooks/). Their function
`process_taf_to_df` still works (with a `DeprecationWarning`) and returns the timeline layout, but
column names follow the schema above: `start`/`end` instead of `st_date`/`end_date`,
`wind_speed` instead of `spd`, `group_code` instead of `group_ind`, `cloud_cover_1` instead of
`cover0`. Bugs fixed relative to the notebooks are listed in the [changelog](CHANGELOG.md).

## Development

```bash
pip install -e ".[dev]"
pytest --cov          # unit + property-based (hypothesis) tests
ruff check src tests && mypy src
```

## Citation

If you use this package in published work, please cite the article above
(GitHub's "Cite this repository" button uses [`CITATION.cff`](CITATION.cff)). Earlier work:
[doi:10.1109/ICMT52455.2021.9502819](https://doi.org/10.1109/ICMT52455.2021.9502819),
[doi:10.3390/atmos12020138](https://doi.org/10.3390/atmos12020138).

## Decoding procedure

How BECMG groups, which have short periods but change the forecast until the next BECMG/FM
change, are handled:

![Process of decoding](https://raw.githubusercontent.com/Sladekd/Terminal-Forecast-Python-Processing/main/docs/img/Process.PNG)

## License

MIT
