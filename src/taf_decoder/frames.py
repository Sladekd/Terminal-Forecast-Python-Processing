"""Convert decoded TAFs into pandas DataFrames.

Three layouts are available:

``groups``
    One row per group, exactly as forecast (nothing inherited).
``timeline``
    The layout described in the publication: the base group and every
    BECMG/FM group become *prevailing* rows holding the full set of conditions
    in force, followed by TEMPO/PROB/INTER rows. Elements not mentioned in a
    BECMG group are inherited from the previous prevailing state; FM groups
    replace everything.
``hourly``
    The timeline expanded to one row per hour (``time`` column).

All layouts share the same column names, so frames from many TAFs can be
concatenated safely.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd

from .models import Group, Taf, Wind

MIN_CLOUD_LAYERS = 4
BECMG_MODES = ("overlap", "start", "end")
TEMPORARY = ("TEMPO", "PROB", "INTER")

META_COLUMNS = [
    "station",
    "issue_time",
    "valid_from",
    "valid_to",
    "amendment",
    "correction",
    "nil",
    "cancelled",
]
GROUP_COLUMNS = ["group_index", "group_code", "change", "probability", "prevailing", "start", "end"]
ELEMENT_COLUMNS = [
    "wind_dir",
    "wind_variable",
    "wind_speed",
    "wind_gust",
    "wind_unit",
    "wind_speed_kt",
    "wind_gust_kt",
    "wind_var_from",
    "wind_var_to",
    "visibility_m",
    "visibility_raw",
    "cavok",
    "weather",
    "nsw",
    "no_clouds",
    "ceiling_ft",
]
TEMP_COLUMNS = ["max_temp_c", "max_temp_time", "min_temp_c", "min_temp_time"]
TAIL_COLUMNS = ["raw_group", "unparsed"]

INT_COLUMNS = {
    "group_index",
    "group_code",
    "probability",
    "wind_dir",
    "wind_speed",
    "wind_gust",
    "wind_var_from",
    "wind_var_to",
    "visibility_m",
    "ceiling_ft",
    "max_temp_c",
    "min_temp_c",
}
FLOAT_COLUMNS = {"wind_speed_kt", "wind_gust_kt"}
BOOL_COLUMNS = {
    "amendment",
    "correction",
    "nil",
    "cancelled",
    "prevailing",
    "wind_variable",
    "cavok",
    "nsw",
    "no_clouds",
}
TIME_COLUMNS = {
    "time",
    "issue_time",
    "valid_from",
    "valid_to",
    "start",
    "end",
    "max_temp_time",
    "min_temp_time",
}


def cloud_columns(n: int) -> List[str]:
    cols = []
    for k in range(1, n + 1):
        cols += [f"cloud_cover_{k}", f"cloud_height_ft_{k}", f"cloud_type_{k}"]
    return cols


def columns(n_layers: int = MIN_CLOUD_LAYERS, hourly: bool = False) -> List[str]:
    """The ordered column list of every layout."""
    head = ["time"] if hourly else []
    return (
        head
        + META_COLUMNS
        + GROUP_COLUMNS
        + ELEMENT_COLUMNS
        + cloud_columns(n_layers)
        + TEMP_COLUMNS
        + TAIL_COLUMNS
    )


# ------------------------------------------------------------------ record building
def _meta(taf: Taf) -> Dict[str, Any]:
    return {
        "station": taf.station,
        "issue_time": taf.issue_time,
        "valid_from": taf.valid_from,
        "valid_to": taf.valid_to,
        "amendment": taf.amendment,
        "correction": taf.correction,
        "nil": taf.nil,
        "cancelled": taf.cancelled,
    }


def _state_of(g: Group) -> Dict[str, Any]:
    return {
        "wind": g.wind,
        "visibility_m": g.visibility_m,
        "visibility_raw": g.visibility_raw,
        "cavok": g.cavok,
        "weather": g.weather,
        "nsw": g.nsw,
        "clouds": g.clouds,
        "no_clouds": g.no_clouds or g.cavok,
    }


def apply_change(state: Dict[str, Any], g: Group) -> Dict[str, Any]:
    """Apply the elements forecast in ``g`` on top of ``state`` (ICAO Annex 3 rules).

    Elements that ``g`` does not mention are kept. CAVOK clears weather and
    clouds; visibility, weather or clouds cancel a previous CAVOK; NSW ends
    weather; a new set of cloud layers (or NSC) replaces all previous layers.
    """
    new = dict(state)
    new["nsw"] = g.nsw
    if g.wind is not None:
        new["wind"] = g.wind
    if g.cavok:
        new.update(
            cavok=True,
            visibility_m=10000,
            visibility_raw="CAVOK",
            weather=(),
            clouds=(),
            no_clouds=True,
        )
        return new
    if g.visibility_m is not None:
        new.update(visibility_m=g.visibility_m, visibility_raw=g.visibility_raw, cavok=False)
    if g.weather:
        new.update(weather=g.weather, cavok=False)
    elif g.nsw:
        new["weather"] = ()
    if g.clouds:
        new.update(clouds=g.clouds, no_clouds=False, cavok=False)
    elif g.no_clouds:
        new.update(clouds=(), no_clouds=True)
    return new


def _record(
    taf: Taf,
    index: int,
    g: Group,
    state: Dict[str, Any],
    start: Optional[datetime],
    end: Optional[datetime],
    prevailing: bool,
) -> Dict[str, Any]:
    rec = _meta(taf)
    wind: Optional[Wind] = state["wind"]
    clouds = state["clouds"]
    heights = [c.height_ft for c in clouds if c.cover in ("BKN", "OVC", "VV") and c.height_ft is not None]
    rec.update(
        group_index=index,
        group_code=g.code,
        change=g.change,
        probability=g.probability,
        prevailing=prevailing,
        start=start,
        end=end,
        wind_dir=wind.direction if wind else None,
        wind_variable=wind.variable if wind else None,
        wind_speed=wind.speed if wind else None,
        wind_gust=wind.gust if wind else None,
        wind_unit=wind.unit if wind else None,
        wind_speed_kt=wind.speed_kt if wind else None,
        wind_gust_kt=wind.gust_kt if wind else None,
        wind_var_from=wind.variable_from if wind else None,
        wind_var_to=wind.variable_to if wind else None,
        visibility_m=state["visibility_m"],
        visibility_raw=state["visibility_raw"],
        cavok=state["cavok"],
        weather=" ".join(state["weather"]) or None,
        nsw=state["nsw"],
        no_clouds=state["no_clouds"],
        ceiling_ft=min(heights) if heights else None,
        max_temp_c=g.max_temp_c,
        max_temp_time=g.max_temp_time,
        min_temp_c=g.min_temp_c,
        min_temp_time=g.min_temp_time,
        raw_group=g.raw,
        unparsed=" ".join(g.unparsed) or None,
    )
    for k, c in enumerate(clouds, start=1):
        rec[f"cloud_cover_{k}"] = c.cover
        rec[f"cloud_height_ft_{k}"] = c.height_ft
        rec[f"cloud_type_{k}"] = c.type
    return rec


def _empty_record(taf: Taf) -> Dict[str, Any]:
    """Header-only row for NIL/cancelled/empty TAFs, so they are not lost."""
    return _meta(taf)


def group_records(taf: Taf) -> List[Dict[str, Any]]:
    if not taf.groups:
        return [_empty_record(taf)]
    return [
        _record(taf, k, g, _state_of(g), g.start, g.end, prevailing=g.change in ("BASE", "BECMG", "FM"))
        for k, g in enumerate(taf.groups)
    ]


def timeline_records(taf: Taf, becmg: str = "overlap", fill_temporary: bool = True) -> List[Dict[str, Any]]:
    """Records for the ``timeline`` layout (see module docstring).

    ``becmg`` controls when a BECMG change takes effect:

    * ``"overlap"`` (publication default): the previous state lasts until the
      *end* of the BECMG period and the new state starts at its *beginning*,
      so both are present during the transition;
    * ``"start"``: switch at the beginning of the BECMG period;
    * ``"end"``: switch at the end of the BECMG period.

    With ``fill_temporary`` TEMPO/PROB/INTER rows inherit elements they do not
    mention from the prevailing state at their start time.
    """
    if becmg not in BECMG_MODES:
        raise ValueError(f"becmg must be one of {BECMG_MODES}, got {becmg!r}")
    if not taf.groups:
        return [_empty_record(taf)]

    base = taf.groups[0]
    # segments: [group_index, group, state, start, end]
    segments: List[list] = [[0, base, _state_of(base), taf.valid_from, taf.valid_to]]
    changes = [
        (k, g) for k, g in enumerate(taf.groups) if g.change in ("BECMG", "FM") and g.start is not None
    ]
    changes.sort(key=lambda kg: kg[1].start)
    for k, g in changes:
        prev = segments[-1]
        if g.change == "FM":
            state = _state_of(g)
            prev_end, new_start = g.start, g.start
        else:
            state = apply_change(prev[2], g)
            g_end = g.end or g.start
            prev_end, new_start = {
                "overlap": (g_end, g.start),
                "start": (g.start, g.start),
                "end": (g_end, g_end),
            }[becmg]
        prev[4] = max(prev[3], prev_end) if prev[3] is not None else prev_end
        segments.append([k, g, state, new_start, taf.valid_to])

    records = [_record(taf, k, g, st, s, e, prevailing=True) for k, g, st, s, e in segments]

    for k, g in enumerate(taf.groups):
        if g.change not in TEMPORARY:
            continue
        state = _state_of(g)
        if fill_temporary and g.start is not None:
            active = [seg for seg in segments if seg[3] is not None and seg[3] <= g.start]
            if active:
                state = apply_change(active[-1][2], g)
        records.append(_record(taf, k, g, state, g.start, g.end, prevailing=False))
    return records


# ------------------------------------------------------------------ DataFrame assembly
def _n_layers(records: Iterable[Dict[str, Any]]) -> int:
    n = MIN_CLOUD_LAYERS
    for r in records:
        while f"cloud_cover_{n + 1}" in r:
            n += 1
    return n


def to_frame(records: List[Dict[str, Any]], hourly: bool = False, extra_front=()) -> pd.DataFrame:
    """Build a DataFrame with a stable column order and nullable dtypes."""
    cols = list(extra_front) + columns(_n_layers(records), hourly=hourly)
    extra = [c for r in records for c in r if c not in cols]
    cols += list(dict.fromkeys(extra))
    df = pd.DataFrame.from_records(records, columns=cols) if records else pd.DataFrame(columns=cols)
    return coerce_dtypes(df)


def coerce_dtypes(df: pd.DataFrame) -> pd.DataFrame:
    for c in df.columns:
        if c in TIME_COLUMNS:
            df[c] = pd.to_datetime(df[c])
        elif c in INT_COLUMNS or c.startswith("cloud_height_ft_"):
            df[c] = pd.to_numeric(df[c]).astype("Int64")
        elif c in FLOAT_COLUMNS:
            df[c] = pd.to_numeric(df[c]).astype("Float64")
        elif c in BOOL_COLUMNS:
            df[c] = df[c].astype("boolean")
        else:
            df[c] = df[c].astype(object).where(df[c].notna(), None)
    return df


def groups_frame(taf: Taf) -> pd.DataFrame:
    """One row per forecast group, exactly as forecast."""
    return to_frame(group_records(taf))


def timeline_frame(taf: Taf, becmg: str = "overlap", fill_temporary: bool = True) -> pd.DataFrame:
    """Prevailing conditions plus TEMPO/PROB/INTER groups (see :func:`timeline_records`)."""
    return to_frame(timeline_records(taf, becmg=becmg, fill_temporary=fill_temporary))


def expand_hourly(timeline: pd.DataFrame) -> pd.DataFrame:
    """Expand a ``timeline`` frame to one row per whole hour in ``[start, end)``.

    During a BECMG transition in ``overlap`` mode, an hour has two prevailing
    rows (old and new state); filter on ``group_index`` if you need one.
    """
    df = timeline[timeline["start"].notna() & timeline["end"].notna()]
    if df.empty:
        out = df.iloc[0:0].copy()
        out.insert(0, "time", pd.Series(dtype="datetime64[ns]"))
        return out
    df = df.reset_index(drop=True)  # input may carry duplicate index labels
    first = list(df["start"].dt.floor("h"))
    seconds = (df["end"] - df["start"].dt.floor("h")).dt.total_seconds()
    hours = [max(math.ceil(s / 3600), 0) for s in seconds]
    positions = [k for k, n in enumerate(hours) for _ in range(n)]
    times = [first[k] + timedelta(hours=h) for k, n in enumerate(hours) for h in range(n)]
    out = df.iloc[positions].reset_index(drop=True)
    out.insert(0, "time", pd.to_datetime(pd.Series(times, dtype=object)))
    out = out.sort_values(["time", "prevailing", "group_index"], ascending=[True, False, True], kind="stable")
    return out.reset_index(drop=True)


def hourly_frame(taf: Taf, becmg: str = "overlap", fill_temporary: bool = True) -> pd.DataFrame:
    """The timeline expanded to one row per hour and active group."""
    return expand_hourly(timeline_frame(taf, becmg=becmg, fill_temporary=fill_temporary))


__all__ = [
    "apply_change",
    "columns",
    "expand_hourly",
    "group_records",
    "groups_frame",
    "hourly_frame",
    "timeline_frame",
    "timeline_records",
    "to_frame",
]
