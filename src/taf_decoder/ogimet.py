"""Download and split TAF archives from the Ogimet database (https://www.ogimet.com).

Please respect Ogimet's usage limits and credit the Ogimet database when you
publish results based on its data.
"""

from __future__ import annotations

import calendar
import os
import re
import time
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, List, Optional, Union
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

from .parser import RE_STATION

OGIMET_URL = "https://www.ogimet.com/display_metars2.php"
USER_AGENT = "taf-decoder (+https://github.com/Sladekd/Terminal-Forecast-Python-Processing)"

RE_STAMP = re.compile(r"(?<!\d)(\d{12})(?=\s)")


class OgimetError(RuntimeError):
    """Raised when Ogimet refuses a request or returns no usable data."""


def _stations(stations: Union[str, Iterable[str]]) -> List[str]:
    if isinstance(stations, str):
        stations = re.split(r"[\s,;]+", stations)
    out = [s.strip().upper() for s in stations if s and s.strip()]
    if not out:
        raise ValueError("At least one ICAO station code is required")
    bad = [s for s in out if not RE_STATION.match(s)]
    if bad:
        raise ValueError(f"Invalid ICAO station code(s): {', '.join(bad)}")
    return out


def ogimet_url(
    stations: Union[str, Iterable[str]],
    year: int,
    month: int,
    report_type: str = "FT",
) -> str:
    """URL of a one-month text query. ``report_type`` is ``FT`` (TAF) or ``SA`` (METAR)."""
    year, month = int(year), int(month)
    if not 1 <= month <= 12:
        raise ValueError(f"month must be 1-12, got {month}")
    if not 1900 <= year <= 2100:
        raise ValueError(f"year out of range: {year}")
    last_day = calendar.monthrange(year, month)[1]
    params = {
        "lang": "en",
        "lugar": ",".join(_stations(stations)),
        "tipo": report_type,
        "ord": "DIR",
        "nil": "SI",
        "fmt": "txt",
        "ano": year,
        "mes": f"{month:02d}",
        "day": "01",
        "hora": "00",
        "anof": year,
        "mesf": f"{month:02d}",
        "dayf": f"{last_day:02d}",
        "horaf": "23",
        "minf": "59",
        "send": "send",
    }
    return f"{OGIMET_URL}?{urlencode(params)}"


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: List[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(content: str) -> str:
    """Strip HTML tags (Ogimet wraps its text output in a minimal page)."""
    if "<" not in content:
        return content
    parser = _TextExtractor()
    parser.feed(content)
    parser.close()
    return "".join(parser.parts)


def download_ogimet(
    stations: Union[str, Iterable[str]],
    year: int,
    month: int,
    save_dir: Union[str, os.PathLike, None] = None,
    *,
    report_type: str = "FT",
    timeout: float = 60.0,
    retries: int = 3,
    backoff: float = 10.0,
    opener=None,
) -> str:
    """Download one month of TAFs for ``stations`` and return the text.

    With ``save_dir`` the text is also written to ``TAF<YYYY><MM>.txt`` there
    (the naming used by the original notebooks). Transient network errors are
    retried ``retries`` times with an increasing delay. :class:`OgimetError` is
    raised when Ogimet reports a quota limit or returns no reports.
    """
    url = ogimet_url(stations, year, month, report_type)
    fetch = opener or (lambda req, t: urlopen(req, timeout=t))  # noqa: S310 - fixed https URL
    last_exc: Optional[BaseException] = None
    for attempt in range(retries + 1):
        try:
            with fetch(Request(url, headers={"User-Agent": USER_AGENT}), timeout) as resp:  # noqa: S310
                raw = resp.read()
                charset = resp.headers.get_content_charset() if hasattr(resp, "headers") else None
            text = html_to_text(raw.decode(charset or "utf-8", errors="replace"))
            break
        except HTTPError as exc:
            last_exc = exc
            if exc.code < 500 and exc.code != 429:
                raise OgimetError(f"Ogimet returned HTTP {exc.code} for {url}") from exc
        except (URLError, TimeoutError, ConnectionError) as exc:
            last_exc = exc
        if attempt < retries:
            time.sleep(backoff * (attempt + 1))
    else:
        raise OgimetError(f"Download failed after {retries + 1} attempts: {last_exc}") from last_exc

    lowered = text.lower()
    if "quota" in lowered and not RE_STAMP.search(text):
        raise OgimetError("Ogimet quota limit reached; wait before the next request")
    if not RE_STAMP.search(text):
        raise OgimetError(f"No reports found for {year}-{int(month):02d} ({url})")

    if save_dir is not None:
        path = Path(save_dir)
        path.mkdir(parents=True, exist_ok=True)
        prefix = "TAF" if report_type == "FT" else report_type
        (path / f"{prefix}{int(year)}{int(month):02d}.txt").write_text(text, encoding="utf-8")
    return text


def split_ogimet_text(text: str) -> List[str]:
    """Split an Ogimet text export into individual reports.

    Each returned string starts with its ``YYYYMMDDHHMM`` stamp and ends with
    ``=``. Comment lines (``#``) and text between reports are dropped.
    """
    starts = [m.start() for m in RE_STAMP.finditer(text)]
    reports = []
    for k, pos in enumerate(starts):
        chunk = text[pos : starts[k + 1] if k + 1 < len(starts) else len(text)]
        if "=" in chunk:
            chunk = chunk[: chunk.index("=") + 1]
        else:
            chunk = "\n".join(line for line in chunk.splitlines() if not line.lstrip().startswith("#"))
        chunk = " ".join(chunk.split())
        if len(chunk) > 13:
            reports.append(chunk)
    return reports


def split_reports(text: str) -> List[str]:
    """Split free text into reports: Ogimet stamps if present, otherwise ``=`` or lines."""
    if RE_STAMP.search(text):
        return split_ogimet_text(text)
    if "=" in text:
        parts = [p.strip() + "=" for p in text.split("=")]
        return [" ".join(p.split()) for p in parts if p.strip("= \n\r\t")]
    return [" ".join(line.split()) for line in text.splitlines() if line.strip()]


def read_ogimet_file(path: Union[str, os.PathLike], encoding: str = "utf-8") -> pd.DataFrame:
    """Read an Ogimet text export into a DataFrame with ``report_time`` and ``taf`` columns.

    Pass the ``taf`` column to :func:`taf_decoder.decode_many`.
    """
    text = Path(path).read_text(encoding=encoding, errors="replace")
    reports = split_ogimet_text(text)
    times = pd.to_datetime([r[:12] for r in reports], format="%Y%m%d%H%M", errors="coerce")
    return pd.DataFrame({"report_time": times, "taf": reports})


# Backwards-compatible name used in the original notebook
def clean_taf_ogimet_file(file_path: Union[str, os.PathLike]) -> pd.DataFrame:
    """Deprecated alias of :func:`read_ogimet_file` (column ``TAF Forecast``)."""
    df = read_ogimet_file(file_path)
    return pd.DataFrame({"TAF Forecast": df["taf"]})
