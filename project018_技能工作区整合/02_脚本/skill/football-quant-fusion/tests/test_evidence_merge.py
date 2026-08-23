import importlib.util
from pathlib import Path


MODULE = Path(__file__).parents[1] / "scripts" / "evidence_merge.py"
spec = importlib.util.spec_from_file_location("evidence_merge", MODULE)
em = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(em)


def test_browser_predicted_xi_fills_pending_mobile_entry():
    chain = {
        "starting_xi": {"status": "PENDING_REFRESH", "source_id": "sporttery.preview"},
        "injury": {"status": "VALID", "source_id": "sporttery.preview"},
    }
    browser = {"entries": {
        "starting_xi": {"status": "PREDICTED", "source_id": "fotmob.bb_browser", "value": {"home": ["A"]}},
        "injury": {"status": "VALID", "source_id": "goal.preview", "value": {"home": ["B"]}},
    }}
    merged, audit = em.merge_browser_audit(chain, browser)
    assert merged["starting_xi"]["status"] == "PREDICTED"
    assert merged["starting_xi"]["source_id"] == "fotmob.bb_browser"
    assert merged["injury"]["status"] == "VALID"
    assert audit["browser_fields_merged"] == ["starting_xi"]


def test_conflict_preserves_both_sources_without_silent_overwrite():
    chain = {"injury": {"status": "VALID", "source_id": "sporttery.preview", "value": {"home": ["A"]}}}
    browser = {"entries": {"injury": {"status": "VALID", "source_id": "goal.preview", "value": {"home": ["B"]}}}}
    merged, audit = em.merge_browser_audit(chain, browser)
    assert merged["injury"]["source_id"] == "sporttery.preview"
    assert len(merged["injury"]["alternatives"]) == 1
    assert audit["conflicts"] == ["injury"]
