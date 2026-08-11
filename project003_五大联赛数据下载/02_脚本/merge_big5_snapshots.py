#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""体彩快照 × football-data 46696 场五大联赛：去重、合并、分联赛。

规则（按用户要求）：
  1. 两套数据按 (联赛, 开球日期+时间, 主队, 客队) 做跨源去重合并；
  2. 队名跨语言匹配靠"同联赛同日同时刻恰有一场对一场"自动挖掘的中英文别名表，
     挖掘不到的样本不去强行删除（有的样本缺少数据不用管，去重合并即可）；
  3. 同一场比赛同时存在于两套数据时，体彩快照字段（中文队名/盘口快照/赛果）为主，
     football-data 字段（season/div/actual/odds/raw）并入同一记录；
  4. 缺字段的样本一律保留，不按完整度过滤；
  5. 按联赛输出独立 JSONL。

用法：python merge_big5_snapshots.py
"""
import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

SHARED = Path(
    r"C:\Users\Administrator\.codex\skills\football-quant-fusion-suite\shared\football-quant-fusion"
)
FD_JSON = Path(
    r"C:\Users\Administrator\.codex\skills\football-quant-fusion-suite\shared\zu-yu-dashi-3\datasets\football_data_big5_backtest.json"
)
SP_DIR = SHARED / "backtest" / "snapshots" / "by_league"
OUT_DIR = SHARED / "datasets" / "merged_big5"

LEAGUES = ["英超", "西甲", "意甲", "法甲", "德甲"]
COUNTRY = {"英超": "UK", "西甲": "EU", "意甲": "EU", "法甲": "EU", "德甲": "EU"}


def _last_sunday(year, month):
    d = date(year, month, 31)
    while d.weekday() != 6:
        d -= timedelta(days=1)
    return d


def fd_to_beijing(kickoff, country):
    """football-data 开球时间统一为英国时间，换算成北京时间墙钟（对齐体彩口径）。

    英国冬令时(GMT) +8h / 夏令时(BST) +7h；夏令时：3月最后一个周日至10月最后一个周日。
    """
    text = str(kickoff or "").replace("Z", "")
    if len(text) < 16:
        return text
    dt = datetime.fromisoformat(text[:16])
    dst = 1 if (_last_sunday(dt.year, 3) <= dt.date() < _last_sunday(dt.year, 10)) else 0
    return (dt + timedelta(hours=8 - dst)).isoformat()


def norm(name):
    """队名归一：去大小写与所有非字母数字字符（中文保留）。"""
    return "".join(c.lower() for c in str(name or "") if c.isalnum())


def kick_parts(kickoff):
    """返回 (日期YYYY-MM-DD, HH:MM)；兼容带时区/不带时区格式。"""
    text = str(kickoff or "").replace("Z", "")
    date = text[:10]
    time = text[11:16] if len(text) >= 16 else ""
    return date, time


def load_fd():
    data = json.loads(FD_JSON.read_text(encoding="utf-8-sig"))
    matches = [m for m in data["matches"] if m.get("competition") in LEAGUES]
    # 源内去重：match_uid 唯一
    seen = set()
    out = []
    for m in matches:
        uid = m.get("match_uid") or f"{m.get('competition')}|{m.get('home')}|{m.get('away')}|{m.get('kickoff')}"
        if uid in seen:
            continue
        seen.add(uid)
        m["_kickoff_beijing"] = fd_to_beijing(m.get("kickoff"), COUNTRY.get(m.get("competition"), "EU"))
        out.append(m)
    return out


def load_sp():
    out = []
    for lg in LEAGUES:
        p = SP_DIR / f"{lg}.jsonl"
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8-sig").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            rec["_league"] = lg
            out.append(rec)
    # 源内去重：match_id 唯一
    seen = set()
    uniq = []
    for rec in out:
        mid = rec.get("match_id") or f"{rec.get('_league')}|{rec.get('home')}|{rec.get('away')}|{rec.get('kickoff')}"
        if mid in seen:
            continue
        seen.add(mid)
        uniq.append(rec)
    return uniq


def mine_aliases(fd_by_key, sp_by_key):
    """自动挖掘中英文队名别名：同联赛、同(日期,时刻)且两源各仅一场时互为别名。"""
    alias = defaultdict(dict)  # league -> {norm_en: norm_cn, norm_cn: norm_en}
    for lg in LEAGUES:
        fd_map = defaultdict(list)
        for m in fd_by_key[lg]:
            fd_map[(m["_date"], m["_time"])].append(m)
        sp_map = defaultdict(list)
        for m in sp_by_key[lg]:
            sp_map[(m["_date"], m["_time"])].append(m)
        for k in set(fd_map) & set(sp_map):
            fds, sps = fd_map[k], sp_map[k]
            if len(fds) == 1 and len(sps) == 1:
                alias[lg][norm(fds[0]["home"])] = norm(sps[0]["home"])
                alias[lg][norm(fds[0]["away"])] = norm(sps[0]["away"])
    return {lg: {k: v for k, v in d.items()} for lg, d in alias.items()}


def canonical(league, name, alias):
    """统一队名canonical：中文名保持自身，英文名查别名表转中文（查不到保留原名）。"""
    if any("\u4e00" <= ch <= "\u9fff" for ch in str(name or "")):
        return norm(name)
    n = norm(name)
    return alias.get(league, {}).get(n, n)


def build_key(league, home, away, date, time, alias):
    return (league, date, time, canonical(league, home, alias), canonical(league, away, alias))


def merge_records(fd, sp):
    """同一场比赛的两套记录合并：体彩字段为主，football-data 字段并入。"""
    base = dict(sp) if sp else dict(fd)
    base["sources"] = (["sporttery"] if sp else []) + (["football-data"] if fd else [])
    base["kickoff_date"] = (sp or fd)["_date"]
    if sp and fd:
        base["home_cn"], base["away_cn"] = sp["home"], sp["away"]
        base["home_en"], base["away_en"] = fd["home"], fd["away"]
        base["home"], base["away"] = sp["home"], sp["away"]
        base["match_uid"] = fd.get("match_uid")
        base["season"] = fd.get("season")
        base["div"] = fd.get("div")
        base["actual"] = fd.get("actual")
        base["fd_odds"] = fd.get("odds")
        base["football_data"] = fd.get("football_data")
        base["fd_kickoff"] = fd.get("kickoff")
        base["_league"] = fd.get("competition") or sp.get("_league")
    return base


def main():
    fd_all = load_fd()
    sp_all = load_sp()
    print(f"输入：football-data={len(fd_all)}（源内去重后） 体彩快照={len(sp_all)}（源内去重后）")

    fd_by_key = defaultdict(list)
    for m in fd_all:
        d, t = kick_parts(m.get("_kickoff_beijing") or m.get("kickoff"))
        m["_date"], m["_time"] = d, t
        m["_league"] = m.get("competition")
        fd_by_key[m["_league"]].append(m)
    sp_by_key = defaultdict(list)
    for m in sp_all:
        d, t = kick_parts(m.get("kickoff"))
        m["_date"], m["_time"] = d, t
        sp_by_key[m["_league"]].append(m)

    alias = mine_aliases(fd_by_key, sp_by_key)
    n_alias = sum(len(v) for v in alias.values())
    print(f"挖掘到中英文队名别名 {n_alias} 条")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    summary = {"input": {"football_data": len(fd_all), "sporttery": len(sp_all)},
               "aliases_mined": n_alias, "leagues": {}}
    (OUT_DIR / "team_alias.json").write_text(
        json.dumps(alias, ensure_ascii=False, indent=2), encoding="utf-8")

    total_merged = 0
    for lg in LEAGUES:
        merged = {}
        n_fd = n_sp = n_cross = n_fd_only = n_sp_only = 0
        for m in fd_by_key.get(lg, []):
            key = build_key(lg, m["home"], m["away"], m["_date"], m["_time"], alias)
            merged.setdefault(key, {"_fd": m, "_sp": None})
            n_fd += 1
        for m in sp_by_key.get(lg, []):
            key = build_key(lg, m["home"], m["away"], m["_date"], m["_time"], alias)
            entry = merged.setdefault(key, {"_fd": None, "_sp": m})
            entry["_sp"] = m
            n_sp += 1
        rows = []
        for key, entry in merged.items():
            rec = merge_records(entry["_fd"], entry["_sp"]) if entry["_fd"] and entry["_sp"] \
                else merge_records(entry["_fd"] or {}, entry["_sp"] or {})
            if entry["_fd"] and entry["_sp"]:
                n_cross += 1
            elif entry["_fd"]:
                n_fd_only += 1
            else:
                n_sp_only += 1
            rows.append(rec)
        rows.sort(key=lambda r: (r.get("kickoff_date") or "", str(r.get("home") or "")))
        out = OUT_DIR / f"{lg}.jsonl"
        with out.open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        total_merged += len(rows)
        summary["leagues"][lg] = {
            "football_data": n_fd, "sporttery": n_sp,
            "merged_total": len(rows),
            "cross_source_same_match": n_cross,
            "football_data_only": n_fd_only,
            "sporttery_only": n_sp_only,
            "file": str(out),
        }
        print(f"{lg}: fd={n_fd} sp={n_sp} 合并后={len(rows)} 跨源同场={n_cross} "
              f"(fd独有={n_fd_only} sp独有={n_sp_only})")

    summary["merged_total"] = total_merged
    (OUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"输出目录：{OUT_DIR}，合并后总记录 {total_merged}")


if __name__ == "__main__":
    main()
