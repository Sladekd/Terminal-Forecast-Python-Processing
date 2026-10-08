"""Hourly wind-speed plot (requires ``pip install taf-decoder[plot]``)."""

from __future__ import annotations

import os
from typing import Optional, Union

import pandas as pd

from .models import Taf

PREVAILING_MARKER = "o"
TEMPORARY_MARKER = "^"
GUST_MARKER = "x"


def _hourly(data, becmg: str) -> pd.DataFrame:
    from . import frames
    from .parser import decode_taf

    if isinstance(data, str):
        data = decode_taf(data)
    if isinstance(data, Taf):
        return frames.hourly_frame(data, becmg=becmg)
    if isinstance(data, pd.DataFrame):
        if "time" in data.columns:
            return data
        if {"start", "end"}.issubset(data.columns):
            return frames.expand_hourly(data)
    raise TypeError("data must be a TAF string, a Taf, or a timeline/hourly DataFrame")


def plot_wind(
    data: Union[str, Taf, pd.DataFrame],
    ax=None,
    gusts: bool = True,
    temporary: bool = True,
    title: Optional[str] = None,
    save_path: Union[str, os.PathLike, None] = None,
    becmg: str = "overlap",
):
    """Plot hourly forecast wind speed (and gusts) in knots.

    Prevailing conditions are drawn as circles, TEMPO/PROB/INTER groups as
    triangles and gusts as crosses; each group gets its own colour. Returns the
    matplotlib ``Axes``. Nothing is saved unless ``save_path`` is given.
    """
    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise ImportError("plot_wind needs matplotlib: pip install 'taf-decoder[plot]'") from exc

    df = _hourly(data, becmg)
    if not temporary:
        df = df[df["prevailing"].fillna(False).astype(bool)]
    df = df[df["time"].notna()]
    if ax is None:
        _, ax = plt.subplots(figsize=(10, 4))
    if df.empty:
        ax.text(0.5, 0.5, "No wind data", ha="center", va="center", transform=ax.transAxes)
        return ax

    cmap = plt.get_cmap("viridis")
    groups = sorted(df["group_index"].dropna().unique())
    colours = {g: cmap(k / max(len(groups) - 1, 1)) for k, g in enumerate(groups)}
    speed = pd.to_numeric(df["wind_speed_kt"], errors="coerce").astype(float)
    gust = pd.to_numeric(df["wind_gust_kt"], errors="coerce").astype(float)
    prevailing = df["prevailing"].fillna(False).astype(bool)

    for g in groups:
        sel = df["group_index"] == g
        is_prev = bool(prevailing[sel].iloc[0])
        label_src = df.loc[sel].iloc[0]
        label = str(label_src["change"])
        if pd.notna(label_src["probability"]):
            prob = f"PROB{int(label_src['probability'])}"
            label = prob if label == "PROB" else f"{prob} {label}"
        ax.scatter(
            df.loc[sel, "time"],
            speed[sel],
            color=colours[g],
            marker=PREVAILING_MARKER if is_prev else TEMPORARY_MARKER,
            label=f"{label} ({g})",
            zorder=3,
        )
        if gusts and gust[sel].notna().any():
            ax.scatter(df.loc[sel, "time"], gust[sel], color=colours[g], marker=GUST_MARKER, zorder=3)

    if gusts and gust.notna().any():
        ax.scatter([], [], color="grey", marker=GUST_MARKER, label="gust")
    ax.set_xlabel("Time (UTC)")
    ax.set_ylabel("Wind speed [kt]")
    ax.grid(True, alpha=0.3)
    if title is None:
        station = df["station"].dropna()
        issued = df["issue_time"].dropna()
        title = "TAF wind forecast"
        if not station.empty:
            title += f" {station.iloc[0]}"
        if not issued.empty:
            title += f" issued {issued.iloc[0]:%Y-%m-%d %H:%MZ}"
    ax.set_title(title)
    ax.legend(fontsize="small", loc="best")
    ax.figure.autofmt_xdate()
    if save_path is not None:
        ax.figure.savefig(save_path, bbox_inches="tight")
    return ax
