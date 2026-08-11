import hashlib

import crawl_evidence as ce


RAW_MATCH = {
    "match_id": 2040829,
    "home": "阿拉木图",
    "away": "索列夫",
    "kickoff_iso": "2026-08-11T23:00:00+08:00",
}


SOURCE = {
    "sporttery_match_id": 2040829,
    "url": "https://official.example/match",
    "source_level": "official_competition",
    "canonical_home": "Kairat Almaty",
    "canonical_away": "Levski Sofia",
    "facts": [{
        "section": 2,
        "text": "官方页面确认本场为第三资格赛第二回合，首回合0-1。",
        "required_terms": ["Third qualifying round", "2nd leg", "1st leg: 0-1"],
    }],
}


def test_verified_source_fact_requires_identity_pre_kickoff_and_page_terms():
    snapshot = {
        "title": "Kairat Almaty vs Levski Sofia",
        "markdown": "Third qualifying round\n2nd leg\n1st leg: 0-1",
        "crawled_at": "2026-08-11T12:00:00+08:00",
        "final_url": "https://official.example/match",
    }

    facts = ce.verified_facts_for_snapshot(RAW_MATCH, SOURCE, snapshot)

    assert facts == [{
        "section": 2,
        "text": "官方页面确认本场为第三资格赛第二回合，首回合0-1。",
        "source": "https://official.example/match",
        "collected_at": "2026-08-11T12:00:00+08:00",
        "source_level": "official_competition",
    }]


def test_source_fact_rejects_missing_away_team_post_kickoff_or_unseen_terms():
    base = {
        "title": "Kairat Almaty vs Levski Sofia",
        "markdown": "Third qualifying round\n2nd leg\n1st leg: 0-1",
        "crawled_at": "2026-08-11T12:00:00+08:00",
        "final_url": "https://official.example/match",
    }
    assert ce.verified_facts_for_snapshot(
        RAW_MATCH, SOURCE, {**base, "title": "Kairat Almaty news", "markdown": "Kairat Almaty Third qualifying round 2nd leg 1st leg: 0-1"}
    ) == []
    assert ce.verified_facts_for_snapshot(
        RAW_MATCH, SOURCE, {**base, "crawled_at": "2026-08-11T23:00:00+08:00"}
    ) == []
    assert ce.verified_facts_for_snapshot(
        RAW_MATCH, SOURCE, {**base, "markdown": "Third qualifying round\n1st leg: 0-1"}
    ) == []


def test_source_fact_rejects_empty_required_terms_configuration():
    snapshot = {
        "title": "Kairat Almaty vs Levski Sofia",
        "markdown": "Third qualifying round\n2nd leg\n1st leg: 0-1",
        "crawled_at": "2026-08-11T12:00:00+08:00",
        "final_url": "https://official.example/match",
    }
    source = {**SOURCE, "facts": [{
        "section": 2,
        "text": "不应被空关键词验证的事实。",
        "required_terms": [""],
    }]}

    assert ce.verified_facts_for_snapshot(RAW_MATCH, source, snapshot) == []


def test_source_fact_rejects_redirect_to_an_unapproved_domain():
    snapshot = {
        "title": "Kairat Almaty vs Levski Sofia",
        "markdown": "Third qualifying round\n2nd leg\n1st leg: 0-1",
        "crawled_at": "2026-08-11T12:00:00+08:00",
        "final_url": "https://untrusted.example/copied-match",
    }

    assert ce.verified_facts_for_snapshot(RAW_MATCH, SOURCE, snapshot) == []


def test_primary_evidence_is_not_rendered_without_two_independent_domains_per_section():
    facts = [
        {
            "section": section,
            "text": f"第{section}类事实",
            "source": f"https://only-one.example/{section}",
            "collected_at": "2026-08-11T12:00:00+08:00",
            "source_level": "official_competition",
        }
        for section in range(1, 7)
    ]

    document, status = ce.render_primary_evidence(RAW_MATCH, facts)

    assert document is None
    assert status == {"ok": False, "reason": "insufficient_independent_sources:1"}


def test_snapshot_keeps_match_identity_final_url_and_content_hash():
    snapshot = ce.build_snapshot(
        RAW_MATCH,
        SOURCE,
        title="Kairat Almaty vs Levski Sofia",
        markdown="Third qualifying round\n2nd leg",
        final_url="https://official.example/redirected-match",
        crawled_at="2026-08-11T12:00:00+08:00",
    )

    assert snapshot["sporttery_match_id"] == 2040829
    assert snapshot["canonical_home"] == "Kairat Almaty"
    assert snapshot["canonical_away"] == "Levski Sofia"
    assert snapshot["final_url"] == "https://official.example/redirected-match"
    assert snapshot["content_sha256"] == hashlib.sha256(
        "Third qualifying round\n2nd leg".encode("utf-8")
    ).hexdigest()


def test_primary_writer_refuses_to_overwrite_existing_primary_evidence(tmp_path):
    facts = []
    for section in range(1, 7):
        for domain in ("official-one.example", "official-two.example"):
            facts.append({
                "section": section,
                "text": f"第{section}类事实-{domain}",
                "source": f"https://{domain}/{section}",
                "collected_at": "2026-08-11T12:00:00+08:00",
                "source_level": "official_competition",
            })
    existing = tmp_path / "evidence_005_existing.md"
    existing.write_text("人工审核的主证据", encoding="utf-8")

    result = ce.write_primary_evidence(tmp_path, 5, RAW_MATCH, facts)

    assert result == {"ok": False, "reason": "existing_primary_evidence"}
    assert existing.read_text(encoding="utf-8") == "人工审核的主证据"
