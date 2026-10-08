from datetime import date, datetime, timezone

import pytest
from conftest import TAF_KJFK, TAF_LFRS, TAF_LKTB

from taf_decoder import Cloud, TafDecodeError, Wind, decode_taf, resolve_time

REF = "2023-08-03"


def base(body, header="TAF LKTB 030500Z 0306/0406", ref=REF):
    return decode_taf(f"{header} {body}=", reference_time=ref).groups[0]


# ----------------------------------------------------------------------------- header
class TestHeader:
    def test_publication_example(self):
        t = decode_taf(TAF_LKTB)
        assert t.station == "LKTB"
        assert t.issue_time == datetime(2023, 8, 3, 5, 0)
        assert t.valid_from == datetime(2023, 8, 3, 6)
        assert t.valid_to == datetime(2023, 8, 4, 6)
        assert [g.change for g in t.groups] == ["BASE", "TEMPO", "BECMG"]
        assert t.warnings == []

    @pytest.mark.parametrize(
        "text, amd, cor",
        [
            ("TAF AMD LKTB 030500Z 0306/0406 17007KT=", True, False),
            ("TAF COR LKTB 030500Z 0306/0406 17007KT=", False, True),
            ("TAF LKTB 030500Z 0306/0406 17007KT=", False, False),
            ("LKTB 030500Z 0306/0406 17007KT=", False, False),
            ("TAF TAF AMD LKTB 030500Z 0306/0406 17007KT=", True, False),
        ],
    )
    def test_amd_cor_variants(self, text, amd, cor):
        t = decode_taf(text, reference_time=REF)
        assert (t.amendment, t.correction, t.station) == (amd, cor, "LKTB")

    def test_nil(self):
        t = decode_taf("202007011700 TAF EDDT 011700Z NIL=")
        assert t.nil and t.groups == [] and t.valid_from is None

    def test_cancelled(self):
        t = decode_taf("TAF AMD EDDT 011700Z 0118/0224 CNL=", reference_time="2020-07-01")
        assert t.cancelled and t.groups == []
        assert t.valid_to == datetime(2020, 7, 3, 0)  # 0224 = 24:00 on the 2nd

    def test_auto_and_remarks(self):
        t = decode_taf(
            "TAF CYYZ 030500Z AUTO 0306/0406 17007KT P6SM SKC RMK NXT FCST BY 12Z=",
            reference_time=REF,
        )
        assert t.auto
        assert t.remarks == "NXT FCST BY 12Z"
        assert t.groups[0].unparsed == ()

    def test_missing_issue_time_warns(self):
        t = decode_taf("TAF LKTB 0306/0406 17007KT=", reference_time=REF)
        assert t.issue_time is None
        assert t.valid_from == datetime(2023, 8, 3, 6)
        assert any("Issue time" in w for w in t.warnings)

    def test_legacy_validity(self):
        t = decode_taf("TAF LKTB 030500Z 030606 17007KT=", reference_time=REF)
        assert t.valid_from == datetime(2023, 8, 3, 6)
        assert t.valid_to == datetime(2023, 8, 4, 6)

    @pytest.mark.parametrize(
        "text, match",
        [
            ("", "Empty"),
            ("   ", "Empty"),
            ("TAF", "station"),
            ("TAF 12 030500Z", "station"),
            ("TAF LKTB 030500Z", "Validity"),
            ("TAF LKTB 030500Z 17007KT 9999", "validity"),
            ("TAF LKTB 030500Z 3206/3306 17007KT", "Invalid day"),
            ("TAF LKTB 030500Z 0325/0406 17007KT", "Invalid day"),
        ],
    )
    def test_errors(self, text, match):
        with pytest.raises(TafDecodeError, match=match):
            decode_taf(text, reference_time=REF)

    @pytest.mark.parametrize("bad", [None, 123, b"TAF LKTB"])
    def test_non_string(self, bad):
        with pytest.raises(TafDecodeError):
            decode_taf(bad)

    def test_literal_newlines_lowercase_and_extra_text(self):
        t = decode_taf(
            "taf lktb 030500z 0306/0406 17007kt\\n9999 sct025= TAF LKPR 030500Z",
            reference_time=REF,
        )
        assert t.groups[0].visibility_m == 9999
        assert any("after '='" in w for w in t.warnings)

    def test_strict(self):
        with pytest.raises(TafDecodeError, match="Unparsed"):
            decode_taf("TAF LKTB 030500Z 0306/0406 17007KT FOO=", reference_time=REF, strict=True)
        decode_taf(TAF_LKTB, strict=True)  # clean TAF passes


# ------------------------------------------------------------------------------ times
class TestTimes:
    def test_month_rollover(self):
        t = decode_taf("202308311700 TAF LKTB 311700Z 3118/0118 17007KT BECMG 0102/0104 CAVOK=")
        assert t.valid_to == datetime(2023, 9, 1, 18)
        assert t.groups[1].start == datetime(2023, 9, 1, 2)

    def test_year_rollover(self):
        t = decode_taf(TAF_KJFK, reference_time="2026-12-31")
        assert t.issue_time == datetime(2026, 12, 31, 23, 30)
        assert t.valid_from == datetime(2027, 1, 1, 0)
        assert t.groups[1].start == datetime(2027, 1, 1, 6)

    def test_hour_24(self):
        t = decode_taf("TAF LKTB 030500Z 0306/0324 17007KT BECMG 0322/0324 VRB02KT=", reference_time=REF)
        assert t.valid_to == datetime(2023, 8, 4, 0)
        assert t.groups[1].end == datetime(2023, 8, 4, 0)

    def test_stamp_in_next_month_than_issue(self):
        # report stamp just after midnight, issue time the previous evening
        t = decode_taf("202309010005 TAF LKTB 312355Z 0100/0124 17007KT=")
        assert t.issue_time == datetime(2023, 8, 31, 23, 55)

    def test_leap_day(self):
        t = decode_taf("TAF LKTB 282300Z 2900/0100 17007KT=", reference_time="2024-02-28")
        assert t.valid_from == datetime(2024, 2, 29)
        assert t.valid_to == datetime(2024, 3, 1)

    def test_day_31_with_30_day_reference_month(self):
        t = decode_taf("TAF LKTB 311700Z 3118/0118 17007KT=", reference_time="2023-09-02")
        assert t.valid_from == datetime(2023, 8, 31, 18)

    @pytest.mark.parametrize(
        "ref",
        [
            "2023-08-03",
            date(2023, 8, 3),
            datetime(2023, 8, 3, 12),
            "202308030500",
            datetime(2023, 8, 3, 14, tzinfo=timezone.utc),
        ],
    )
    def test_reference_time_types(self, ref):
        t = decode_taf("TAF LKTB 030500Z 0306/0406 17007KT=", reference_time=ref)
        assert t.valid_from == datetime(2023, 8, 3, 6)

    def test_reference_time_pandas(self):
        pd = pytest.importorskip("pandas")
        t = decode_taf("TAF LKTB 030500Z 0306/0406 17007KT=", reference_time=pd.Timestamp("2023-08-03"))
        assert t.valid_from.year == 2023

    def test_bad_reference_time(self):
        with pytest.raises(TypeError):
            decode_taf("TAF LKTB 030500Z 0306/0406 17007KT=", reference_time="not a date")

    def test_default_reference_is_now(self):
        t = decode_taf("TAF LKTB 030500Z 0306/0406 17007KT=")
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        assert abs((t.valid_from - now).days) <= 31

    def test_resolve_time_closest(self):
        anchor = datetime(2023, 1, 1, 0)
        assert resolve_time(31, 22, 0, anchor) == datetime(2022, 12, 31, 22)
        assert resolve_time(1, 6, 0, anchor) == datetime(2023, 1, 1, 6)
        assert resolve_time(31, 22, 0, anchor, not_before=anchor) == datetime(2023, 1, 31, 22)

    @pytest.mark.parametrize("d,h,m", [(0, 0, 0), (32, 0, 0), (1, 25, 0), (1, 24, 30), (1, 0, 60)])
    def test_resolve_time_invalid(self, d, h, m):
        with pytest.raises(TafDecodeError):
            resolve_time(d, h, m, datetime(2023, 1, 15))


# ----------------------------------------------------------------------------- groups
class TestGroups:
    def test_publication_lfrs(self):
        t = decode_taf(TAF_LFRS)
        assert t.amendment
        labels = [g.label for g in t.groups]
        assert labels == ["BASE", "TEMPO", "BECMG", "TEMPO", "PROB30 TEMPO", "BECMG", "TEMPO"]
        codes = [g.code for g in t.groups]
        assert codes == [0, 1, 6, 1, 3, 6, 1]
        prob = t.groups[4]
        assert prob.probability == 30
        assert prob.wind == Wind(270, 30, 50, "KT")
        assert prob.visibility_m == 1400
        assert prob.weather == ("TSRA",)
        assert prob.clouds == (Cloud("BKN", 800), Cloud("BKN", 1400, "CB"))
        assert t.warnings == []

    @pytest.mark.parametrize(
        "body, label, code",
        [
            ("PROB30 0310/0312 4000 BR", "PROB30", 2),
            ("PROB40 0310/0312 4000 BR", "PROB40", 4),
            ("PROB40 TEMPO 0310/0312 4000 BR", "PROB40 TEMPO", 5),
            ("INTER 0310/0312 4000 BR", "INTER", 8),
            ("FM031000 4000 BR", "FM", 7),
            ("FM 031000 4000 BR", "FM", 7),
        ],
    )
    def test_change_indicators(self, body, label, code):
        t = decode_taf(f"TAF LKTB 030500Z 0306/0406 17007KT 9999 {body}=", reference_time=REF)
        g = t.groups[1]
        assert (g.label, g.code) == (label, code)
        assert g.visibility_m == 4000

    def test_fm_end_times(self):
        t = decode_taf(TAF_KJFK, reference_time="2026-12-31")
        fm1, fm2 = t.groups[1], t.groups[2]
        assert fm1.end == fm2.start == datetime(2027, 1, 1, 18)
        assert fm2.end == t.valid_to

    def test_fm_with_minutes(self):
        t = decode_taf("TAF LKTB 030500Z 0306/0406 17007KT FM031230 20010KT=", reference_time=REF)
        assert t.groups[1].start == datetime(2023, 8, 3, 12, 30)

    def test_group_without_period_warns(self):
        t = decode_taf("TAF LKTB 030500Z 0306/0406 17007KT TEMPO 4000 BR=", reference_time=REF)
        assert t.groups[1].start == t.valid_from
        assert any("without period" in w for w in t.warnings)

    def test_group_outside_validity_warns(self):
        t = decode_taf("TAF LKTB 030500Z 0306/0318 17007KT TEMPO 0320/0322 4000=", reference_time=REF)
        assert any("outside validity" in w for w in t.warnings)

    def test_empty_group_warns(self):
        t = decode_taf("TAF LKTB 030500Z 0306/0406 17007KT TEMPO 0310/0312=", reference_time=REF)
        assert any("Empty group" in w for w in t.warnings)

    def test_raw_group_text(self):
        t = decode_taf(TAF_LFRS)
        assert t.groups[4].raw == "PROB30 TEMPO 0208/0218 27030G50KT 1400 TSRA BKN008 BKN014CB"


# --------------------------------------------------------------------------- elements
class TestWind:
    @pytest.mark.parametrize(
        "tok, wind",
        [
            ("17007KT", Wind(170, 7)),
            ("25025G40KT", Wind(250, 25, 40)),
            ("VRB02KT", Wind(None, 2, variable=True)),
            ("00000KT", Wind(0, 0)),
            ("270105G130KT", Wind(270, 105, 130)),
            ("24008MPS", Wind(240, 8, unit="MPS")),
            ("24030KMH", Wind(240, 30, unit="KMH")),
        ],
    )
    def test_wind(self, tok, wind):
        assert base(tok).wind == wind

    def test_variable_direction(self):
        w = base("17007KT 140V200 9999").wind
        assert (w.variable_from, w.variable_to) == (140, 200)

    def test_knots_conversion(self):
        assert base("24010MPS").wind.speed_kt == 19.4
        assert base("24010G20MPS").wind.gust_kt == 38.9
        assert base("17007KT").wind.gust_kt is None


class TestVisibility:
    @pytest.mark.parametrize(
        "tok, metres",
        [
            ("9999", 9999),
            ("0000", 0),
            ("0800", 800),
            ("4000NDV", 4000),
            ("1500SW", 1500),
            ("P6SM", 9656),
            ("6SM", 9656),
            ("1/2SM", 805),
            ("M1/4SM", 402),
            ("1 1/2SM", 2414),
            ("CAVOK", 10000),
        ],
    )
    def test_visibility(self, tok, metres):
        g = base(f"17007KT {tok}")
        assert g.visibility_m == metres
        assert g.visibility_raw == tok
        assert g.unparsed == ()

    def test_directional_after_prevailing(self):
        g = base("17007KT 4000 1500SW")
        assert g.visibility_m == 4000
        assert g.visibility_raw == "4000 1500SW"

    def test_zero_denominator_is_unparsed(self):
        assert base("17007KT 1/0SM").unparsed == ("1/0SM",)

    def test_cavok_flag(self):
        g = base("17007KT CAVOK")
        assert g.cavok and g.visibility_m == 10000


class TestWeather:
    @pytest.mark.parametrize(
        "toks",
        ["-SHRA", "+TSRA", "VCSH", "FZFG", "BR", "TS", "-RADZ", "+SHRASN", "VCTS", "BCFG", "DRSN", "+FC"],
    )
    def test_weather(self, toks):
        assert base(f"17007KT 9999 {toks}").weather == (toks,)

    def test_multiple(self):
        assert base("17007KT 2000 -RA BR").weather == ("-RA", "BR")

    def test_nsw(self):
        g = base("17007KT 9999 NSW")
        assert g.nsw and g.weather == ()


class TestClouds:
    def test_layers(self):
        g = base("17007KT 9999 FEW005 SCT015TCU BKN030CB OVC100 BKN///")
        assert g.clouds == (
            Cloud("FEW", 500),
            Cloud("SCT", 1500, "TCU"),
            Cloud("BKN", 3000, "CB"),
            Cloud("OVC", 10000),
            Cloud("BKN", None),
        )
        assert g.ceiling_ft == 3000

    def test_slashes_type(self):
        assert base("17007KT 9999 BKN030///").clouds == (Cloud("BKN", 3000, None),)

    @pytest.mark.parametrize("tok, height", [("VV001", 100), ("VV///", None)])
    def test_vertical_visibility(self, tok, height):
        g = base(f"17007KT 0100 FG {tok}")
        assert g.clouds == (Cloud("VV", height),)
        assert g.ceiling_ft == height

    @pytest.mark.parametrize("tok", ["NSC", "SKC", "NCD", "CLR"])
    def test_no_clouds(self, tok):
        g = base(f"17007KT 9999 {tok}")
        assert g.no_clouds and g.clouds == () and g.ceiling_ft is None


class TestTemperatures:
    def test_tx_tn(self):
        g = base("17007KT 9999 TX25/0314Z TNM02/0404Z")
        assert g.max_temp_c == 25 and g.max_temp_time == datetime(2023, 8, 3, 14)
        assert g.min_temp_c == -2 and g.min_temp_time == datetime(2023, 8, 4, 4)

    def test_invalid_temp_time_warns(self):
        t = decode_taf("TAF LKTB 030500Z 0306/0406 17007KT TX25/3514Z=", reference_time=REF)
        assert t.groups[0].max_temp_c == 25
        assert t.groups[0].max_temp_time is None
        assert t.warnings


def test_unknown_tokens_preserved():
    g = base("17007KT 9999 WS020/24045KT 620304 QNH1013")
    assert g.unparsed == ("WS020/24045KT", "620304", "QNH1013")
    assert g.wind == Wind(170, 7)
