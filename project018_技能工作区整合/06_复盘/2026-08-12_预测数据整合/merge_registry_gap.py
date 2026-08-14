# -*- coding: utf-8 -*-
"""P2-2 registry 哈希链合并（2026-08-12，一次性迁移工具）。

背景：仓库内 registry（1550 条）比外部套件（1555 条）少 8 条预测登记
（sporttery-2040812~2040818、2040830，2026-08-11 11:02 UTC 一批，外部链尾部）。
外部 8 条 entry 的 previous_hash 链起点 = 仓库内 2040829 的 entry_hash，
插入点 = 仓库内 2040829 之后、2040831 之前。

约束（AGENTS.md）：entry_hash = sha(previous_hash + record_hash) 逐行链式，
插入后必须从插入点重算后续所有 entry 的 previous_hash 与 entry_hash，
否则链断裂、可验证性破坏。record_hash 不变（预测文件内容不变）。

流程：
1. 备份仓库内 registry.jsonl
2. 复制 8 条预测文件到仓库内 predictions/2026/08/（改 path 为仓库内）
3. 8 条 entry 按外部链顺序插入（保持 record_hash/created_at，path 指向仓库内副本）
4. 从插入点之后第一条开始重算 previous_hash + entry_hash
5. 验证：全链 1558 条 entry_hash 链式自洽 + 外部 8 条 record_hash 不变
"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, r"F:\HM足球比赛预测\project018_技能工作区整合\02_脚本\core\zu-yu-dashi-3\scripts")
from backtest_lib import sha  # noqa: E402

REPO_BASE = Path(r"F:\HM足球比赛预测\project018_技能工作区整合\04_素材\shared-data\football-quant-fusion\backtest")
EXT_BASE = Path(r"C:\Users\Administrator\.codex\skills\football-quant-fusion-suite\shared\football-quant-fusion\backtest")

GAP_IDS = [f"sporttery-204081{i}" for i in range(2, 9)] + ["sporttery-2040830"]


def load_jsonl(p: Path):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def main():
    repo_reg = REPO_BASE / "registry.jsonl"
    ext_reg = EXT_BASE / "registry.jsonl"
    repo = load_jsonl(repo_reg)
    ext = load_jsonl(ext_reg)
    print(f"repo={len(repo)} ext={len(ext)}")

    # 1. 备份
    bak = repo_reg.with_suffix(".jsonl.bak_20260812_merge8")
    if not bak.exists():
        bak.write_bytes(repo_reg.read_bytes())
    print("backup=", bak.name)

    # 2. 取外部 8 条（按外部链顺序）
    ext_by_id = {r["match_id"]: r for r in ext}
    gap = []
    for mid in GAP_IDS:
        r = ext_by_id.get(mid)
        if not r:
            raise SystemExit(f"外部链缺 {mid}")
        gap.append(r)
    # 外部链顺序 = created_at 升序
    gap.sort(key=lambda r: r["created_at"])
    print("gap_entries=", [r["match_id"] for r in gap])

    # 3. 复制预测文件到仓库内
    copied = []
    for r in gap:
        src = Path(r["path"])
        if not src.exists():
            raise SystemExit(f"外部预测文件缺失: {src}")
        dst = REPO_BASE / "predictions" / "2026" / "08" / src.name
        if not dst.exists():
            shutil.copy2(src, dst)
        # 验证 record_hash 一致（内容不变）
        rec = json.loads(dst.read_text(encoding="utf-8"))
        if sha(rec) != r["record_hash"]:
            raise SystemExit(f"record_hash 不一致: {r['match_id']}")
        copied.append(dst)
    print("prediction_files_copied=", len(copied))

    # 4. 定位插入点：仓库内 2040829 的 index
    idx = next(i for i, r in enumerate(repo) if r["match_id"] == "sporttery-2040829")
    print("insert_after_index=", idx, "match=", repo[idx]["match_id"])
    assert repo[idx]["entry_hash"] == gap[0]["previous_hash"], \
        "外部8条 previous_hash 起点 != 仓库内 2040829 entry_hash —— 拓扑不符，中止"

    # 5. 构造新 entry（path 改仓库内；record_hash/created_at 保持外部原值）
    new_entries = []
    for r, dst in zip(gap, copied):
        e = {
            "prediction_id": r["prediction_id"],
            "match_id": r["match_id"],
            "path": str(dst),
            "record_hash": r["record_hash"],
            "previous_hash": r["previous_hash"],  # 链内会重算
            "created_at": r["created_at"],
        }
        e["entry_hash"] = sha(e["previous_hash"] + e["record_hash"])
        new_entries.append(e)

    # 6. 拼接并重算插入点之后所有 entry
    merged = repo[: idx + 1] + new_entries + repo[idx + 1:]
    # 从第一条 new entry 开始重算 previous/entry hash
    for i in range(idx + 1, len(merged)):
        prev_hash = merged[i - 1]["entry_hash"]
        merged[i]["previous_hash"] = prev_hash
        merged[i]["entry_hash"] = sha(prev_hash + merged[i]["record_hash"])

    # 7. 验证整链
    for i in range(1, len(merged)):
        if merged[i]["previous_hash"] != merged[i - 1]["entry_hash"]:
            raise SystemExit(f"链断裂 at {i}: {merged[i]['match_id']}")
        if merged[i]["entry_hash"] != sha(merged[i]["previous_hash"] + merged[i]["record_hash"]):
            raise SystemExit(f"entry_hash 错误 at {i}: {merged[i]['match_id']}")
    print("chain_verified=ok total=", len(merged))

    # 8. 落盘（原子：先写临时再替换）
    tmp = repo_reg.with_suffix(".jsonl.tmp_merge8")
    with open(tmp, "w", encoding="utf-8") as f:
        for e in merged:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    tmp.replace(repo_reg)
    print("registry_merged=", len(merged))

    # 9. 输出汇总
    print(json.dumps({
        "status": "merged",
        "repo_before": len(repo), "added": len(new_entries), "repo_after": len(merged),
        "insert_after": "sporttery-2040829", "insert_before": "sporttery-2040831",
        "backup": str(bak),
    }, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
