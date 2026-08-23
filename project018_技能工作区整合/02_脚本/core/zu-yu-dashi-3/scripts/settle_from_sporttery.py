#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用体彩移动端官方赛果自动回填登记库。

流程：读 registry.jsonl → 找出缺 results/<match_id>.json 的预测
    → 按队名+开球日期匹配官方赛果 → 调 settle_result 写入。
只回填 matchStatusName=已完成 且有 sectionsNo999 的场次；未完成一律跳过。

用法：
  python3 settle_from_sporttery.py [--date YYYY-MM-DD] [--dry-run]
"""
import argparse, datetime, json, re, subprocess, sys, tempfile, time, urllib.parse, urllib.request
from pathlib import Path
from backtest_lib import load_jsonl

HERE = Path(__file__).parent

FIXED_API = "https://webapi.sporttery.cn/gateway/uniform/football/getFixedBonusV1.qry"
UA = {"User-Agent":"Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/134 Mobile Safari/537.36",
      "Referer":"https://m.sporttery.cn/mjc/zqsj/?tab=result", "Accept":"application/json,text/plain,*/*"}

# [中文功能] 队名归一化（去掉FC/队/俱乐部等噪声）
def norm(s):
    """队名归一：去掉FC/队/俱乐部等噪声，只留可比字符。"""
    s = re.sub(r'(FC|SK|CF|AC|队|俱乐部|足球)', '', str(s))
    return ''.join(c for c in s if c.isalnum())

# [中文功能] 中文简称相似判断（子串匹配）
def similar(a, b):
    """中文简称匹配：一方是另一方的子串即可（瓦勒伦加/瓦勒伦加、利勒斯特/利勒斯特罗姆）。"""
    a, b = norm(a), norm(b)
    if not a or not b: return False
    return a in b or b in a

# [中文功能] 调用官方赛果接口并返回结果列表
def fetch_results(date, out):
    subprocess.run([sys.executable, str(HERE / 'fetch_sporttery_full.py'),
                    '--results', '--output', str(out)] + (['--date', date] if date else []),
                   check=True, stdout=subprocess.DEVNULL)
    return json.load(open(out, encoding='utf-8'))['results']

# [中文功能] 按日期逐日拉取赛果并合并去重
def fetch_results_multi(dates, out):
    """官方 result 接口不带 matchDate 时只返回约10场的滚动窗口，
    会漏掉更早的待回填场次。故按待回填场次的开球日期逐日查询后合并去重。"""
    seen, merged = set(), []
    for d in dates:
        try:
            rows = fetch_results(d, out)
        except Exception:
            continue
        for r in rows:
            key = r.get('match_id') or (r.get('home'), r.get('away'), r.get('kickoff_local'))
            if key in seen: continue
            seen.add(key); merged.append(r)
    return merged


# [中文功能] 按官方 matchId 直查固定奖金接口拿赛果（不依赖按日期分组的 result 列表）
def fetch_fixed_by_id(mid):
    """getFixedBonusV1 按 matchId 返回赛果；sectionsNo999=全场90分钟、sectionsNo1=半场。
    无效场次/未完成返回 finished=False。"""
    url = FIXED_API + "?" + urllib.parse.urlencode({"clientCode": 3001, "matchId": mid})
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.load(r)
    v = d.get("value") or {}
    s999 = str(v.get("sectionsNo999") or "").strip()
    if not s999 or s999 in ("无效场次", "-1:-1", "0:0:0"):
        return {"match_id": str(mid), "finished": False, "score_90": None,
                "score_ht": None, "status_name": v.get("matchStatusName")}
    s1 = str(v.get("sectionsNo1") or "").strip()
    return {"match_id": str(mid), "finished": True,
            "score_90": s999.replace(":", "-"),
            "score_ht": s1.replace(":", "-") or None,
            "status_name": v.get("matchStatusName")}


def filter_pending_by_date(pending, only_date):
    """Apply the requested local kickoff-date scope before any remote lookup."""
    if not only_date:
        return list(pending)
    return [row for row in pending
            if str(row.get("kickoff") or "")[:10] == str(only_date)]

# [中文功能] 按官方赛果自动回填登记库
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--store', default='C:/Users/Administrator/.codex/skills/football-quant-fusion-suite/shared/zu-yu-dashi-3/backtest')
    ap.add_argument('--date', help='只回填该 business_date')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    root = Path(a.store)

    pending = []
    for e in load_jsonl(root / 'registry.jsonl'):
        mid = e['match_id']
        if (root / 'results' / (mid + '.json')).exists(): continue
        p = Path(e['path'])
        if not p.exists(): continue
        rec = json.load(open(p, encoding='utf-8'))
        meta = (rec.get('input') or {}).get('sporttery_meta') or {}
        m = rec.get('match') or {}
        if not m:  # 旧格式：队名在 output.match，形如 "主队 vs 客队"
            o = rec.get('output') or {}
            parts = str(o.get('match', '')).split(' vs ')
            if len(parts) == 2:
                m = {'home': parts[0], 'away': parts[1],
                     'kickoff': (rec.get('input') or {}).get('kickoff', '')}
        if not m.get('home'):
            continue
        if mid not in [x['match_id'] for x in pending]:
            pending.append({'match_id': mid, 'home': m['home'], 'away': m['away'],
                            'kickoff': m.get('kickoff') or '', 'path': str(p),
                            'sporttery_id': meta.get('match_id')})

    # Apply the date scope before both date queries and matchId direct lookup.
    # The direct lookup is authoritative, but must not bypass --date.
    pending = filter_pending_by_date(pending, a.date)

    # 按待回填场次的开球日期逐日查询，覆盖官方滚动窗口之外的历史场次
    if a.date:
        query_dates = [a.date]
    else:
        ds = sorted({(p['kickoff'] or '')[:10] for p in pending if (p['kickoff'] or '')[:10]})
        # 官方 matchDate 按当地开球日归档，同时查前一日以覆盖跨零点场次
        extra = set()
        for d in ds:
            try:
                extra.add((datetime.date.fromisoformat(d) - datetime.timedelta(days=1)).isoformat())
            except ValueError:
                pass
        query_dates = sorted(set(ds) | extra) or [None]
    # Windows 兼容：原包硬编码 POSIX /tmp 路径（Linux 导出遗留），
    # 在 Windows 上解析为 \tmp\_settle_results.json 导致 FileNotFoundError。
    # 改为系统临时目录，保证官方赛果滚动窗口可落盘。
    results = fetch_results_multi(query_dates, Path(tempfile.gettempdir()) / '_settle_results.json')
    done = [r for r in results if r['finished'] and r['score_90']]

    # 按 matchId 直查固定奖金接口（可靠路径）：官方 result 列表按业务日期归档，
    # 开球日与业务日不一致时按日期查询会漏场；直查不依赖日期分组。
    direct = []
    for pd in pending:
        sid = pd.get('sporttery_id')
        if sid is None:
            continue
        try:
            row = fetch_fixed_by_id(sid)
        except Exception:
            continue
        if row.get("finished") and row.get("score_90"):
            direct.append(row)
        time.sleep(0.35)
    if direct:
        print(f"[settle] matchId 直查命中 {len(direct)} 场（补日期分组漏项）", file=sys.stderr)

    report = []
    for pd in pending:
        day = (pd['kickoff'] or '')[:10]
        # 优先用官方 matchId 精确匹配，无 ID 的旧记录才回退到队名模糊匹配
        hit = None
        if pd.get('sporttery_id'):
            sid = str(pd['sporttery_id'])
            hit = next((r for r in direct if str(r['match_id']) == sid), None)
            if hit:
                match_by = 'fixed_by_id'
        if not hit and pd.get('sporttery_id'):
            hit = next((r for r in done if str(r['match_id']) == str(pd['sporttery_id'])), None)
            if hit:
                match_by = 'official_match_id'
        if not hit:
            hit = next((r for r in done
                        if similar(pd['home'], r['home']) and similar(pd['away'], r['away'])
                        and (not day or day in (r['kickoff_local'] or ''))), None)
            if hit:
                match_by = 'name_fuzzy'
        if not hit:
            report.append({'match_id': pd['match_id'], 'status': 'no_result_yet',
                           'match': f"{pd['home']} vs {pd['away']}"}); continue
        if a.dry_run:
            report.append({'match_id': pd['match_id'], 'status': 'would_settle',
                           'match': f"{pd['home']} vs {pd['away']}",
                           'matched_by': match_by, 'score_90': hit['score_90']}); continue
        r = subprocess.run([sys.executable, str(HERE / 'settle_result.py'),
                            '--match-id', pd['match_id'], '--score-90', hit['score_90'],
                            *(('--score-ht', hit['score_ht']) if hit.get('score_ht') else ()),
                            '--source', '中国体彩网移动端官方赛果',
                            '--source-url', 'https://m.sporttery.cn/mjc/zqsj/',
                            '--store', a.store], capture_output=True, text=True)
        report.append({'match_id': pd['match_id'], 'match': f"{pd['home']} vs {pd['away']}",
                       'matched_by': match_by, 'score_90': hit['score_90'],
                       'status': 'settled' if r.returncode == 0 else 'failed',
                       'err': r.stderr.strip()[:120] if r.returncode else None})

    print(json.dumps({'pending': len(pending), 'official_finished': len(done),
                      'settled': sum(1 for x in report if x['status'] == 'settled'),
                      'report': report}, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
