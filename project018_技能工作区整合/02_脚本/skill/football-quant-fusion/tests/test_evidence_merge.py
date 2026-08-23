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


def test_newer_api_snapshot_replaces_stale_preview_but_keeps_alternative():
    chain = {"injury": {"status": "VALID", "source_id": "sporttery.preview",
                         "value": {"home": []}, "refreshed_at": "2026-08-23T13:00:00+00:00"}}
    browser = {"entries": {"injury": {"status": "VALID", "source_id": "api-sports.io",
                                        "value": {"home": ["A1"]},
                                        "refreshed_at": "2026-08-23T15:00:00+00:00"}}}
    merged, audit = em.merge_browser_audit(chain, browser)
    assert merged["injury"]["source_id"] == "api-sports.io"
    assert merged["injury"]["alternatives"][0]["source_id"] == "sporttery.preview"
    assert audit["browser_fields_merged"] == ["injury"]


def test_late_info_fills_unusable_injury_and_preserves_post_kickoff_event():
    chain = {
        "injury": {"status": "UNAVAILABLE", "source_id": "sporttery.preview"},
        "starting_xi": {"status": "PENDING_REFRESH", "source_id": "sporttery.preview"},
    }
    merged, audit = em.merge_late_info_events(chain, [
        {
            "kind": "injury", "status": "VALID", "collected_at": "2026-08-23T20:00:00+00:00",
            "absence": {"home": {"count": 1}}, "gate": {"minutes_to_kickoff": 120},
        },
        {
            "kind": "lineup", "status": "VALID", "collected_at": "2026-08-24T01:00:00+00:00",
            "lineup": {"home": {"starting_count": 11}}, "gate": {"minutes_to_kickoff": -1},
        },
    ])
    assert merged["injury"]["status"] == "VALID"
    assert merged["starting_xi"]["status"] == "PENDING_REFRESH"
    assert audit["fields_merged"] == ["injury"]
    assert audit["ignored_post_kickoff"] == 1


def test_late_info_conflict_keeps_initial_confirmed_source():
    chain = {"injury": {"status": "VALID", "source_id": "official", "value": {"home": []}}}
    merged, audit = em.merge_late_info_events(chain, [{
        "kind": "injury", "status": "VALID", "collected_at": "2026-08-23T20:00:00+00:00",
        "absence": {"home": {"count": 2}}, "gate": {"minutes_to_kickoff": 60},
    }])
    assert merged["injury"]["source_id"] == "official"
    assert len(merged["injury"]["alternatives"]) == 1
    assert audit["conflicts"] == ["injury"]
