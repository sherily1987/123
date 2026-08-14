#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""国际盘对照适配器（可选，The Odds API）。

用途：给体彩主链路加一个独立的国际盘赔率快照源，作为移动赔率 / CLV 参考。
赔率一律以体彩官方为准；本数据不参与概率建模、不替换体彩盘口、不进推荐门控；
默认不启用（未设置 ODDS_API_KEY 时直接跳过）。

用法：
  python3 odds_api_adapter.py --match-file raw.json --out intl_snapshot.json
  python3 odds_api_adapter.py --match-file raw.json --out intl_snapshot.json --dry-run
  python3 odds_api_adapter.py --dry-run            # 不传 match-file 也可（只打印计划）
  python3 odds_api_adapter.py --check-sports       # 拉一次 sports 列表校验配置里的 sport key

环境变量：
  ODDS_API_KEY  The Odds API 免费 key（https://the-odds-api.com/，500 次/月）

输出：
  - 快照 JSON（--out）：本次抓取的完整报告
  - 追加 JSONL（--store/intl_production.jsonl）：每次运行一行，保留各家博彩赔率供 CLV 回算

免费档配额纪律：默认每联赛 1 个请求（h2h 单市场）；--markets 追加市场会额外计次。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent
DEFAULT_CONFIG = SKILL_ROOT / "config" / "intl_odds_sources.json"
DEFAULT_STORE = Path(
    "F:\HM足球比赛预测\project017_football-quant-fusion技能导出\03_共享数据\football-quant-fusion/odds"
)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def load_api_key():
    """读取 ODDS_API_KEY：优先环境变量；Windows 下回退读用户注册表
    （setx 持久化后，部分新进程/计划任务可能拿不到环境变量）。"""
    key = os.environ.get("ODDS_API_KEY", "")
    if key:
        return key
    if sys.platform.startswith("win"):
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                return winreg.QueryValueEx(k, "ODDS_API_KEY")[0]
        except Exception:
            pass
    return ""


def norm_name(name: str) -> str:
    """归一化队名：小写、去变音符号、只保留字母数字。"""
    if not name:
        return ""
    s = unicodedata.normalize("NFKD", name)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return "".join(ch for ch in s.lower() if ch.isalnum())


def name_hits(alias, candidates) -> bool:
    a = norm_name(alias)
    if not a:
        return False
    for c in candidates:
        cn = norm_name(c)
        if a == cn:
            return True
        if len(a) >= 3 and len(cn) >= 3 and (a in cn or cn in a):
            return True
    return False


def fetch_json(url: str, timeout: int = 30):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


class OddsApiAdapter:
    def __init__(self, config: dict, api_key: str):
        self.base = config.get("base_url", "https://api.the-odds-api.com/v4").rstrip("/")
        self.key = api_key
        self.regions = config.get("regions", ["eu"])
        self.odds_format = config.get("odds_format", "decimal")
        self.default_markets = config.get("default_markets", ["h2h"])
        self.default_sport_keys = config.get("default_sport_keys", [])
        self.league_map = config.get("league_map", {})
        self.team_aliases = config.get("team_aliases", {})
        self._cache = {}

    def sport_key_for_league(self, league: str):
        return self.league_map.get(league or "")

    def fetch_odds(self, sport_key: str, markets):
        if sport_key in self._cache:
            return self._cache[sport_key]
        params = {
            "apiKey": self.key,
            "regions": ",".join(self.regions),
            "markets": ",".join(markets),
            "oddsFormat": self.odds_format,
        }
        url = f"{self.base}/sports/{urllib.parse.quote(sport_key)}/odds/?{urllib.parse.urlencode(params)}"
        data = fetch_json(url)
        self._cache[sport_key] = data
        return data

    def fetch_sports(self):
        url = f"{self.base}/sports/?apiKey={self.key}"
        return fetch_json(url)

    def match_event(self, sport_key: str, league: str, kickoff_iso: str,
                    home: str, away: str, events):
        """在 The Odds API 事件里找体彩场次：开球时间窗 + 队名（别名优先）。"""
        if not kickoff_iso:
            return None, "bad_kickoff"
        try:
            target = datetime.fromisoformat(kickoff_iso.replace("Z", "+00:00"))
            if target.tzinfo is None:
                target = target.replace(tzinfo=timezone.utc)
            target_ts = target.timestamp()
        except (ValueError, TypeError):
            return None, "bad_kickoff"
        aliases = [home]
        away_aliases = [away]
        # 别名扩展：体彩常用简称（如 塞萨洛），别名表键为全名（如 塞萨洛尼基）时也能命中
        for k, v in self.team_aliases.items():
            if v and name_hits(home, [k]):
                aliases.extend(v)
            if v and name_hits(away, [k]):
                away_aliases.extend(v)
        best = None
        for ev in events:
            try:
                ev_ts = datetime.fromisoformat(
                    ev.get("commence_time", "").replace("Z", "+00:00")
                ).timestamp()
            except (ValueError, TypeError):
                continue
            delta_min = abs(ev_ts - target_ts) / 60.0
            if delta_min > 90:
                continue
            if name_hits(ev.get("home_team", ""), aliases) and name_hits(ev.get("away_team", ""), away_aliases):
                if best is None or delta_min < best[0]:
                    best = (delta_min, ev)
        if best is None:
            return None, "no_intl_event"
        return best, "ok"

    def run(self, match_file, out_path, store_dir, sport_keys, markets, dry_run):
        report = {
            "schema": "intl-odds-snapshot-1.0",
            "provider": "the-odds-api",
            "status": "ok",
            "ran_at": now_iso(),
            "requests": [],
            "matches": [],
            "unmatched": [],
            "store_file": None,
            "dry_run": dry_run,
        }
        if not self.key:
            report.update(status="skipped", reason="ODDS_API_KEY 未设置，国际盘对照默认不启用")
            return report
        if dry_run:
            report["note"] = "dry-run：未发起任何网络请求"

        keys = sport_keys or self.default_sport_keys
        if not keys:
            report.update(status="error", reason="没有可用的 sport key（config/intl_odds_sources.json）")
            return report

        matches = []
        if match_file:
            try:
                raw = json.loads(Path(match_file).read_text(encoding="utf-8"))
                matches = raw.get("matches", [])
            except (OSError, ValueError) as exc:
                report.update(status="error", reason=f"match-file 读取失败: {exc}")
                return report

        # 1) 抓取各联赛国际盘（默认 h2h，1 请求/联赛；dry-run 不请求）
        events_by_key = {}
        for k in keys:
            if dry_run:
                events_by_key[k] = []
                report["requests"].append(
                    {"sport_key": k, "events": 0, "note": "dry-run 不请求"})
                continue
            try:
                data = self.fetch_odds(k, markets)
                events_by_key[k] = data or []
                n_bm = sum(len(ev.get("bookmakers", [])) for ev in events_by_key[k])
                report["requests"].append(
                    {"sport_key": k, "events": len(events_by_key[k]),
                     "bookmakers_total": n_bm, "quota": "1 请求/联赛/市场组"})
            except Exception as exc:
                report["requests"].append(
                    {"sport_key": k, "error": f"{type(exc).__name__}: {exc}"})
                events_by_key[k] = []

        # 2) 与体彩场次匹配（best-effort，未匹配不阻断）
        for m in matches:
            meta = m.get("sporttery_meta") or m.get("team_ids") or {}
            mid = f"sporttery-{(meta.get('match_id') or m.get('match_id') or '?')}"
            num = meta.get("match_num") or m.get("match_num") or "?"
            league = m.get("league") or m.get("competition") or ""
            home, away = m.get("home", ""), m.get("away", "")
            kickoff = m.get("kickoff") or m.get("kickoff_iso")
            skey = self.sport_key_for_league(league)
            if not skey:
                report["unmatched"].append(
                    {"match_id": mid, "match_num": num, "league": league,
                     "reason": f"no_sport_key（league_map 未配置: {league}）"})
                continue
            ev_hit, status = self.match_event(skey, league, kickoff, home, away, events_by_key.get(skey, []))
            if status != "ok":
                report["unmatched"].append(
                    {"match_id": mid, "match_num": num, "match": f"{home} vs {away}",
                     "league": league, "sport_key": skey, "reason": status})
                continue
            delta_min, ev = ev_hit
            entry = {
                "match_id": mid, "match_num": num,
                "match": f"{home} vs {away}", "league": league, "sport_key": skey,
                "intl_event_id": ev.get("id"), "intl_match": f"{ev.get('home_team')} vs {ev.get('away_team')}",
                "kickoff_delta_min": round(delta_min, 1),
                "commence_time": ev.get("commence_time"),
                "bookmakers": ev.get("bookmakers", []),
            }
            report["matches"].append(entry)

        # 3) 落盘：快照 JSON + 追加 JSONL（dry-run 不写）
        if not dry_run and store_dir:
            store = Path(store_dir)
            store.mkdir(parents=True, exist_ok=True)
            line = {"schema": report["schema"], "provider": report["provider"],
                    "ran_at": report["ran_at"], "matches": report["matches"]}
            with open(store / "intl_production.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
            report["store_file"] = str((store / "intl_production.jsonl").resolve())
        if out_path:
            Path(out_path).write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report


def load_config(path):
    p = Path(path) if path else DEFAULT_CONFIG
    if not p.exists():
        return {"base_url": "https://api.the-odds-api.com/v4", "regions": ["eu"],
                "odds_format": "decimal", "default_markets": ["h2h"],
                "default_sport_keys": [], "league_map": {}, "team_aliases": {}}
    return json.loads(p.read_text(encoding="utf-8"))


def main():
    ap = argparse.ArgumentParser(description="国际盘赔率对照（The Odds API / APIfootball，可选）")
    ap.add_argument("--match-file", help="体彩采集 raw/input JSON（含 matches）")
    ap.add_argument("--out", help="快照报告 JSON 输出路径")
    ap.add_argument("--store", default=str(DEFAULT_STORE), help="追加 JSONL 的 odds 目录")
    ap.add_argument("--sport-keys", help="覆盖默认 sport key 列表（逗号分隔）")
    ap.add_argument("--markets", help="覆盖默认市场（逗号分隔，如 h2h,totals）")
    ap.add_argument("--config", default=str(DEFAULT_CONFIG), help="配置文件路径")
    ap.add_argument("--provider", choices=["the-odds-api", "apifootball"], default=None,
                    help="数据源；默认取配置文件的 provider 字段")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，不发起网络请求")
    ap.add_argument("--check-sports", action="store_true", help="拉取 sports 列表校验配置")
    a = ap.parse_args()

    config = load_config(a.config)
    key = load_api_key()
    provider = a.provider or config.get("provider", "the-odds-api")

    if provider == "apifootball":
        # apifootball 用自己的环境变量 API_FOOTBALL_KEY（与 The Odds API 的 ODDS_API_KEY 不同）
        apifb_key = os.environ.get("API_FOOTBALL_KEY", "")
        if sys.platform.startswith("win") and not apifb_key:
            try:
                import winreg
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                    apifb_key = winreg.QueryValueEx(k, "API_FOOTBALL_KEY")[0]
            except Exception:
                pass
        run_apifootball(a, config, apifb_key)
        return

    adapter = OddsApiAdapter(config, key)

    if a.check_sports:
        if not key:
            print(json.dumps({"status": "skipped", "reason": "ODDS_API_KEY 未设置"},
                             ensure_ascii=False, indent=2))
            return
        try:
            sports = adapter.fetch_sports()
            known = {s.get("key") for s in sports if s.get("key")}
            bad = [k for k in (config.get("default_sport_keys") or []) if k not in known]
            print(json.dumps({"status": "ok", "total_sports": len(known),
                              "missing_in_config": bad}, ensure_ascii=False, indent=2))
        except Exception as exc:
            print(json.dumps({"status": "error", "error": f"{type(exc).__name__}: {exc}"},
                             ensure_ascii=False, indent=2))
        return

    keys = [k.strip() for k in (a.sport_keys or "").split(",") if k.strip()] or None
    markets = [k.strip() for k in (a.markets or "").split(",") if k.strip()] or config.get("default_markets", ["h2h"])
    report = adapter.run(a.match_file, a.out, a.store, keys, markets, a.dry_run)
    print(json.dumps(report, ensure_ascii=False, indent=2))


def run_apifootball(a, config, key):
    """APIfootball.com provider：按联赛拉国际盘，与体彩场次 best-effort 匹配。

    - 数据源：apiv3.apifootball.com（老牌独立足球 API，与 api-sports.io 无关）
    - 认证：环境变量 API_FOOTBALL_KEY（query 参数 APIkey）
    - get_odds 限制：日期区间 ≤5 天；每场返回多家博彩公司（bet365/WilliamHill/10Bet...）
    - 覆盖 55 联赛（欧洲主流+挪超/芬超/瑞超/苏超/土超等，2026/2027 当前赛季）
    - 赔率一律以体彩官方为准；本数据仅作移动赔率/CLV 参考，不参与建模、不进推荐门控。
    """
    if a.check_sports:
        print(json.dumps({
            "status": "ok",
            "provider": "apifootball",
            "note": "apifootball 无 sports 列表接口；覆盖 55 联赛见 apifootball_adapter.py leagues",
        }, ensure_ascii=False, indent=2))
        return

    report = {
        "schema": "intl-odds-snapshot-1.0",
        "provider": "apifootball",
        "status": "ok",
        "ran_at": now_iso(),
        "requests": [],
        "matches": [],
        "unmatched": [],
        "store_file": None,
        "dry_run": a.dry_run,
    }
    if not key:
        report.update(status="skipped", reason="API_FOOTBALL_KEY 未设置，国际盘对照默认不启用")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    if a.dry_run:
        report["note"] = "dry-run：未发起任何网络请求"

    # 1) 配置里的 league_map（中文联赛名 -> apifootball league_id）
    league_map = config.get("league_map_apifootball") or {}
    if not league_map:
        report.update(status="error", reason="config/intl_odds_sources.json 缺 league_map_apifootball")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    matches = []
    if a.match_file:
        try:
            raw = json.loads(Path(a.match_file).read_text(encoding="utf-8"))
            matches = raw.get("matches", [])
        except (OSError, ValueError) as exc:
            report.update(status="error", reason=f"match-file 读取失败: {exc}")
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return

    # 2) 对每个体彩场次查 apifootball odds（按联赛 + 开球日期前后 2 天）
    import urllib.parse
    for m in matches:
        meta = m.get("sporttery_meta") or m.get("team_ids") or {}
        mid = f"sporttery-{(meta.get('match_id') or m.get('match_id') or '?')}"
        num = meta.get("match_num") or m.get("match_num") or "?"
        league = m.get("league") or m.get("competition") or ""
        home, away = m.get("home", ""), m.get("away", "")
        kickoff = m.get("kickoff") or m.get("kickoff_iso") or ""
        lid = league_map.get(league)
        if not lid:
            report["unmatched"].append(
                {"match_id": mid, "match_num": num, "league": league,
                 "reason": f"no_apifootball_league_id（league_map_apifootball 未配置: {league}）"})
            continue
        if a.dry_run:
            report["requests"].append({"league_id": lid, "league": league, "note": "dry-run 不请求"})
            report["unmatched"].append(
                {"match_id": mid, "match_num": num, "match": f"{home} vs {away}",
                 "league": league, "reason": "dry_run"})
            continue
        # 日期窗口：开球日前后 2 天（get_odds 区间 ≤5 天）
        from datetime import datetime, timedelta
        try:
            dt = datetime.fromisoformat(kickoff.replace("Z", "+00:00"))
            d_from = (dt - timedelta(days=2)).strftime("%Y-%m-%d")
            d_to = (dt + timedelta(days=2)).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            report["unmatched"].append(
                {"match_id": mid, "match_num": num, "match": f"{home} vs {away}",
                 "league": league, "reason": f"bad_kickoff:{kickoff}"})
            continue
        params = urllib.parse.urlencode({
            "action": "get_odds", "APIkey": key,
            "league_id": lid, "from": d_from, "to": d_to,
        })
        odds_list = None
        last_err = None
        for attempt in range(4):  # apiv3 SSL 超时偶发，指数退避重试
            try:
                req = urllib.request.Request(f"https://apiv3.apifootball.com/?{params}",
                                             headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=60) as resp:
                    odds_list = json.loads(resp.read().decode("utf-8", "replace"))
                break
            except Exception as exc:
                last_err = f"{type(exc).__name__}: {str(exc)[:80]}"
                if attempt < 3:
                    time.sleep(3 * (attempt + 1))
        if odds_list is None:
            report["unmatched"].append(
                {"match_id": mid, "match_num": num, "match": f"{home} vs {away}",
                 "league": league, "reason": f"retry_failed:{last_err}"})
            continue
        if isinstance(odds_list, dict) and odds_list.get("error") is not None:
            report["unmatched"].append(
                {"match_id": mid, "match_num": num, "match": f"{home} vs {away}",
                 "league": league, "reason": f"api_error:{odds_list.get('message')}"})
            continue
        odds_list = odds_list if isinstance(odds_list, list) else []
        report["requests"].append({"league_id": lid, "league": league,
                                   "window": f"{d_from}~{d_to}", "odds_rows": len(odds_list)})
        if not odds_list:
            report["unmatched"].append(
                {"match_id": mid, "match_num": num, "match": f"{home} vs {away}",
                 "league": league, "reason": "no_apifootball_odds_in_window"})
            continue
        # 窗口内按队名过滤到具体场次（get_odds 返回整个联赛窗口的多场比赛）
        # 体彩短名是中文、国际盘名是英文：team_aliases 配置中文->英文别名，
        # 匹配时把别名英文名加入候选，与 events 返回的英文队名做归一化比对。
        aliases_cfg = config.get("team_aliases") or {}
        home_candidates = [home] + list(aliases_cfg.get(home, []))
        away_candidates = [away] + list(aliases_cfg.get(away, []))
        # get_events 拿窗口内场次的队名（同联赛、同日窗口），再按队名匹配
        ev_params = urllib.parse.urlencode({
            "action": "get_events", "APIkey": key,
            "league_id": lid, "from": d_from, "to": d_to,
        })
        ev_by_id = {}
        for attempt in range(4):  # apiv3 SSL 超时偶发，指数退避重试
            try:
                req = urllib.request.Request(f"https://apiv3.apifootball.com/?{ev_params}",
                                             headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=60) as resp:
                    ev_list = json.loads(resp.read().decode("utf-8", "replace"))
                if isinstance(ev_list, list):
                    for ev in ev_list:
                        ev_by_id[ev.get("match_id")] = (
                            ev.get("match_hometeam_name"), ev.get("match_awayteam_name"))
                break
            except Exception:
                if attempt < 3:
                    time.sleep(3 * (attempt + 1))
        matched_odds = []
        for o in odds_list:
            mid_apifb = str(o.get("match_id"))
            h_name, a_name = ev_by_id.get(mid_apifb, ("", ""))
            if h_name and a_name:
                # 有 events 数据：按队名匹配（候选含中文短名+英文别名）
                if name_hits(h_name, home_candidates) and name_hits(a_name, away_candidates):
                    matched_odds.append(o)
            else:
                # 无 events 数据：按窗口内唯一场次近似（仅当窗口内 match_id 唯一）
                if len({str(x.get("match_id")) for x in odds_list}) == 1:
                    matched_odds.append(o)
        if not matched_odds:
            report["unmatched"].append(
                {"match_id": mid, "match_num": num, "match": f"{home} vs {away}",
                 "league": league, "reason": "no_team_match_in_odds_window",
                 "window_match_ids": len({str(x.get('match_id')) for x in odds_list})})
            continue
        entry = {
            "match_id": mid, "match_num": num,
            "match": f"{home} vs {away}", "league": league,
            "apifootball_league_id": lid, "window": f"{d_from}~{d_to}",
            "apifootball_match_id": str(matched_odds[0].get("match_id")),
            "bookmakers": matched_odds,
        }
        report["matches"].append(entry)

    # 3) 落盘：快照 JSON + 追加 JSONL（dry-run 不写）
    if not a.dry_run and a.store:
        store = Path(a.store)
        store.mkdir(parents=True, exist_ok=True)
        line = {"schema": report["schema"], "provider": report["provider"],
                "ran_at": report["ran_at"], "matches": report["matches"]}
        with open(store / "intl_production.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
        report["store_file"] = str((store / "intl_production.jsonl").resolve())
    if a.out:
        Path(a.out).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
