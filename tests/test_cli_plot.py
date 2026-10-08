import json

import pandas as pd
import pytest
from conftest import TAF_LFRS, TAF_LKTB

from taf_decoder import decode_taf, plot_wind, taf_to_dataframe
from taf_decoder.cli import main


class TestCli:
    def test_args_csv(self, capsys):
        assert main([TAF_LKTB, "--format", "csv"]) == 0
        out = capsys.readouterr().out
        assert out.splitlines()[0].startswith("taf_index,station")
        assert len(out.splitlines()) == 4

    def test_json_timeline(self, capsys):
        assert main([TAF_LFRS, "--format", "json", "-k", "timeline"]) == 0
        rows = json.loads(capsys.readouterr().out)
        assert len(rows) == 7 and rows[0]["station"] == "LFRS"

    def test_table(self, capsys):
        assert main([TAF_LKTB, "--format", "table"]) == 0
        assert "LKTB" in capsys.readouterr().out

    def test_file_and_output(self, data_dir, tmp_path, capsys):
        out = tmp_path / "x.csv"
        code = main(["-f", str(data_dir / "ogimet_sample.txt"), "-o", str(out)])
        assert code == 1  # one undecodable report
        assert "1 of 6" in capsys.readouterr().err
        assert pd.read_csv(out)["taf_index"].nunique() == 6

    def test_stdin(self, monkeypatch, capsys):
        import io

        monkeypatch.setattr("sys.stdin", io.StringIO(TAF_LKTB))
        assert main(["--format", "csv"]) == 0
        assert "LKTB" in capsys.readouterr().out

    def test_reference_time_and_strict(self, capsys):
        taf = "TAF LKTB 030500Z 0306/0406 17007KT FOO="
        assert main([taf, "--reference-time", "2023-08-03", "--format", "csv"]) == 0
        assert main([taf, "--reference-time", "2023-08-03", "--strict", "--format", "csv"]) == 1

    def test_no_reports(self, capsys):
        assert main(["   "]) == 1

    def test_version(self, capsys):
        with pytest.raises(SystemExit):
            main(["--version"])
        assert "taf-decoder" in capsys.readouterr().out


class TestPlot:
    @pytest.fixture(autouse=True)
    def _agg(self):
        mpl = pytest.importorskip("matplotlib")
        mpl.use("Agg")
        yield
        import matplotlib.pyplot as plt

        plt.close("all")

    @pytest.mark.parametrize("kind", ["str", "taf", "timeline", "hourly"])
    def test_inputs(self, kind):
        data = {
            "str": TAF_LFRS,
            "taf": decode_taf(TAF_LFRS),
            "timeline": taf_to_dataframe(TAF_LFRS),
            "hourly": taf_to_dataframe(TAF_LFRS, kind="hourly"),
        }[kind]
        ax = plot_wind(data)
        assert "LFRS" in ax.get_title()
        assert len(ax.collections) > 0

    def test_save_and_options(self, tmp_path):
        path = tmp_path / "wind.png"
        ax = plot_wind(TAF_LFRS, gusts=False, temporary=False, title="T", save_path=path)
        assert path.stat().st_size > 0 and ax.get_title() == "T"

    def test_no_data(self):
        ax = plot_wind(decode_taf("202007011700 TAF EDDT 011700Z NIL="))
        assert ax.texts

    def test_bad_input(self):
        with pytest.raises(TypeError):
            plot_wind(42)
