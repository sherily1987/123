#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apifootball 官方模型概率 -> fusion 引擎 lambda_prior 特征注入器 (2026-08-08)

把 MCP get_football_predictions 的官方数学模型概率(主/平/客%)反解成 Dixon-Coles
泊松参数 (λ主, λ客), 作为 lambda_prior 注入 input.json 的对应场次, 让 fusion 核心
联合拟合(market_fit.fit)把官方模型作为独立特征参与 —— 软约束, 默认权重 0.02
(market_fit.W_PRIOR), 可用 --weight 调强度。

用法:
  python mcp_model_adapter.py --input input.json --output input_mcp.json
  python mcp_model_adapter.py --input input.json --output input_mcp.json --weight 0.05
  python mcp_model_adapter.py --input input.json --output input_mcp.json --limit 3   # 测试前3场

流程:
  1. 读 input.json (UTF-8 BOM)
  2. 对每场: 按 联赛+开球时间(±3h) 匹配 apifootball 比赛 (复用 mcp_evidence 的映射与匹配)
  3. 拉 get_football_predictions (UTC 日期口径 + match_id, 与 mcp_evidence 同坑)
  4. 官方概率 -> 核心 solve_lam_from_probs (Dixon-Coles 反解) -> (λ主, λ客)
  5. 注入 match dict: lambda_prior + assumptions 注记原始概率
  6. 写 output (仅注入成功场次加字段, 其余原样)
  7. 打印摘要

依赖: mcp_query.py (MCP 调用内核) + mcp_evidence.py (联赛映射/匹配) + zu-yu-dashi-3/scripts/predict.py (反解)
环境变量: MCP_APIFOOTBALL_API_KEY
注意: apifootball MCP 服务器慢(20-60s/次); 官方模型对部分联赛无预测(No probabilities found) -> 跳过该场
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for _p in (r"F:\HM足球比赛预测", r"C:\Users\Administrator\football-llm-predictor"):
    if os.path.isdir(_p):
        sys.path.insert(0, _p)

from mcp_evidence import (  # noqa: E402  复用映射/匹配/UTC日期工具, 不重复实现
    LEAGUE_KEYWORDS, mcp_tool, match_raw_to_candidates, parse_bj, to_bj, utc_date,
)

# 55联赛套餐内已验证的 league_id (中文联赛名 -> apifootball league_id)
LEAGUE_IDS = {
    "芬超": 352, "挪超": 253, "瑞超": 307, "荷甲": 244, "葡超": 266,
    "欧冠": 3, "欧罗巴": 4, "欧协联": 683, "苏超": 279, "德甲": 175,
    "西甲": 302, "英超": 152, "意甲": 207, "法甲": 168,
}

from runtime_paths import core_scripts_dir

ZUYU_SCRIPTS = str(core_scripts_dir())
if os.path.isdir(ZUYU_SCRIPTS):
    sys.path.insert(0, ZUYU_SCRIPTS)


def solve_lambda(probs):
    """官方概率 [p1,px,p2] -> (λ主, λ客) 或 None。用核心 Dixon-Coles 反解。"""
    try:
        import predict as zuyu
    except ImportError as e:
        print(f"  ✗ 无法 import 核心 predict.py: {e}")
        return None
    p = [float(probs[0]) / 100.0, float(probs[1]) / 100.0, float(probs[2]) / 100.0]
    if not (0 < p[0] < 1 and 0 < p[1] < 1 and 0 < p[2] < 1):
        return None
    try:
        r = zuyu.solve_lam_from_probs(p)
    except Exception as e:
        print(f"  ✗ 反解失败: {e}")
        return None
    if not r:
        return None
    lh, la = r
    if not (0.05 <= lh <= 6 and 0.05 <= la <= 6):  # 核心 lambda_prior 校验范围
        return None
    return lh, la


def main():
    ap = argparse.ArgumentParser(description="apifootball 官方模型概率 -> lambda_prior 注入器")
    ap.add_argument("--input", required=True, help="fusion input.json (采集器产物)")
    ap.add_argument("--output", required=True, help="输出 input_mcp.json (给 fusion_predict 用)")
    ap.add_argument("--weight", type=float, default=0.02, help="先验权重 (默认0.02=market_fit.W_PRIOR)")
    ap.add_argument("--mode", default=None,
                    help="覆盖 mode: market_only|hybrid (默认保持 input.json 原值)。"
                         "market_only: 先验只作用于衍生盘(比分/大小球/BTTS)λ, 1X2固定为市场; "
                         "hybrid: 先验同时拉动 1X2 (独立事实修正生效)")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 场 (测试用)")
    ap.add_argument("--workers", type=int, default=3, help="MCP 并发数")
    args = ap.parse_args()

    # ---- 1. 读 input.json (UTF-8 BOM 兼容) ----
    for enc in ("utf-8-sig", "utf-8"):
        try:
            with open(args.input, encoding=enc) as f:
                data = json.load(f)
            break
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    ms = data.get("matches", []) if isinstance(data, dict) else data
    print(f"📋 input.json 场次: {len(ms)}")
    if args.limit:
        ms = ms[:args.limit]

    # ---- 2. 拉 apifootball 比赛候选 ----
    kicks = []
    for m in ms:
        t = parse_bj(str(m.get("kickoff", ""))[:16].replace("T", " "))
        if t:
            kicks.append(t)
    if not kicks:
        print("✗ 没有可解析的 kickoff")
        return 1
    d_from = (min(kicks) - timedelta(days=1)).strftime("%Y-%m-%d")
    d_to = (max(kicks) + timedelta(days=1)).strftime("%Y-%m-%d")
    print(f"🔭 按联赛拉取 apifootball 比赛 {d_from} ~ {d_to} (league_id 过滤, 绕开50条截断) ...")
    cands = []
    comps = sorted(set(m.get("competition", "") for m in ms))
    for comp in comps:
        lid = LEAGUE_IDS.get(comp)
        if not lid:
            print(f"   {comp}: 无 league_id 映射(套餐外/未验证), 跳过")
            continue
        r = mcp_tool("get_football_matches", {"date_from": d_from, "date_to": d_to,
                                              "league_id": str(lid)})
        part = r if isinstance(r, list) else r.get("matches", [])
        cands.extend(part)
        print(f"   {comp}({lid}): {len(part)} 场")
    print(f"   候选合计 {len(cands)} 场")

    # ---- 3. 匹配 (复用 mcp_evidence 逻辑: input match -> 其期望的 raw 形态) ----
    fake_raw = [{"league": m.get("competition", ""), "home": m.get("home", ""),
                 "away": m.get("away", ""),
                 "kickoff_local": str(m.get("kickoff", ""))[:16].replace("T", " "),
                 "match_id": (m.get("sporttery_meta") or {}).get("match_id", "")}
                for m in ms]
    pairs = match_raw_to_candidates(fake_raw, cands)

    # ---- 4. 并发拉官方模型预测 ----
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import threading
    lock = threading.Lock()
    preds = {}

    def fetch(ri, mid):
        d = None
        for c in cands:
            if str(c.get("match_id")) == str(mid):
                d = c.get("kickoff_utc", "")[:10]
                break
        if not d:
            d = (parse_bj(str(ms[ri].get("kickoff", ""))[:16].replace("T", " ")) - timedelta(hours=8)).strftime("%Y-%m-%d")
        try:
            r = mcp_tool("get_football_predictions", {"date_from": d, "date_to": d, "match_id": mid})
            pl = (r or {}).get("predictions") or []
            with lock:
                preds[ri] = pl[0] if pl else None
                print(f"  ✓ preds {mid}: {pl[0].get('home_win_pct') if pl else '无'}")
        except Exception as e:
            with lock:
                preds[ri] = None
                print(f"  ✗ preds {mid}: {e}")

    tasks = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for ri, cand in pairs:
            fraw = fake_raw[ri]
            if cand:
                print(f"  第{ri+1}场 {fraw['home']} vs {fraw['away']} -> "
                      f"{cand.get('home_team')} vs {cand.get('away_team')} "
                      f"(id={cand.get('match_id')}, utc={cand.get('kickoff_utc')})")
                tasks.append(ex.submit(fetch, ri, cand.get("match_id")))
            else:
                preds[ri] = None
                print(f"⚠️ 第{ri+1}场 {fraw['home']} vs {fraw['away']} ({fraw['league']}) 未匹配到 apifootball 比赛")
        for t in as_completed(tasks):
            t.result()

    # ---- 5. 注入 lambda_prior ----
    injected = 0
    for ri, cand in pairs:
        fraw = fake_raw[ri]
        if not cand:
            continue
        pr = preds.get(ri)
        if not pr:
            continue
        try:
            hp, dp, ap_ = float(pr["home_win_pct"]), float(pr["draw_pct"]), float(pr["away_win_pct"])
        except (KeyError, TypeError, ValueError):
            continue
        lam = solve_lambda([hp, dp, ap_])
        if not lam:
            print(f"  ✗ 第{ri+1}场 {fraw['home']} vs {fraw['away']}: 官方概率({hp}/{dp}/{ap_}) 反解λ失败, 跳过")
            continue
        lh, la = lam
        m = ms[ri]
        if args.mode:
            m["mode"] = args.mode  # 覆盖模式: hybrid 时先验拉动 1X2
        m["lambda_prior"] = {
            "lambda_home": round(lh, 3),
            "lambda_away": round(la, 3),
            "weight": args.weight,
            "source": f"apifootball官方模型(MCP) 主{hp:.0f}%/平{dp:.0f}%/客{ap_:.0f}% favorite={pr.get('favorite')}",
        }
        m.setdefault("assumptions", []).append(
            f"官方模型先验(MCP): 主{hp:.0f}%/平{dp:.0f}%/客{ap_:.0f}% -> λ({lh:.2f},{la:.2f}) w={args.weight}")
        injected += 1
        print(f"  ✓ 第{ri+1}场 {fraw['home']} vs {fraw['away']}: 官方概率 {hp:.0f}/{dp:.0f}/{ap_:.0f} "
              f"-> λ主{lh:.2f}/λ客{la:.2f} (w={args.weight})")

    # ---- 6. 写输出 (保持 BOM, 与套件一致) ----
    with open(args.output, "w", encoding="utf-8-sig") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"\n✅ 注入 {injected}/{len(ms)} 场 -> {args.output}")
    print("   下一步: python fusion_predict.py <output> --output model_output.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
