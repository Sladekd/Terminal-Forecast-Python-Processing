"""Token-based TAF parser.

The parser never silently drops information: every token is either decoded or
kept in ``Group.unparsed``. Day/hour fields are turned into full datetimes by
choosing the calendar month closest to a reference time, so forecasts that
cross a month or year boundary (``3118/0124``) and ``24`` hour notation
(``0306/0324``) are handled correctly.
"""

from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence, Tuple, Union

from .models import Cloud, Group, Taf, TafDecodeError, Wind

ReferenceTime = Union[datetime, date, str, None]

# --------------------------------------------------------------------------- regexes
RE_PREFIX = re.compile(r"^(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})$")  # Ogimet YYYYMMDDHHMM
RE_STATION = re.compile(r"^[A-Z][A-Z0-9]{3}$")
RE_ISSUE = re.compile(r"^(\d{2})(\d{2})(\d{2})Z$")
RE_PERIOD = re.compile(r"^(\d{2})(\d{2})/(\d{2})(\d{2})$")
RE_PERIOD_LEGACY = re.compile(r"^(\d{2})(\d{2})(\d{2})$")  # pre-2008 DDHHHH
RE_PROB = re.compile(r"^PROB(\d{2})$")
RE_FM = re.compile(r"^FM(\d{2})(\d{2})(\d{2})$")
RE_SIXDIGITS = re.compile(r"^(\d{2})(\d{2})(\d{2})$")

RE_WIND = re.compile(r"^(\d{3}|VRB)(\d{2,3})(?:G(\d{2,3}))?(KT|MPS|KMH)$")
RE_WIND_VAR = re.compile(r"^(\d{3})V(\d{3})$")
RE_VIS = re.compile(r"^(\d{4})(NDV)?$")
RE_VIS_DIR = re.compile(r"^(\d{4})(N|NE|E|SE|S|SW|W|NW)$")
RE_VIS_SM = re.compile(r"^([PM])?(?:(\d{1,2})|(\d{1,2})/(\d{1,2}))SM$")
RE_WHOLE = re.compile(r"^\d$")
RE_CLOUD = re.compile(r"^(FEW|SCT|BKN|OVC)(\d{3}|///)(CB|TCU|///)?$")
RE_VV = re.compile(r"^VV(\d{3}|///)$")
RE_TEMP = re.compile(r"^(TX|TN)(M)?(\d{1,2})/(\d{2})(\d{2})Z$")
RE_WEATHER = re.compile(
    r"^(?P<int>[-+]|VC)?"
    r"(?P<desc>MI|PR|BC|DR|BL|SH|TS|FZ)?"
    r"(?P<phen>(?:DZ|RA|SN|SG|IC|PL|GR|GS|UP|BR|FG|FU|VA|DU|SA|HZ|PY|PO|SQ|FC|SS|DS)*)$"
)

NO_CLOUD_TOKENS = {"NSC", "SKC", "NCD", "CLR"}
HEADER_WORDS = {"TAF", "AMD", "COR", "RTD"}
SM_TO_M = 1609.344


# ------------------------------------------------------------------ time resolution
def _shift_month(year: int, month: int, delta: int) -> Tuple[int, int]:
    m = month - 1 + delta
    return year + m // 12, m % 12 + 1


def resolve_time(
    day: int,
    hour: int,
    minute: int,
    anchor: datetime,
    not_before: Optional[datetime] = None,
) -> datetime:
    """Turn a day/hour/minute triple into a datetime close to ``anchor``.

    The previous, current and next month of ``anchor`` are tried and the
    candidate nearest to ``anchor`` wins. Hour ``24`` means midnight at the end
    of ``day``. With ``not_before``, earlier candidates are discarded.
    """
    candidates = []
    for delta in (-1, 0, 1):
        y, m = _shift_month(anchor.year, anchor.month, delta)
        if not 1 <= day <= calendar.monthrange(y, m)[1]:
            continue
        if hour == 24 and minute == 0:
            candidates.append(datetime(y, m, day) + timedelta(days=1))
        elif 0 <= hour <= 23 and 0 <= minute <= 59:
            candidates.append(datetime(y, m, day, hour, minute))
    if not_before is not None:
        candidates = [c for c in candidates if c >= not_before]
    if not candidates:
        raise TafDecodeError(f"Invalid day/time {day:02d}{hour:02d}{minute:02d} near {anchor:%Y-%m-%d}")
    return min(candidates, key=lambda c: abs(c - anchor))


def _stamp_to_datetime(m: re.Match[str]) -> datetime:
    year, month, day, hour, minute = (int(x) for x in m.groups())
    return datetime(year, month, day, hour, minute)


def _to_reference(reference_time: ReferenceTime) -> Optional[datetime]:
    if reference_time is None:
        return None
    if isinstance(reference_time, datetime):
        if reference_time.tzinfo is not None:
            reference_time = reference_time.astimezone(timezone.utc).replace(tzinfo=None)
        return reference_time
    if isinstance(reference_time, date):
        return datetime(reference_time.year, reference_time.month, reference_time.day)
    if isinstance(reference_time, str):
        text = reference_time.strip()
        m = RE_PREFIX.match(text)
        if m:
            return _stamp_to_datetime(m)
        try:
            return _to_reference(datetime.fromisoformat(text))
        except ValueError:
            pass
    # pandas.Timestamp and similar objects
    to_py = getattr(reference_time, "to_pydatetime", None)
    if callable(to_py):
        return _to_reference(to_py())
    raise TypeError(f"Unsupported reference_time: {reference_time!r}")


# ------------------------------------------------------------------- normalisation
def normalize(text: str) -> Tuple[str, List[str]]:
    """Clean raw text and return it with any warnings produced while cleaning."""
    if not isinstance(text, str):
        raise TafDecodeError(f"TAF must be a string, got {type(text).__name__}")
    warnings: List[str] = []
    # literal escape sequences appear in CSV exports
    text = text.replace("\\r", " ").replace("\\n", " ").replace("\\t", " ")
    text = " ".join(text.upper().split())
    if "=" in text:
        head, _, tail = text.partition("=")
        if tail.strip():
            warnings.append(f"Text after '=' ignored: {tail.strip()[:60]!r}")
        text = head.strip()
    return text, warnings


# ------------------------------------------------------------------ element parser
def _sm_to_m(miles: float) -> int:
    return round(miles * SM_TO_M)


def _parse_elements(tokens: Sequence[str], anchor: Optional[datetime], warnings: List[str]) -> Dict:
    """Decode the weather elements of one group body."""
    out: Dict = {
        "wind": None,
        "visibility_m": None,
        "visibility_raw": None,
        "cavok": False,
        "weather": [],
        "nsw": False,
        "clouds": [],
        "no_clouds": False,
        "max_temp_c": None,
        "max_temp_time": None,
        "min_temp_c": None,
        "min_temp_time": None,
        "unparsed": [],
    }
    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        m = RE_WIND.match(tok)
        if m and out["wind"] is None:
            direction, speed, gust, unit = m.groups()
            var_from = var_to = None
            if i + 1 < n:
                mv = RE_WIND_VAR.match(tokens[i + 1])
                if mv:
                    var_from, var_to = int(mv.group(1)), int(mv.group(2))
                    i += 1
            d = None if direction == "VRB" else int(direction)
            if d is not None and d > 360:
                warnings.append(f"Wind direction out of range: {tok}")
            out["wind"] = Wind(
                direction=d,
                speed=int(speed),
                gust=int(gust) if gust else None,
                unit=unit,
                variable=direction == "VRB",
                variable_from=var_from,
                variable_to=var_to,
            )
            i += 1
            continue
        if tok == "CAVOK":
            out["cavok"] = True
            out["visibility_m"] = 10000
            out["visibility_raw"] = "CAVOK"
            i += 1
            continue
        m = RE_VIS.match(tok)
        if m and out["visibility_m"] is None:
            out["visibility_m"] = int(m.group(1))
            out["visibility_raw"] = tok
            i += 1
            continue
        m = RE_VIS_DIR.match(tok)
        if m:
            if out["visibility_m"] is None:
                out["visibility_m"] = int(m.group(1))
                out["visibility_raw"] = tok
            else:
                out["visibility_raw"] = f"{out['visibility_raw']} {tok}"
            i += 1
            continue
        # US statute miles, incl. two-token form "1 1/2SM"
        if RE_WHOLE.match(tok) and i + 1 < n:
            mf = RE_VIS_SM.match(tokens[i + 1])
            if mf and mf.group(3) and out["visibility_m"] is None:
                miles = int(tok) + int(mf.group(3)) / int(mf.group(4))
                out["visibility_m"] = _sm_to_m(miles)
                out["visibility_raw"] = f"{tok} {tokens[i + 1]}"
                i += 2
                continue
        m = RE_VIS_SM.match(tok)
        if m and out["visibility_m"] is None:
            if m.group(2):
                miles = float(m.group(2))
            elif int(m.group(4)) == 0:
                out["unparsed"].append(tok)
                i += 1
                continue
            else:
                miles = int(m.group(3)) / int(m.group(4))
            out["visibility_m"] = _sm_to_m(miles)
            out["visibility_raw"] = tok
            i += 1
            continue
        if tok == "NSW":
            out["nsw"] = True
            i += 1
            continue
        if tok in NO_CLOUD_TOKENS:
            out["no_clouds"] = True
            i += 1
            continue
        m = RE_CLOUD.match(tok)
        if m:
            cover, height, ctype = m.groups()
            out["clouds"].append(
                Cloud(
                    cover=cover,
                    height_ft=None if height == "///" else int(height) * 100,
                    type=None if ctype in (None, "///") else ctype,
                )
            )
            i += 1
            continue
        m = RE_VV.match(tok)
        if m:
            h = m.group(1)
            out["clouds"].append(Cloud("VV", None if h == "///" else int(h) * 100))
            i += 1
            continue
        m = RE_TEMP.match(tok)
        if m:
            kind, minus, value, day, hour = m.groups()
            temp = -int(value) if minus else int(value)
            when = None
            if anchor is not None:
                try:
                    when = resolve_time(int(day), int(hour), 0, anchor)
                except TafDecodeError as exc:
                    warnings.append(str(exc))
            key = "max" if kind == "TX" else "min"
            out[f"{key}_temp_c"] = temp
            out[f"{key}_temp_time"] = when
            i += 1
            continue
        m = RE_WEATHER.match(tok)
        if m and (m.group("desc") or m.group("phen")):
            out["weather"].append(tok)
            i += 1
            continue
        out["unparsed"].append(tok)
        i += 1
    return out


# ------------------------------------------------------------------ group splitting
def _split_groups(tokens: List[str]) -> List[Tuple[str, Optional[int], Optional[str], List[str]]]:
    """Split body tokens into (change, probability, time_token, element_tokens)."""
    groups: List[Tuple[str, Optional[int], Optional[str], List[str]]] = []
    current: Tuple[str, Optional[int], Optional[str], List[str]] = ("BASE", None, None, [])
    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        change = prob = time_tok = None
        consumed = 0
        mp = RE_PROB.match(tok)
        if tok in ("BECMG", "TEMPO", "INTER"):
            change, consumed = tok, 1
        elif mp:
            prob = int(mp.group(1))
            if i + 1 < n and tokens[i + 1] in ("TEMPO", "INTER"):
                change, consumed = tokens[i + 1], 2
            else:
                change, consumed = "PROB", 1
        elif RE_FM.match(tok):
            change, time_tok, consumed = "FM", tok[2:], 1
        elif tok == "FM" and i + 1 < n and RE_SIXDIGITS.match(tokens[i + 1]):
            change, time_tok, consumed = "FM", tokens[i + 1], 2

        if change is None:
            current[3].append(tok)
            i += 1
            continue

        groups.append(current)
        i += consumed
        if change != "FM" and i < n and RE_PERIOD.match(tokens[i]):
            time_tok = tokens[i]
            i += 1
        current = (change, prob, time_tok, [])
    groups.append(current)
    return groups


# ------------------------------------------------------------------ public decoder
def decode_taf(
    text: str,
    reference_time: ReferenceTime = None,
    strict: bool = False,
) -> Taf:
    """Decode one TAF report.

    Parameters
    ----------
    text:
        The TAF. An optional leading ``YYYYMMDDHHMM`` stamp (as in Ogimet
        exports) is used to determine the year and month.
    reference_time:
        Any time near the issue time (``datetime``, ``date``, ISO string or
        ``YYYYMMDDHHMM``). Used when the text carries no ``YYYYMMDDHHMM``
        stamp. Defaults to the current UTC time.
    strict:
        If true, raise :class:`TafDecodeError` when any token cannot be decoded
        or any warning is produced, instead of recording it.
    """
    cleaned, warnings = normalize(text)
    tokens = cleaned.split()
    if not tokens:
        raise TafDecodeError("Empty TAF")
    i = 0

    # --- optional Ogimet stamp
    stamp: Optional[datetime] = None
    m = RE_PREFIX.match(tokens[0])
    if m:
        try:
            stamp = _stamp_to_datetime(m)
        except ValueError:
            warnings.append(f"Invalid date stamp ignored: {tokens[0]}")
        i += 1

    anchor = stamp or _to_reference(reference_time)
    if anchor is None:
        anchor = datetime.now(timezone.utc).replace(tzinfo=None)

    # --- TAF / AMD / COR / RTD
    amendment = correction = False
    while i < len(tokens) and tokens[i] in HEADER_WORDS:
        amendment |= tokens[i] == "AMD"
        correction |= tokens[i] == "COR"
        i += 1

    # --- station
    if i >= len(tokens) or not RE_STATION.match(tokens[i]):
        found = tokens[i] if i < len(tokens) else "end of text"
        raise TafDecodeError(f"Expected ICAO station identifier, found {found!r}")
    station = tokens[i]
    i += 1

    # --- issue time
    issue_time: Optional[datetime] = None
    if i < len(tokens):
        m = RE_ISSUE.match(tokens[i])
        if m:
            day, hour, minute = (int(x) for x in m.groups())
            issue_time = resolve_time(day, hour, minute, anchor=anchor)
            i += 1
        else:
            warnings.append("Issue time (DDHHMMZ) missing")
    period_anchor = issue_time or anchor

    taf = Taf(
        raw=cleaned,
        station=station,
        issue_time=issue_time,
        valid_from=None,
        valid_to=None,
        amendment=amendment,
        correction=correction,
        warnings=warnings,
    )

    if i < len(tokens) and tokens[i] == "NIL":
        taf.nil = True
        if i + 1 < len(tokens):
            warnings.append(f"Text after NIL ignored: {' '.join(tokens[i + 1 :])!r}")
        return _finish(taf, strict)

    if i < len(tokens) and tokens[i] == "AUTO":
        taf.auto = True
        i += 1

    # --- validity period
    if i >= len(tokens):
        raise TafDecodeError("Validity period missing")
    m = RE_PERIOD.match(tokens[i])
    m_legacy = RE_PERIOD_LEGACY.match(tokens[i])
    if m:
        d1, h1, d2, h2 = map(int, m.groups())
    elif m_legacy:
        d1, h1, h2 = map(int, m_legacy.groups())
        d2 = d1 if h2 > h1 else d1 + 1
        warnings.append("Legacy DDHHHH validity format")
    else:
        raise TafDecodeError(f"Expected validity period DDHH/DDHH, found {tokens[i]!r}")
    i += 1
    taf.valid_from = resolve_time(d1, h1, 0, anchor=period_anchor)
    if m_legacy and not m:
        # legacy end day is implied; roll forward from the start
        taf.valid_to = taf.valid_from + timedelta(hours=(h2 - h1) % 24 or 24)
    else:
        taf.valid_to = resolve_time(d2, h2, 0, anchor=taf.valid_from, not_before=taf.valid_from)
    if taf.valid_to - taf.valid_from > timedelta(hours=36):
        warnings.append("Validity period longer than 36 hours")

    rest = tokens[i:]
    if rest and rest[0] == "CNL":
        taf.cancelled = True
        return _finish(taf, strict)
    if "RMK" in rest:
        k = rest.index("RMK")
        taf.remarks = " ".join(rest[k + 1 :]) or None
        rest = rest[:k]

    taf.groups = _build_groups(rest, taf, warnings)
    return _finish(taf, strict)


def _build_groups(tokens: List[str], taf: Taf, warnings: List[str]) -> List[Group]:
    assert taf.valid_from is not None and taf.valid_to is not None
    raw_groups = _split_groups(tokens)
    built = []
    for change, prob, time_tok, body in raw_groups:
        start: Optional[datetime]
        end: Optional[datetime]
        if change == "BASE":
            start, end = taf.valid_from, taf.valid_to
            raw_head = ""
        elif change == "FM":
            assert time_tok is not None
            d, h, mi = map(int, RE_SIXDIGITS.match(time_tok).groups())  # type: ignore[union-attr]
            try:
                start = resolve_time(d, h, mi, anchor=taf.valid_from)
            except TafDecodeError as exc:
                warnings.append(f"FM{time_tok}: {exc}")
                start = None
            end = None  # filled below
            raw_head = f"FM{time_tok}"
        else:
            raw_head = " ".join(
                x
                for x in (
                    f"PROB{prob}" if prob is not None else None,
                    change if change != "PROB" else None,
                    time_tok,
                )
                if x
            )
            if time_tok is None:
                warnings.append(f"{raw_head} group without period; using whole validity")
                start, end = taf.valid_from, taf.valid_to
            else:
                d1, h1, d2, h2 = map(int, RE_PERIOD.match(time_tok).groups())  # type: ignore[union-attr]
                try:
                    start = resolve_time(d1, h1, 0, anchor=taf.valid_from)
                    end = resolve_time(d2, h2, 0, anchor=start, not_before=start)
                except TafDecodeError as exc:
                    warnings.append(f"{raw_head}: {exc}")
                    start = end = None

        if not body and change != "BASE":
            warnings.append(f"Empty group {raw_head!r}")

        el = _parse_elements(body, taf.valid_from, warnings)
        if el["unparsed"]:
            warnings.append(f"Unparsed tokens in {raw_head or 'base'}: {' '.join(el['unparsed'])}")
        for t in (start, end):
            if t is not None and not (taf.valid_from <= t <= taf.valid_to):
                warnings.append(f"{raw_head or 'base'} time {t:%d%H%M} outside validity period")
                break
        built.append(
            Group(
                change=change,
                probability=prob,
                start=start,
                end=end,
                wind=el["wind"],
                visibility_m=el["visibility_m"],
                visibility_raw=el["visibility_raw"],
                cavok=el["cavok"],
                weather=tuple(el["weather"]),
                nsw=el["nsw"],
                clouds=tuple(el["clouds"]),
                no_clouds=el["no_clouds"],
                max_temp_c=el["max_temp_c"],
                max_temp_time=el["max_temp_time"],
                min_temp_c=el["min_temp_c"],
                min_temp_time=el["min_temp_time"],
                raw=" ".join(x for x in (raw_head, " ".join(body)) if x),
                unparsed=tuple(el["unparsed"]),
            )
        )

    # FM groups last until the next FM group or the end of validity
    fm_idx = [k for k, g in enumerate(built) if g.change == "FM"]
    for pos, k in enumerate(fm_idx):
        nxt = built[fm_idx[pos + 1]].start if pos + 1 < len(fm_idx) else taf.valid_to
        built[k] = _replace(built[k], end=nxt)
    return built


def _replace(group: Group, **changes) -> Group:
    from dataclasses import replace

    return replace(group, **changes)


def _finish(taf: Taf, strict: bool) -> Taf:
    if strict and taf.warnings:
        raise TafDecodeError("; ".join(taf.warnings))
    return taf
