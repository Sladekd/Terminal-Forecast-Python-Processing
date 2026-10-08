from pathlib import Path

import pytest

DATA = Path(__file__).parent / "data"

# Example from the publication / Plot_ws_Taf notebook
TAF_LFRS = """202311020512 TAF AMD LFRS 020512Z 0206/0312 25025G40KT 9999 BKN030
                      TEMPO 0206/0208 25025G60KT 3000 SHRA SCT015
                       BKN030CB
                      BECMG 0208/0210 26020G35KT
                      TEMPO 0208/0220 27020G40KT 3000 SHRA SCT015
                       BKN030CB
                      PROB30 TEMPO 0208/0218 27030G50KT 1400 TSRA BKN008 BKN014CB
                      BECMG 0222/0224 18006KT
                      TEMPO 0300/0312 4500 -SHRA SCT035CB BKN045="""

# Example from the Taf_decode notebook
TAF_LKTB = (
    " 202308030500 TAF LKTB 030500Z 0306/0406 17007KT 9999 SCT025      "
    "TEMPO 0306/0309 19013KT RA BKN025      BECMG 0322/0400 VRB02KT="
)

TAF_KJFK = (
    "TAF KJFK 312330Z 0100/0206 18010KT P6SM FEW250 "
    "FM010600 20012G22KT 1 1/2SM -RA BR OVC008 "
    "FM011800 27015KT P6SM SCT040 TX15/0118Z TNM02/0210Z"
)


@pytest.fixture
def data_dir():
    return DATA
