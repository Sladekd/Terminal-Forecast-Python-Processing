"""Property-based tests: the decoder must never fail with anything but TafDecodeError."""

from datetime import datetime, timedelta

import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import HealthCheck, given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from taf_decoder import TafDecodeError, decode_many, decode_taf, resolve_time  # noqa: E402
from taf_decoder.frames import group_records, timeline_records  # noqa: E402

SETTINGS = settings(max_examples=400, deadline=None, suppress_health_check=[HealthCheck.too_slow])

TOKENS = [
    "BECMG",
    "TEMPO",
    "PROB30",
    "PROB40",
    "INTER",
    "FM031200",
    "FM",
    "031200",
    "0310/0312",
    "0322/0324",
    "3123/0101",
    "17007KT",
    "VRB02KT",
    "25025G40KT",
    "140V200",
    "24008MPS",
    "9999",
    "4000",
    "0800",
    "CAVOK",
    "P6SM",
    "1",
    "1/2SM",
    "-RA",
    "+TSRA",
    "BR",
    "NSW",
    "FEW010",
    "BKN030CB",
    "OVC///",
    "VV001",
    "NSC",
    "SKC",
    "TX25/0314Z",
    "TNM02/0404Z",
    "RMK",
    "CNL",
    "NIL",
    "=",
    "AUTO",
    "AMD",
    "FOO",
    "//",
    "0000",
    "9999NDV",
    "M1/4SM",
    "1500SW",
    "24",
    "",
]


@SETTINGS
@given(st.text(max_size=200))
def test_arbitrary_text(text):
    try:
        decode_taf(text, reference_time="2023-08-03")
    except TafDecodeError:
        pass


@SETTINGS
@given(st.lists(st.sampled_from(TOKENS), max_size=30))
def test_token_soup_after_valid_header(tokens):
    text = "TAF LKTB 030500Z 0306/0406 " + " ".join(tokens)
    try:
        taf = decode_taf(text, reference_time="2023-08-03")
    except TafDecodeError:
        return
    for mode in ("overlap", "start", "end"):
        timeline_records(taf, becmg=mode)
    group_records(taf)
    taf.to_dataframe("hourly")


@SETTINGS
@given(st.lists(st.sampled_from(TOKENS), max_size=25), st.booleans())
def test_header_soup(tokens, stamp):
    text = ("202308030500 " if stamp else "") + " ".join(tokens)
    try:
        decode_taf(text, reference_time="2023-08-03")
    except TafDecodeError:
        pass


@SETTINGS
@given(
    st.datetimes(min_value=datetime(1990, 1, 1), max_value=datetime(2090, 12, 31)),
    st.integers(-13, 13),
)
def test_resolve_time_roundtrip(anchor, hours):
    """A time within ±13 h of the anchor is always recovered from day/hour/minute."""
    target = (anchor + timedelta(hours=hours)).replace(second=0, microsecond=0)
    assert resolve_time(target.day, target.hour, target.minute, anchor) == target


@settings(max_examples=50, deadline=None)
@given(st.lists(st.one_of(st.none(), st.text(max_size=80)), max_size=10))
def test_decode_many_never_raises(items):
    df = decode_many(items, reference_time="2023-08-03")
    if items:
        assert df["taf_index"].nunique() == len(items)
