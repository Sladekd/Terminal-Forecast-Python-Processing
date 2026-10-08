"""High-level helpers: decode one or many TAFs straight into DataFrames."""

from __future__ import annotations

import warnings as _warnings
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd

from . import frames
from .models import Taf, TafDecodeError
from .parser import ReferenceTime, decode_taf

KINDS = ("groups", "timeline", "hourly")


def _records(taf: Taf, kind: str, becmg: str, fill_temporary: bool) -> List[Dict[str, Any]]:
    if kind == "groups":
        return frames.group_records(taf)
    return frames.timeline_records(taf, becmg=becmg, fill_temporary=fill_temporary)


def taf_to_dataframe(
    text: str,
    kind: str = "timeline",
    reference_time: ReferenceTime = None,
    strict: bool = False,
    becmg: str = "overlap",
    fill_temporary: bool = True,
) -> pd.DataFrame:
    """Decode one TAF and return it as a DataFrame (see :mod:`taf_decoder.frames`)."""
    return decode_many(
        [text],
        kind=kind,
        reference_time=reference_time,
        strict=strict,
        becmg=becmg,
        fill_temporary=fill_temporary,
        errors="raise",
        index=False,
    )


def decode_many(
    tafs: Iterable[str],
    kind: str = "groups",
    reference_time: ReferenceTime = None,
    errors: str = "coerce",
    strict: bool = False,
    becmg: str = "overlap",
    fill_temporary: bool = True,
    index: bool = True,
) -> pd.DataFrame:
    """Decode many TAFs into one DataFrame.

    Parameters
    ----------
    tafs:
        Iterable of TAF strings (a list, a pandas Series, ...).
    kind:
        ``"groups"``, ``"timeline"`` or ``"hourly"``.
    errors:
        ``"coerce"`` (default) keeps going and records the message in the
        ``error`` column; ``"ignore"`` skips undecodable TAFs; ``"raise"``
        re-raises the first :class:`TafDecodeError`.
    index:
        Add ``taf_index`` (position of the TAF in the input), ``warnings`` and
        ``error`` columns.

    Other parameters are passed to :func:`decode_taf` and the frame builders.
    """
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, got {kind!r}")
    if errors not in ("coerce", "ignore", "raise"):
        raise ValueError(f"errors must be 'coerce', 'ignore' or 'raise', got {errors!r}")
    if becmg not in frames.BECMG_MODES:
        raise ValueError(f"becmg must be one of {frames.BECMG_MODES}, got {becmg!r}")
    if isinstance(tafs, str):
        tafs = [tafs]

    records: List[Dict[str, Any]] = []
    for pos, text in enumerate(tafs):
        try:
            if text is None or (isinstance(text, float) and pd.isna(text)):
                raise TafDecodeError("Missing value")
            taf = decode_taf(str(text), reference_time=reference_time, strict=strict)
            recs = _records(taf, kind, becmg, fill_temporary)
            warn = "; ".join(taf.warnings) or None
            err: Optional[str] = None
        except TafDecodeError as exc:
            if errors == "raise":
                raise
            if errors == "ignore":
                continue
            recs, warn, err = [{}], None, str(exc)
        except Exception as exc:  # pragma: no cover - defensive, should not happen
            if errors == "raise":
                raise
            if errors == "ignore":
                continue
            recs, warn, err = [{}], None, f"{type(exc).__name__}: {exc}"
        if index:
            for r in recs:
                r["taf_index"] = pos
                r["warnings"] = warn
                r["error"] = err
        records.extend(recs)

    front = ("taf_index",) if index else ()
    df = frames.to_frame(records, extra_front=front)
    if index:
        df["taf_index"] = df["taf_index"].astype("Int64")
        for c in ("warnings", "error"):
            if c not in df.columns:
                df[c] = pd.Series(dtype=object)
        cols = [c for c in df.columns if c not in ("warnings", "error")] + ["warnings", "error"]
        df = df[cols]
    if kind == "hourly":
        hourly = frames.expand_hourly(df)
        if index:
            failed = df[df["error"].notna()].copy()  # keep failures visible
            if not failed.empty:
                failed.insert(0, "time", pd.NaT)
                hourly = pd.concat([hourly, failed[hourly.columns]], ignore_index=True)
            hourly = hourly.sort_values(["taf_index", "time"], kind="stable")
        df = hourly.reset_index(drop=True)
    return df


def process_taf_to_df(sampl_TAF: str, reference_time: ReferenceTime = None) -> pd.DataFrame:  # noqa: N803
    """Deprecated: use :func:`taf_to_dataframe` (``kind="timeline"``).

    Kept so code written for the original notebooks keeps running. Column names
    follow the new, documented schema (``start``/``end`` instead of
    ``st_date``/``end_date``, ``wind_speed`` instead of ``spd``, ...).
    """
    _warnings.warn(
        "process_taf_to_df is deprecated; use taf_to_dataframe(text, kind='timeline')",
        DeprecationWarning,
        stacklevel=2,
    )
    return taf_to_dataframe(sampl_TAF, kind="timeline", reference_time=reference_time)
