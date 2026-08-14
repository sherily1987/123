#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键导出 football-quant-fusion 技能包给 Hermes 使用。

用法:
    python export_skill_for_hermes.py                # 默认导出 + 路径改写 + 打包 zip
    python export_skill_for_hermes.py --with-datasets # 额外带上大数据训练集(约1.2GB)
    python export_skill_for_hermes.py --no-rewrite    # 不改写脚本内绝对路径(仅本机用)
    python export_skill_for_hermes.py --no-zip        # 只更新目录不打包

导出的包结构:
    01_技能本体/football-quant-fusion/   SKILL.md + config + references + scripts
    02_核心引擎依赖/zu-yu-dashi-3/       核心库(backtest_lib/market_fit/predict 等)
    03_共享数据/football-quant-fusion/   datasets(精选) + odds + 运行时目录骨架
    04_示例/                             单场示例输入 + 运行示例说明
    05_单文件手册/SKILL_完整手册.md       全文合并版(给只能粘贴文本的 Hermes)
    dist/*.zip                           打包产物
"""

import argparse
import json
import shutil
import sys
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(r"F:\HM足球比赛预测\project017_football-quant-fusion技能导出")

SRC_SKILL = Path(r"C:\Users\Administrator\.codex\skills\football-quant-fusion")
SRC_CORE = Path(
    r"C:\Users\Administrator\.codex\skills\football-quant-fusion-suite\skills\zu-yu-dashi-3"
)
SRC_SHARED = Path(
    r"C:\Users\Administrator\.codex\skills\football-quant-fusion-suite\shared\football-quant-fusion"
)
SRC_TODAY_INPUT = Path(
    # project014 已于 2026-08-12 归档到 90_归档/，样例输入随之搬迁；仅用于导出包里的
    # demo 样例，不是生产数据依赖，路径失效只会让导出脚本报错，不影响实际预测链路。
    r"F:\HM足球比赛预测\90_归档\project014_football-quant-fusion\04_素材\2026-08-06_今日竞彩预测\input_20260806.json"
)

SKILL_DIR = PROJECT_ROOT / "01_技能本体" / "football-quant-fusion"
CORE_DIR = PROJECT_ROOT / "02_核心引擎依赖" / "zu-yu-dashi-3"
SHARED_DIR = PROJECT_ROOT / "03_共享数据" / "football-quant-fusion"
EXAMPLE_DIR = PROJECT_ROOT / "04_示例"
MANUAL_DIR = PROJECT_ROOT / "05_单文件手册"
DIST_DIR = PROJECT_ROOT / "dist"

ZIP_NAME = "football-quant-fusion-skill-hermes-v1.4.0.zip"

# 路径改写表：先长后短，先专后泛，保证不误替换
def build_rewrites():
    shared = str(SHARED_DIR)
    core = str(CORE_DIR)
    skill = str(SKILL_DIR)
    suite = str(PROJECT_ROOT / "02_核心引擎依赖")
    return [
        (
            r"C:\Users\Administrator\.codex\skills\football-quant-fusion-suite\shared\football-quant-fusion",
            shared,
        ),
        (
            r"C:/Users/Administrator/.codex/skills/football-quant-fusion-suite/shared/football-quant-fusion",
            shared,
        ),
        (
            r"C:\Users\Administrator\.codex\skills\football-quant-fusion-suite\skills\zu-yu-dashi-3",
            core,
        ),
        (
            r"C:/Users/Administrator/.codex/skills/football-quant-fusion-suite/skills/zu-yu-dashi-3",
            core,
        ),
        (r"C:\Users\Administrator\.codex\skills\football-quant-fusion-suite", suite),
        (r"C:/Users/Administrator/.codex/skills/football-quant-fusion-suite", suite),
        (r"C:\Users\Administrator\.codex\skills\football-quant-fusion", skill),
        (r"C:/Users/Administrator/.codex/skills/football-quant-fusion", skill),
    ]


def _ignore_pycache(_dir, names):
    return {n for n in names if n == "__pycache__" or n.endswith(".pyc")}


def copy_tree(src: Path, dst: Path):
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=_ignore_pycache)


def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)


def rewrite_files(root: Path, rewrites, dry=False):
    changed = 0
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in (".py", ".md", ".json"):
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        new = text
        for old, rep in rewrites:
            new = new.replace(old, rep)
        if new != text:
            p.write_text(new, encoding="utf-8")
            changed += 1
    return changed


def copy_shared_data(with_datasets: bool):
    ensure_dir(SHARED_DIR)
    # odds 盘口移动日志（小，有用）
    odds_src = SRC_SHARED / "odds"
    if odds_src.exists():
        copy_tree(odds_src, SHARED_DIR / "odds")
    # today 今日快照（小）
    today_src = SRC_SHARED / "today"
    if today_src.exists():
        copy_tree(today_src, SHARED_DIR / "today")
    # datasets 精选小文件；大训练集默认不打包
    ds_src = SRC_SHARED / "datasets"
    ds_dst = SHARED_DIR / "datasets"
    ensure_dir(ds_dst)
    curated = [
        "understat_store.jsonl",
        "devig_backtest_400_matches.jsonl",
        "team_strength_ratings_2025.json",
    ]
    for name in curated:
        f = ds_src / name
        if f.exists():
            shutil.copy2(f, ds_dst / name)
    if with_datasets:
        for f in ds_src.iterdir():
            if f.is_file() and f.name not in curated:
                shutil.copy2(f, ds_dst / f.name)
    (ds_dst / "README.md").write_text(
        "本目录为精选数据。完整训练集(约1.2GB, 含 sporttery_all_leagues_history_2026_*、"
        "football_data_big5_* 等)默认不打包；如需请运行 export_skill_for_hermes.py --with-datasets。\n",
        encoding="utf-8",
    )
    # 运行时目录骨架
    for name in ("backtest", "forward", "metrics"):
        ensure_dir(SHARED_DIR / name)
    (SHARED_DIR / "backtest" / "README.md").write_text(
        "回测注册表目录。fusion_record / settle / backtest 会在首次运行时自动创建 jsonl；"
        "本机已有的历史注册表(约57MB)默认不打包。\n",
        encoding="utf-8",
    )
    (SHARED_DIR / "forward" / "README.md").write_text("每日流水线工作目录。\n", encoding="utf-8")
    (SHARED_DIR / "metrics" / "README.md").write_text("评估指标输出目录。\n", encoding="utf-8")


def generate_sample_input() -> Path:
    ensure_dir(EXAMPLE_DIR)
    data = json.loads(SRC_TODAY_INPUT.read_text(encoding="utf-8"))
    match = next((m for m in data["matches"] if m.get("sporttery_meta", {}).get("match_num") == "周四004"), data["matches"][0])
    sample = {"matches": [match]}
    out = EXAMPLE_DIR / "sample_input.json"
    out.write_text(json.dumps(sample, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def generate_manual():
    ensure_dir(MANUAL_DIR)
    parts = [
        "# football-quant-fusion 技能完整手册（单文件版）\n",
        "\n> 本文件由 export_skill_for_hermes.py 自动合并生成，内容与本机技能 1.4.0 一致。\n"
        "> 用途：给只能粘贴文本的 Hermes 作为常驻技能说明；脚本仍在本包 01_技能本体/ 下，按文内命令执行。\n",
        "\n---\n\n",
        (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8"),
        "\n\n---\n\n# 附：功能映射（references/function_map.md）\n\n",
        (SKILL_DIR / "references" / "function_map.md").read_text(encoding="utf-8"),
        "\n\n---\n\n# 附：推荐门控配置（config/recommendation_policy.json）\n\n```json\n",
        (SKILL_DIR / "config" / "recommendation_policy.json").read_text(encoding="utf-8"),
        "\n```\n\n# 附：版本清单（config/version_manifest.json）\n\n```json\n",
        (SKILL_DIR / "config" / "version_manifest.json").read_text(encoding="utf-8"),
        "\n```\n\n**概率模型输出，非投注建议。**\n",
    ]
    out = MANUAL_DIR / "SKILL_完整手册.md"
    out.write_text("".join(parts), encoding="utf-8")
    return out


def generate_example_readme():
    ensure_dir(EXAMPLE_DIR)
    out = EXAMPLE_DIR / "运行示例.md"
    out.write_text(
        """# 运行示例（在本包根目录执行）

## 1. 采集今日竞彩销售日盘口

```sh
python 01_技能本体/football-quant-fusion/scripts/fusion_cli.py collect --sales-day 2026-08-06 --output raw.json --emit-input input.json
```

## 2. 批量预测（胜平负/比分/大小球/BTTS/让球）

```sh
python 01_技能本体/football-quant-fusion/scripts/fusion_predict.py input.json > output.json
```

也可以用包内示例输入直接试跑：

```sh
python 01_技能本体/football-quant-fusion/scripts/fusion_predict.py 04_示例/sample_input.json > 04_示例/sample_output.json
```

## 3. 登记 prematch 快照到待回测库

```sh
python 01_技能本体/football-quant-fusion/scripts/fusion_cli.py record --input input.json --output model_output.json --snapshot prematch
```

## 4. 开球后回填赛果并回测

```sh
python 01_技能本体/football-quant-fusion/scripts/fusion_cli.py settle --date 2026-08-06
python 01_技能本体/football-quant-fusion/scripts/backtest_dual_track.py --date 20260806
```

## 5. 双轨（LLM 对比）可选

LLM 轨道为搜索证据驱动的定性判断（方向 + 比分偏好），按 05_单文件手册 中的 llm-track-1.0 模板登记到待回测目录，与量化轨道同场回测对比。

> 所有产物请保存在各自的 projectXXX 项目文件夹内（SOP），不要把文件散落到系统其它位置。
""",
        encoding="utf-8",
    )
    return out


def make_zip():
    ensure_dir(DIST_DIR)
    out = DIST_DIR / ZIP_NAME
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in PROJECT_ROOT.rglob("*"):
            if p.is_file() and not p.is_relative_to(DIST_DIR) and p.name != "export_skill_for_hermes.py":
                zf.write(p, p.relative_to(PROJECT_ROOT))
    return out


def main():
    ap = argparse.ArgumentParser(description="一键导出 football-quant-fusion 技能包给 Hermes")
    ap.add_argument("--with-datasets", action="store_true", help="额外带上大数据训练集(约1.2GB)")
    ap.add_argument("--no-rewrite", action="store_true", help="不改写脚本内绝对路径(仅本机使用)")
    ap.add_argument("--no-zip", action="store_true", help="只更新目录不重新打包")
    args = ap.parse_args()

    if not SRC_SKILL.exists() or not SRC_CORE.exists():
        sys.exit(f"源技能缺失: {SRC_SKILL} / {SRC_CORE}")

    # 1) 技能本体 + 核心引擎
    copy_tree(SRC_SKILL, SKILL_DIR)
    copy_tree(SRC_CORE, CORE_DIR)
    print(f"[1/6] 技能本体 -> {SKILL_DIR}")
    print(f"[1/6] 核心引擎 -> {CORE_DIR}")

    # 2) 共享数据
    copy_shared_data(args.with_datasets)
    print(f"[2/6] 共享数据 -> {SHARED_DIR}")

    # 3) 路径改写（本机绝对路径 -> 包内相对路径）
    if args.no_rewrite:
        print("[3/6] 跳过路径改写 (--no-rewrite)")
    else:
        rewrites = build_rewrites()
        n1 = rewrite_files(SKILL_DIR, rewrites)
        n2 = rewrite_files(CORE_DIR, rewrites)
        print(f"[3/6] 路径改写完成: 技能本体 {n1} 个文件, 核心引擎 {n2} 个文件")

    # 4) 示例
    sample = generate_sample_input()
    example_md = generate_example_readme()
    print(f"[4/6] 示例输入 -> {sample}")
    print(f"[4/6] 运行示例 -> {example_md}")

    # 5) 单文件手册
    manual = generate_manual()
    print(f"[5/6] 单文件手册 -> {manual}")

    # 6) 打包
    if args.no_zip:
        print("[6/6] 跳过打包 (--no-zip)")
    else:
        z = make_zip()
        size_mb = z.stat().st_size / 1024 / 1024
        print(f"[6/6] 打包完成 -> {z} ({size_mb:.1f} MB)")

    print("\n导出完成。验证命令:")
    print(f'  python "{SKILL_DIR / "scripts" / "fusion_predict.py"}" "{sample}" > sample_out.json')


if __name__ == "__main__":
    main()
