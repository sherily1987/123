#!/usr/bin/env python3
"""把「汉堡 vs 勒沃库森 2026-01-14」标记为取消/无效场（无赛果可回填）。

体彩 sectionsNo999=无效场次；apifootball.com 德甲(league_id=175) 01-13/14 均无此对阵，
确认比赛不存在/取消。写 status=cancelled 的 results 文件 + 更新 results_registry，
让评测脚本（score_record / validate_90min_settlement）正确跳过该场，不再计为待回测。
"""
import json
import sys
from pathlib import Path

CORE = Path(r"F:\HM足球比赛预测\project018_技能工作区整合\02_脚本\core\zu-yu-dashi-3\scripts")
STORE = Path(r"F:\HM足球比赛预测\project018_技能工作区整合\04_素材\shared-data\football-quant-fusion\backtest")
sys.path.insert(0, str(CORE))
from backtest_lib import now, sha, atomic_json, append_jsonl  # noqa: E402

MID = "sporttery-2036932"
rp = STORE / "results" / f"{MID}.json"
if rp.exists():
    print(json.dumps({"status": "exists", "match_id": MID}, ensure_ascii=False))
    sys.exit(0)

rec = {
    "schema_version": "1.1",
    "match_id": MID,
    "status": "cancelled",
    "score_ht": None,
    "score_90": None,
    "score_et": None,
    "penalty_winner": None,
    "advanced": None,
    "settlement_scope": "90min",
    "source": {
        "name": "体彩官方无效场次 + apifootball.com 德甲赛程复核",
        "url": "https://m.sporttery.cn/mjc/zqsj/",
        "observed_at": now(),
    },
    "revision": 1,
    "cancel_note": ("汉堡 vs 勒沃库森 2026-01-14 德甲：体彩 sectionsNo999=无效场次；"
                    "apifootball.com 德甲(league_id=175) 2026-01-13/14 赛程均无此对阵，"
                    "比赛不存在/取消，无 90 分钟赛果可回填。"),
}
atomic_json(rp, rec)
append_jsonl(STORE / "results_registry.jsonl", {
    "match_id": MID, "path": str(rp), "hash": sha(rec), "created_at": now(),
    "status": "cancelled",
})
print(json.dumps({"status": "cancelled", "match_id": MID, "path": str(rp)},
                 ensure_ascii=False, indent=2))
