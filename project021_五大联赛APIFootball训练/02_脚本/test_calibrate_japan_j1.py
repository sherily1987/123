from __future__ import annotations

import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("cal_j1", Path(__file__).with_name("calibrate_japan_j1.py"))
mod = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(mod)


def test_fd_slug_aliases_known_j1_variants():
    assert mod.fd_slug("Consadole Sapporo") == "hokkaidoconsadolesapporo"
    assert mod.fd_slug("Jubilo Iwata") == "iwata"
    assert mod.fd_slug("Kashima") == "kashimaantlers"
    assert mod.fd_slug("Kyoto Sanga") == "kyoto"
    assert mod.fd_slug("Machida Zelvia") == "machida"
    assert mod.fd_slug("Urawa") == "urawareds"
    assert mod.fd_slug("Tokyo Verdy") == "verdy"
    assert mod.fd_slug("Kawasaki Frontale") == "kawasakifrontale"


def test_attach_closing_matches_same_day_and_skips_ambiguous():
    api = [
        {"match_id": 1, "kickoff": "2024-03-01T18:00:00", "home": "Kashima", "away": "FC Tokyo"},
        {"match_id": 2, "kickoff": "2024-03-02T18:00:00", "home": "Gamba Osaka", "away": "Cerezo Osaka"},
    ]
    fd = [
        {"match_id": 10, "kickoff": "2024-03-01T09:00:00", "home": "Kashima Antlers",
         "away": "FC Tokyo", "closing_market_1x2": [0.5, 0.25, 0.25]},
        {"match_id": 11, "kickoff": "2024-03-02T09:00:00", "home": "Gamba Osaka",
         "away": "Cerezo Osaka", "closing_market_1x2": [0.4, 0.3, 0.3]},
        {"match_id": 12, "kickoff": "2024-03-02T10:00:00", "home": "Gamba Osaka",
         "away": "Cerezo Osaka", "closing_market_1x2": [0.41, 0.29, 0.3]},
    ]
    out, audit = mod.attach_closing(api, fd)
    assert out[0]["closing_market_1x2"] == [0.5, 0.25, 0.25]
    assert "closing_market_1x2" not in out[1]
    assert audit["attached"] == 1
    assert audit["ambiguous"] == 1
    assert "provider_market_1x2" not in out[0]
