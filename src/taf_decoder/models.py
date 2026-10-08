"""Data structures returned by the decoder.

All datetimes are naive and expressed in UTC (TAF times are always UTC).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Tuple

#: Conversion factors from a TAF wind unit to knots.
TO_KNOTS = {"KT": 1.0, "MPS": 1.943844, "KMH": 0.539957}

#: Numeric group codes used in the original notebooks / publication.
GROUP_CODES = {
    ("BASE", None): 0,
    ("TEMPO", None): 1,
    ("PROB", 30): 2,
    ("TEMPO", 30): 3,
    ("PROB", 40): 4,
    ("TEMPO", 40): 5,
    ("BECMG", None): 6,
    ("FM", None): 7,
    ("INTER", None): 8,
}


class TafDecodeError(ValueError):
    """Raised when a TAF cannot be decoded (or, in strict mode, fully decoded)."""


@dataclass(frozen=True)
class Wind:
    """Surface wind, e.g. ``25025G40KT`` or ``VRB03KT 180V240``."""

    direction: Optional[int]  # degrees true; None when variable (VRB)
    speed: int
    gust: Optional[int] = None
    unit: str = "KT"
    variable: bool = False
    variable_from: Optional[int] = None
    variable_to: Optional[int] = None

    @property
    def speed_kt(self) -> float:
        return round(self.speed * TO_KNOTS[self.unit], 1)

    @property
    def gust_kt(self) -> Optional[float]:
        if self.gust is None:
            return None
        return round(self.gust * TO_KNOTS[self.unit], 1)


@dataclass(frozen=True)
class Cloud:
    """One cloud layer, e.g. ``BKN030CB``. ``cover`` is FEW/SCT/BKN/OVC or VV."""

    cover: str
    height_ft: Optional[int]  # None when reported as ///
    type: Optional[str] = None  # CB, TCU or None


@dataclass(frozen=True)
class Group:
    """One forecast group: the base forecast or a BECMG/TEMPO/PROB/FM/INTER change."""

    change: str  # BASE, BECMG, TEMPO, PROB, FM, INTER
    start: Optional[datetime]
    end: Optional[datetime]
    probability: Optional[int] = None
    wind: Optional[Wind] = None
    visibility_m: Optional[int] = None
    visibility_raw: Optional[str] = None
    cavok: bool = False
    weather: Tuple[str, ...] = ()
    nsw: bool = False  # "no significant weather" - ends previously forecast weather
    clouds: Tuple[Cloud, ...] = ()
    no_clouds: bool = False  # NSC / SKC / NCD / CLR
    max_temp_c: Optional[int] = None
    max_temp_time: Optional[datetime] = None
    min_temp_c: Optional[int] = None
    min_temp_time: Optional[datetime] = None
    raw: str = ""
    unparsed: Tuple[str, ...] = ()

    @property
    def code(self) -> int:
        """Numeric group indicator as used in the original publication."""
        return GROUP_CODES.get((self.change, self.probability), -1)

    @property
    def label(self) -> str:
        """Human label, e.g. ``PROB30 TEMPO``."""
        if self.change == "PROB":
            return f"PROB{self.probability}"
        if self.probability is not None:
            return f"PROB{self.probability} {self.change}"
        return self.change

    @property
    def ceiling_ft(self) -> Optional[int]:
        """Height of the lowest BKN/OVC layer or vertical visibility."""
        heights = [
            c.height_ft for c in self.clouds if c.cover in ("BKN", "OVC", "VV") and c.height_ft is not None
        ]
        return min(heights) if heights else None


@dataclass
class Taf:
    """A decoded Terminal Aerodrome Forecast."""

    raw: str
    station: str
    issue_time: Optional[datetime]
    valid_from: Optional[datetime]
    valid_to: Optional[datetime]
    amendment: bool = False
    correction: bool = False
    auto: bool = False
    nil: bool = False
    cancelled: bool = False
    remarks: Optional[str] = None  # text after RMK, if any
    groups: list = field(default_factory=list)  # list[Group]
    warnings: list = field(default_factory=list)  # list[str]

    @property
    def base(self) -> Optional[Group]:
        return self.groups[0] if self.groups else None

    def to_dataframe(self, kind: str = "groups", **kwargs):
        """Return the TAF as a pandas DataFrame.

        ``kind`` is one of:

        * ``"groups"``   - one row per group exactly as forecast;
        * ``"timeline"`` - prevailing conditions after applying BECMG/FM changes,
          plus TEMPO/PROB/INTER rows (the representation used in the publication);
        * ``"hourly"``   - one row per hour and active group.

        Extra keyword arguments are passed to the corresponding builder in
        :mod:`taf_decoder.frames`.
        """
        from . import frames

        builders = {
            "groups": frames.groups_frame,
            "timeline": frames.timeline_frame,
            "hourly": frames.hourly_frame,
        }
        if kind not in builders:
            raise ValueError(f"kind must be one of {sorted(builders)}, got {kind!r}")
        return builders[kind](self, **kwargs)
