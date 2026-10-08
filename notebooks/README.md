# Original notebooks

These are the notebooks used for the publication, kept for reference. The same
functionality is now available, tested and with bugs fixed, in the `taf-decoder`
package:

| Notebook | Package equivalent |
|---|---|
| `Taf_get_data.ipynb` (`build_TAF_url`) | `taf_decoder.download_ogimet(stations, year, month, save_dir=...)` |
| `Taf_clean.ipynb` (`clean_taf_ogimet_file`) | `taf_decoder.read_ogimet_file(path)` |
| `Taf_decode.ipynb` (`process_taf_to_df`) | `taf_decoder.taf_to_dataframe(text, kind="timeline")` / `decode_many(...)` |
| `Plot_ws_Taf.ipynb` (`plot_ws_g`) | `taf_decoder.plot_wind(text)` |

See the [changelog](../CHANGELOG.md) for the differences.
