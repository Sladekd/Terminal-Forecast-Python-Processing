from datetime import datetime

import pandas as pd
import pytest
from conftest import TAF_KJFK, TAF_LFRS, TAF_LKTB

from taf_decoder import decode_many, decode_taf, process_taf_to_df, taf_to_dataframe
from taf_decoder.frames import columns

REF = "2023-08-03"


def timeline(text, **kw):
    return taf_to_dataframe(text, kind="timeline", reference_time=REF, **kw)


class TestGroupsFrame:
    def test_columns_and_dtypes(self):
        df = decode_taf(TAF_LFRS).to_dataframe("groups")
        assert list(df.columns) == columns()
        assert len(df) == 7
        assert str(df["wind_speed"].dtype) == "Int64"
        assert str(df["wind_speed_kt"].dtype) == "Float64"
        assert str(df["cavok"].dtype) == "boolean"
        assert pd.api.types.is_datetime64_any_dtype(df["start"])
        assert df["group_code"].tolist() == [0, 1, 6, 1, 3, 6, 1]

    def test_nothing_inherited(self):
        df = decode_taf(TAF_LFRS).to_dataframe("groups")
        becmg = df.iloc[2]
        assert becmg["wind_speed"] == 20 and pd.isna(becmg["visibility_m"])

    def test_nil_keeps_header_row(self):
        df = decode_taf("202007011700 TAF EDDT 011700Z NIL=").to_dataframe()
        assert len(df) == 1 and bool(df["nil"].iloc[0]) and df["station"].iloc[0] == "EDDT"

    def test_more_than_four_cloud_layers(self):
        df = taf_to_dataframe(
            "TAF LKTB 030500Z 0306/0406 17007KT 9999 FEW005 FEW010 SCT020 BKN030 OVC050=",
            kind="groups",
            reference_time=REF,
        )
        assert df["cloud_cover_5"].iloc[0] == "OVC"

    def test_bad_kind(self):
        with pytest.raises(ValueError, match="kind"):
            decode_taf(TAF_LKTB).to_dataframe("weird")


class TestTimeline:
    def test_lfrs_publication_layout(self):
        df = taf_to_dataframe(TAF_LFRS, kind="timeline")
        prev = df[df["prevailing"]]
        # base, BECMG, BECMG; overlap mode: old state lasts until end of BECMG
        assert prev["start"].tolist() == [
            pd.Timestamp("2023-11-02 06:00"),
            pd.Timestamp("2023-11-02 08:00"),
            pd.Timestamp("2023-11-02 22:00"),
        ]
        assert prev["end"].tolist() == [
            pd.Timestamp("2023-11-02 10:00"),
            pd.Timestamp("2023-11-03 00:00"),
            pd.Timestamp("2023-11-03 12:00"),
        ]
        # inherited elements
        assert prev["visibility_m"].tolist() == [9999, 9999, 9999]
        assert prev["cloud_cover_1"].tolist() == ["BKN", "BKN", "BKN"]
        assert prev["wind_speed"].tolist() == [25, 20, 6]
        assert prev["wind_gust"].isna().tolist() == [False, False, True]
        # prevailing rows first, then temporary ones
        assert df["prevailing"].tolist() == [True] * 3 + [False] * 4

    @pytest.mark.parametrize(
        "mode, starts, ends",
        [
            ("overlap", ["06", "22"], ["00", "06"]),
            ("start", ["06", "22"], ["22", "06"]),
            ("end", ["06", "00"], ["00", "06"]),
        ],
    )
    def test_becmg_modes(self, mode, starts, ends):
        df = timeline(TAF_LKTB, becmg=mode)
        prev = df[df["prevailing"]]
        assert [f"{t:%H}" for t in prev["start"]] == starts
        assert [f"{t:%H}" for t in prev["end"]] == ends

    def test_bad_becmg_mode(self):
        with pytest.raises(ValueError, match="becmg"):
            timeline(TAF_LKTB, becmg="sometime")

    def test_clouds_replaced_not_merged(self):
        # regression: the notebooks forward-filled cloud columns one by one
        df = timeline("TAF LKTB 030500Z 0306/0406 17007KT 9999 FEW010 SCT020 BKN030 BECMG 0310/0312 OVC008=")
        new = df[df["prevailing"]].iloc[1]
        assert new["cloud_cover_1"] == "OVC"
        assert pd.isna(new["cloud_cover_2"]) and new["ceiling_ft"] == 800

    def test_cavok_clears_and_is_cancelled(self):
        df = timeline(
            "TAF LKTB 030500Z 0306/0406 17007KT 4000 RA BKN010 BECMG 0310/0312 CAVOK BECMG 0318/0320 3000 BR="
        )
        prev = df[df["prevailing"]]
        cav, after = prev.iloc[1], prev.iloc[2]
        assert cav["cavok"] and pd.isna(cav["weather"]) and pd.isna(cav["cloud_cover_1"])
        assert not after["cavok"] and after["visibility_m"] == 3000 and after["weather"] == "BR"

    def test_nsw_ends_weather(self):
        df = timeline("TAF LKTB 030500Z 0306/0406 17007KT 4000 RA BKN010 BECMG 0310/0312 9999 NSW=")
        assert pd.isna(df[df["prevailing"]].iloc[1]["weather"])

    def test_fm_does_not_inherit(self):
        df = taf_to_dataframe(TAF_KJFK, kind="timeline", reference_time="2026-12-31")
        prev = df[df["prevailing"]]
        assert prev["end"].iloc[0] == prev["start"].iloc[1] == pd.Timestamp("2027-01-01 06:00")
        fm2 = prev.iloc[2]
        assert fm2["cloud_cover_1"] == "SCT" and pd.isna(fm2["weather"])

    def test_tempo_fill(self):
        df = timeline("TAF LKTB 030500Z 0306/0406 17007KT 9999 SCT025 TEMPO 0310/0312 4000 BR=")
        tempo = df[~df["prevailing"]].iloc[0]
        assert tempo["wind_speed"] == 7 and tempo["cloud_cover_1"] == "SCT"
        raw = timeline(
            "TAF LKTB 030500Z 0306/0406 17007KT 9999 SCT025 TEMPO 0310/0312 4000 BR=",
            fill_temporary=False,
        )
        tempo = raw[~raw["prevailing"]].iloc[0]
        assert pd.isna(tempo["wind_speed"]) and tempo["visibility_m"] == 4000

    def test_tempo_fill_uses_state_at_its_start(self):
        df = timeline(TAF_LKTB.replace("VRB02KT", "VRB02KT TEMPO 0400/0402 SHRA"))
        last = df[~df["prevailing"]].iloc[-1]
        assert bool(last["wind_variable"]) and last["wind_speed"] == 2


class TestHourly:
    def test_hours(self):
        df = taf_to_dataframe(TAF_LKTB, kind="hourly")
        assert df["time"].min() == pd.Timestamp("2023-08-03 06:00")
        assert df["time"].max() == pd.Timestamp("2023-08-04 05:00")
        tempo = df[df["change"] == "TEMPO"]
        assert len(tempo) == 3  # 06, 07, 08 - end is exclusive
        # overlap mode: two prevailing rows during the BECMG transition
        assert (df[df["prevailing"]].groupby("time").size().max()) == 2

    def test_hours_single_switch(self):
        df = taf_to_dataframe(TAF_LKTB, kind="hourly", becmg="start")
        assert df[df["prevailing"]].groupby("time").size().max() == 1
        assert len(df[df["prevailing"]]) == 24

    def test_fm_half_hour(self):
        df = taf_to_dataframe(
            "TAF LKTB 030500Z 0306/0312 17007KT FM030930 20010KT=", kind="hourly", reference_time=REF
        )
        fm = df[df["change"] == "FM"]
        assert fm["time"].tolist()[0] == pd.Timestamp("2023-08-03 09:00")

    def test_nil_gives_empty(self):
        df = decode_taf("202007011700 TAF EDDT 011700Z NIL=").to_dataframe("hourly")
        assert df.empty and "time" in df.columns


class TestDecodeMany:
    def test_mixed_input(self):
        tafs = pd.Series([TAF_LKTB, None, "garbage", float("nan"), TAF_LFRS])
        df = decode_many(tafs)
        assert df["taf_index"].unique().tolist() == [0, 1, 2, 3, 4]
        errors = df.drop_duplicates("taf_index").set_index("taf_index")["error"]
        assert errors.notna().tolist() == [False, True, True, True, False]
        assert list(df.columns[:2]) == ["taf_index", "station"]
        assert list(df.columns[-2:]) == ["warnings", "error"]

    def test_ignore_and_raise(self):
        assert decode_many(["garbage", TAF_LKTB], errors="ignore")["taf_index"].unique().tolist() == [1]
        with pytest.raises(Exception, match="station"):
            decode_many(["garbage"], errors="raise")

    def test_single_string(self):
        assert decode_many(TAF_LKTB)["taf_index"].unique().tolist() == [0]

    def test_empty_input(self):
        df = decode_many([])
        assert df.empty and "station" in df.columns

    def test_hourly_keeps_errors(self):
        df = decode_many([TAF_LKTB, "garbage"], kind="hourly")
        assert df["error"].notna().sum() == 1
        assert df[df["taf_index"] == 0]["time"].notna().all()

    def test_warnings_column(self):
        df = decode_many(["TAF LKTB 030500Z 0306/0406 17007KT FOO="], reference_time=REF)
        assert "FOO" in df["warnings"].iloc[0]

    def test_bad_arguments(self):
        with pytest.raises(ValueError):
            decode_many([TAF_LKTB], kind="nope")
        with pytest.raises(ValueError):
            decode_many([TAF_LKTB], errors="nope")
        with pytest.raises(ValueError):
            decode_many([TAF_LKTB], becmg="nope")

    def test_concat_consistent_columns(self):
        a = taf_to_dataframe(TAF_LKTB)
        b = taf_to_dataframe(TAF_LFRS)
        assert list(a.columns) == list(b.columns)


def test_legacy_process_taf_to_df():
    with pytest.warns(DeprecationWarning):
        df = process_taf_to_df(TAF_LKTB)
    pd.testing.assert_frame_equal(df, taf_to_dataframe(TAF_LKTB, kind="timeline"))


def test_timestamps_are_naive_utc():
    df = taf_to_dataframe(TAF_LKTB)
    assert df["start"].dt.tz is None
    assert df["issue_time"].iloc[0] == datetime(2023, 8, 3, 5)


def test_expand_hourly_duplicate_index_and_zero_length():
    from taf_decoder import expand_hourly

    a = taf_to_dataframe(TAF_LKTB)
    both = pd.concat([a, a])  # duplicate index labels
    assert len(expand_hourly(both)) == 2 * len(expand_hourly(a))
    zero = a.copy()
    zero["end"] = zero["start"]
    assert expand_hourly(zero).empty
