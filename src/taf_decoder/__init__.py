"""taf-decoder: decode aviation TAF (Terminal Aerodrome Forecast) reports into pandas.

Quick start::

    from taf_decoder import decode_taf, taf_to_dataframe

    taf = decode_taf("202308030500 TAF LKTB 030500Z 0306/0406 17007KT 9999 SCT025 "
                     "TEMPO 0306/0309 19013KT RA BKN025 BECMG 0322/0400 VRB02KT=")
    df = taf.to_dataframe("timeline")
"""

from __future__ import annotations

try:
    from importlib.metadata import PackageNotFoundError, version

    __version__ = version("taf-decoder")
except PackageNotFoundError:  # pragma: no cover - running from a source checkout
    __version__ = "0.0.0+unknown"

from .api import decode_many, process_taf_to_df, taf_to_dataframe
from .frames import apply_change, expand_hourly
from .models import Cloud, Group, Taf, TafDecodeError, Wind
from .ogimet import (
    OgimetError,
    clean_taf_ogimet_file,
    download_ogimet,
    ogimet_url,
    read_ogimet_file,
    split_ogimet_text,
    split_reports,
)
from .parser import decode_taf, resolve_time


def plot_wind(*args, **kwargs):
    """Plot hourly wind speed; see :func:`taf_decoder.plot.plot_wind` (needs matplotlib)."""
    from .plot import plot_wind as _plot_wind

    return _plot_wind(*args, **kwargs)


__all__ = [
    "Cloud",
    "Group",
    "OgimetError",
    "Taf",
    "TafDecodeError",
    "Wind",
    "__version__",
    "apply_change",
    "clean_taf_ogimet_file",
    "decode_many",
    "decode_taf",
    "download_ogimet",
    "expand_hourly",
    "ogimet_url",
    "plot_wind",
    "process_taf_to_df",
    "read_ogimet_file",
    "resolve_time",
    "split_ogimet_text",
    "split_reports",
    "taf_to_dataframe",
]
