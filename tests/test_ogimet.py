import io
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse

import pandas as pd
import pytest

from taf_decoder import (
    OgimetError,
    clean_taf_ogimet_file,
    decode_many,
    download_ogimet,
    ogimet_url,
    read_ogimet_file,
    split_ogimet_text,
    split_reports,
)
from taf_decoder.ogimet import html_to_text


class FakeResponse(io.BytesIO):
    class _Headers:
        def get_content_charset(self):
            return "utf-8"

    headers = _Headers()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def opener_returning(*results):
    """Fake urlopen yielding the given results in order (bytes or exceptions)."""
    calls = []
    it = iter(results)

    def opener(req, timeout):
        calls.append(req.full_url)
        res = next(it)
        if isinstance(res, BaseException):
            raise res
        return FakeResponse(res)

    opener.calls = calls
    return opener


SAMPLE_HTML = (
    b"<html><head><style>p{}</style></head><body><pre>"
    b"202007010500 TAF EDDT 010500Z 0106/0212 26008KT 9999 SCT030=\n"
    b"</pre></body></html>"
)


class TestUrl:
    def test_params(self):
        q = parse_qs(urlparse(ogimet_url(["eddt", "LKTB"], 2024, 2)).query)
        assert q["lugar"] == ["EDDT,LKTB"]
        assert q["tipo"] == ["FT"]
        assert q["dayf"] == ["29"]  # leap year
        assert q["mes"] == q["mesf"] == ["02"]

    def test_station_string(self):
        q = parse_qs(urlparse(ogimet_url("EDDT, LKTB;LKPR", 2023, 1)).query)
        assert q["lugar"] == ["EDDT,LKTB,LKPR"]

    @pytest.mark.parametrize(
        "stations, year, month",
        [([], 2023, 1), (["EDD"], 2023, 1), (["EDDT"], 2023, 13), (["EDDT"], 1800, 1)],
    )
    def test_invalid(self, stations, year, month):
        with pytest.raises(ValueError):
            ogimet_url(stations, year, month)


class TestDownload:
    def test_success_and_save(self, tmp_path):
        opener = opener_returning(SAMPLE_HTML)
        text = download_ogimet(["EDDT"], 2020, 7, save_dir=tmp_path / "out", opener=opener)
        assert "202007010500 TAF EDDT" in text and "<pre>" not in text and "p{}" not in text
        assert (tmp_path / "out" / "TAF202007.txt").read_text(encoding="utf-8") == text
        assert len(opener.calls) == 1

    def test_retries_transient_errors(self):
        opener = opener_returning(
            URLError("down"),
            HTTPError("u", 503, "busy", {}, None),
            SAMPLE_HTML,
        )
        assert "EDDT" in download_ogimet("EDDT", 2020, 7, opener=opener, backoff=0)
        assert len(opener.calls) == 3

    def test_gives_up(self):
        opener = opener_returning(*[URLError("down")] * 3)
        with pytest.raises(OgimetError, match="3 attempts"):
            download_ogimet("EDDT", 2020, 7, opener=opener, retries=2, backoff=0)

    def test_client_error_not_retried(self):
        opener = opener_returning(HTTPError("u", 404, "nf", {}, None))
        with pytest.raises(OgimetError, match="404"):
            download_ogimet("EDDT", 2020, 7, opener=opener, backoff=0)
        assert len(opener.calls) == 1

    def test_quota(self):
        opener = opener_returning(b"#Sorry, Your quota limit for slow queries rate has been reached")
        with pytest.raises(OgimetError, match="quota"):
            download_ogimet("EDDT", 2020, 7, opener=opener)

    def test_no_reports(self):
        with pytest.raises(OgimetError, match="No reports"):
            download_ogimet("EDDT", 2020, 7, opener=opener_returning(b"# nothing here"))


class TestSplitting:
    def test_sample_file(self, data_dir):
        reports = split_ogimet_text((data_dir / "ogimet_sample.txt").read_text())
        assert len(reports) == 6
        assert reports[0].startswith("202007010500 TAF EDDT") and reports[0].endswith("=")
        assert "  " not in reports[0]

    def test_read_file_and_decode(self, data_dir):
        df = read_ogimet_file(data_dir / "ogimet_sample.txt")
        assert list(df.columns) == ["report_time", "taf"]
        assert df["report_time"].iloc[0] == pd.Timestamp("2020-07-01 05:00")
        decoded = decode_many(df["taf"], kind="timeline")
        first = decoded.drop_duplicates("taf_index").set_index("taf_index")
        assert first["error"].notna().tolist() == [False, False, False, False, False, True]
        assert bool(first.loc[2, "nil"])
        assert "GARBAGE" in first.loc[4, "warnings"]
        # month rollover in the AMD TAF
        amd = decoded[decoded["taf_index"] == 3]
        assert amd["valid_to"].iloc[0] == pd.Timestamp("2020-08-02 00:00")

    def test_legacy_clean_function(self, data_dir):
        df = clean_taf_ogimet_file(data_dir / "ogimet_sample.txt")
        assert list(df.columns) == ["TAF Forecast"] and len(df) == 6

    def test_report_without_terminator(self):
        text = "# head\n202007010500 TAF EDDT 010500Z 0106/0212 26008KT\n# comment\n"
        assert split_ogimet_text(text) == ["202007010500 TAF EDDT 010500Z 0106/0212 26008KT"]

    def test_split_reports_plain(self):
        assert split_reports("TAF A=\nTAF B=") == ["TAF A=", "TAF B="]
        assert split_reports("TAF A\nTAF B\n\n") == ["TAF A", "TAF B"]
        assert split_reports("") == []

    def test_html_to_text_passthrough(self):
        assert html_to_text("plain") == "plain"
