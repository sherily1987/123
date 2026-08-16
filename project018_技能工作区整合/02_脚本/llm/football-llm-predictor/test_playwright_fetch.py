import json

import playwright_fetch as pf


LONG_BODY = "Injured players. Type of injury and expected return. " * 120


def test_cloudflare_interstitial_is_a_gap_not_a_success():
    verdict = pf.classify_verdict(200, "Just a moment...", "Verify you are human" + LONG_BODY)

    assert verdict == "challenge"


def test_server_refusal_is_blocked_even_without_challenge_wording():
    assert pf.classify_verdict(403, "Forbidden", "") == "blocked"
    assert pf.classify_verdict(406, "", LONG_BODY) == "blocked"


def test_rendered_page_with_substantial_text_is_usable():
    assert pf.classify_verdict(200, "Premier League - Injured players", LONG_BODY) == "ok"


def test_skeleton_page_is_thin_not_ok():
    """curl 拿骨架的典型形态：200 但正文极短——必须与 ok 区分开。"""
    assert pf.classify_verdict(200, "Ｊリーグ公式サイト", "Loading...") == "thin"


def test_dense_japanese_page_is_not_mistaken_for_a_skeleton():
    """jleague.jp 实测：2254 字符已是全量赛程，按纯字符数会被误判成骨架。"""
    japanese = "鹿島アントラーズ 対 名古屋グランパス 試合終了 メルカリスタジアム " * 32

    assert len(japanese) < pf.THIN_TEXT_WEIGHT
    assert pf.classify_verdict(200, "Ｊリーグ公式サイト", japanese) == "ok"


def test_offsite_redirect_is_flagged_for_the_hostname_gate():
    record = pf.build_record(
        "https://www.transfermarkt.com/x/verletztespieler/wettbewerb/GB1",
        final_url="https://ads.example.com/landing",
        status=200, title="", text=LONG_BODY, fetched_at="2026-08-16T13:00:00+08:00")

    assert record["redirected_offsite"] is True


def test_www_only_difference_is_same_host():
    record = pf.build_record(
        "https://transfermarkt.com/a", final_url="https://www.transfermarkt.com/a",
        status=200, title="", text=LONG_BODY, fetched_at="2026-08-16T13:00:00+08:00")

    assert record["redirected_offsite"] is False


def test_record_carries_no_credentials_and_is_hash_addressed():
    record = pf.build_record(
        "https://example.com/p", final_url="https://example.com/p", status=200,
        title="T", text="body", fetched_at="2026-08-16T13:00:00+08:00")

    assert "cookie" not in json.dumps(record).casefold()
    assert record["content_sha256"] == pf.build_record(
        "https://other.example/q", final_url="https://other.example/q", status=200,
        title="T", text="body", fetched_at="2026-08-16T14:00:00+08:00")["content_sha256"]


def test_fetch_error_never_reports_a_verdict_of_ok():
    record = pf.build_record("https://example.com", final_url="", status=None, title="",
                             text="", fetched_at="2026-08-16T13:00:00+08:00",
                             error="TimeoutError: exceeded")

    assert record["verdict"] == "error"


def _stub_fetchers(monkeypatch, http_verdicts, browser_verdicts):
    """按 URL→verdict 表桩掉两条取页路径，并记录浏览器实际收到的 URL。"""
    called = []

    def fake_http(url, **_):
        record = pf.build_record(url, final_url=url, status=200, title="",
                                 text=_body_for(http_verdicts[url]), fetched_at="t")
        record["fetched_via"] = "http"
        return record

    def fake_browser(urls, **_):
        called.extend(urls)
        return [dict(pf.build_record(u, final_url=u, status=200, title="",
                                     text=_body_for(browser_verdicts[u]), fetched_at="t"),
                     fetched_via="browser") for u in urls]

    monkeypatch.setattr(pf, "fetch_http", fake_http)
    monkeypatch.setattr(pf, "fetch_urls", fake_browser)
    return called


def _body_for(verdict):
    return {"ok": LONG_BODY, "thin": "Loading...",
            "challenge": "Just a moment... verify you are human"}[verdict]


def test_http_sufficient_source_never_launches_a_browser(monkeypatch):
    """transfermarkt/oddsportal 类：正文在服务端 HTML 里，不该付渲染代价。"""
    url = "https://www.transfermarkt.com/x"
    called = _stub_fetchers(monkeypatch, {url: "ok"}, {})

    records = pf.fetch_http_first([url])

    assert called == []
    assert records[0]["fetched_via"] == "http"


def test_js_only_source_escalates_to_browser(monkeypatch):
    """fotmob 类：HTTP 只得骨架，升级渲染。"""
    url = "https://www.fotmob.com/leagues/47"
    called = _stub_fetchers(monkeypatch, {url: "thin"}, {url: "ok"})

    records = pf.fetch_http_first([url])

    assert called == [url]
    assert records[0]["fetched_via"] == "browser"
    assert records[0]["http_verdict"] == "thin"


def test_challenge_is_never_retried_in_a_browser(monkeypatch):
    """换客户端重试人机验证就是绕过；只记缺口。"""
    url = "https://fbref.com/en/comps/55"
    called = _stub_fetchers(monkeypatch, {url: "challenge"}, {})

    records = pf.fetch_http_first([url])

    assert called == []
    assert records[0]["verdict"] == "challenge"


def test_report_lists_every_gap_source():
    records = [
        pf.build_record("https://fbref.com/a", final_url="https://fbref.com/a", status=200,
                        title="Just a moment...", text="", fetched_at="t"),
        pf.build_record("https://www.transfermarkt.com/b",
                        final_url="https://www.transfermarkt.com/b", status=200,
                        title="Injured players", text=LONG_BODY, fetched_at="t"),
    ]

    report = pf.format_report(records)

    assert "fbref.com: challenge" in report
    assert "缺口 1/2" in report
