#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""足球预测量化工具 — Windows 交互式菜单（独立工具入口）。

双击 fusion_tool.bat 启动本菜单。菜单直接调用 fusion_cli.py 及配套脚本，
与 Codex/DSH 会话无关，可在任何 Windows 终端独立使用。

纪律（与 AGENTS.md 一致）：
- 所有登记/结算/回测显式 --store 指向仓库内唯一事实源；
- 版本管理（release_lock / audit）走 40_模型 方案定义的新流程。
"""
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

SCRIPTS = Path(r"F:\HM足球比赛预测\project018_技能工作区整合\02_脚本\skill\football-quant-fusion\scripts")
STORE = Path(r"F:\HM足球比赛预测\project018_技能工作区整合\04_素材\shared-data\football-quant-fusion\backtest")
DELIVERY = Path(r"F:\HM足球比赛预测\project021_五大联赛APIFootball训练\05_交付")
TOOL_DIR = Path(__file__).resolve().parent
LOG_DIR = TOOL_DIR / "logs"

sys.path.insert(0, str(SCRIPTS))
from runtime import resolve_python  # noqa: E402

PY = resolve_python()          # 融合脚本统一用 3.12
CLI = SCRIPTS / "fusion_cli.py"
INTERNAL_BT = TOOL_DIR / "internal_backtest.py"
LOCK = SCRIPTS / "release_lock.py"
AUDIT = SCRIPTS / "audit_version_consistency.py"
DUAL_TRACK = SCRIPTS / "backtest_dual_track.py"
TOURNAMENT = SCRIPTS / "ucl_tournament_mc.py"

MENU = """
================================================
  ⚽ 足球预测量化工具  (football-quant-fusion)
================================================
  [1] 每日开售预测   采集+预测+登记当日竞彩场次
  [2] 赛果回填       拉取官方赛果结算（settle）
  [3] 全量回测       融合模型 Brier/命中率报告
  [4] 双轨回测       量化 vs LLM（按日期）
  [5] 版本管理       锁定发布 / 审计概率签名漂移
  [6] 查看最近报告
  [7] 欧冠夺冠模拟   Monte Carlo 淘汰赛
  [8] 国际盘对照     odds-intl（需先有 match-file）
  [9] 生成 PPT 报告  预测结果 / 回测报告 一键转 PPT
  [0] 退出
================================================
"""


def banner(text):
    print(f"\n--- {text} ---")


def run(cmd, note=""):
    """运行命令：spinner + 实时回显日志新内容 + 已运行时长，输出写日志。"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log = LOG_DIR / f"{ts}_{note}.log" if note else LOG_DIR / f"{ts}.log"
    print(f"[执行] {' '.join(str(x) for x in cmd)}")
    print(f"[日志] {log}")
    started = time.time()
    import os as _os
    env = dict(_os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
    with open(log, "wb") as fp:          # 子进程写日志（写句柄）
        proc = subprocess.Popen([str(x) for x in cmd], stdout=fp, stderr=subprocess.STDOUT,
                                env=env)
        spin = "|/-\\"
        i = 0
        last_size = 0
        while proc.poll() is None:
            # 用独立读句柄实时读取日志文件新写入的内容并回显
            try:
                with open(log, "r", encoding="utf-8", errors="replace") as rf:
                    rf.seek(last_size)
                    new = rf.read()
                    last_size = rf.tell()
                if new.strip():
                    sys.stdout.write(new)
                    sys.stdout.flush()
            except Exception:
                pass
            elapsed = time.time() - started
            print(f"\r  [{spin[i % 4]}] 运行中 · 已用 {elapsed:5.1f} 秒   "
                  f"（进度实时显示在上方）", end="", flush=True)
            i += 1
            time.sleep(0.15)
        proc.wait()
    # 收尾：回显剩余输出
    try:
        with open(log, "r", encoding="utf-8", errors="replace") as rf:
            rf.seek(last_size)
            rest = rf.read()
        if rest.strip():
            sys.stdout.write(rest)
            sys.stdout.flush()
    except Exception:
        pass
    elapsed = time.time() - started
    print(f"\n  [完成] 用时 {elapsed:.0f} 秒，退出码 {proc.returncode}")
    print(f"[完成] 完整输出见 {log}")
    return proc.returncode


def menu_1_daily():
    day = input("开球日期（YYYY-MM-DD，回车=今天）: ").strip()
    cmd = [PY, str(CLI), "daily-pipeline", "--store", str(STORE)]
    if day:
        cmd += ["--kickoff-date", day]
    run(cmd, note="daily_pipeline")


def menu_2_settle():
    run([PY, str(CLI), "settle", "--store", str(STORE)], note="settle")


def menu_3_backtest():
    if not INTERNAL_BT.exists():
        print("缺少 internal_backtest.py（内部 store 重定向包装），请从 06_复盘 复制。")
        input("回车返回...")
        return
    out = DELIVERY / f"backtest_{datetime.now().strftime('%Y%m%d_%H%M')}_fusion.json"
    run([PY, str(INTERNAL_BT), "--store", str(STORE), "--output", str(out)],
        note="fusion_backtest")


def menu_4_dual_track():
    date = input("待回测日期（YYYYMMDD，如 20260812）: ").strip()
    if not date:
        print("日期不能为空。")
        input("回车返回...")
        return
    iso = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
    records = DELIVERY / "每日开售预测" / iso / "待回测记录" / iso
    if not records.exists():
        alt = input(f"未找到默认待回测记录目录 {records}\n手动输入 records-dir（回车放弃）: ").strip()
        if not alt:
            return
        records = Path(alt)
    out = TOOL_DIR / f"dual_track_{date}.json"
    run([PY, str(DUAL_TRACK), "--records-dir", str(records),
         "--results-dir", str(STORE / "results"), "--output", str(out)],
        note=f"dual_track_{date}")


def menu_5_version():
    print("  [1] 锁定发布快照（release_lock）")
    print("  [2] 审计概率签名漂移（audit）")
    print("  [0] 返回")
    c = input("选择: ").strip()
    if c == "1":
        run([PY, str(LOCK)], note="release_lock")
    elif c == "2":
        run([PY, str(AUDIT)], note="audit_version")


def menu_6_reports():
    targets = sorted(TOOL_DIR.glob("dual_track_*.json")) + \
              sorted(DELIVERY.glob("backtest_*.json")) + \
              sorted(STORE.glob("backtest_*.json"))
    latest = targets[-10:] if targets else []
    if not latest:
        print("暂无报告文件。")
    else:
        for i, p in enumerate(latest, 1):
            print(f"  [{i}] {p.name}  ({datetime.fromtimestamp(p.stat().st_mtime):%m-%d %H:%M})")
        c = input("输入编号用记事本打开（回车返回）: ").strip()
        if c.isdigit() and 1 <= int(c) <= len(latest):
            subprocess.Popen(["notepad", str(latest[int(c) - 1])])
    input("回车返回...")


def menu_7_tournament():
    print("默认跑内置自检；生产模拟需 teams/strength 参数，见 fusion_cli.py tournament --help")
    run([PY, str(CLI), "tournament"], note="tournament")


def menu_8_odds_intl():
    f = input("match-file 路径（raw JSON，含 matches；回车放弃）: ").strip()
    if not f:
        return
    out = input("输出快照 JSON 路径: ").strip() or str(TOOL_DIR / "intl_snapshot.json")
    run([PY, str(CLI), "odds-intl", "--match-file", f, "--out", out], note="odds_intl")


def menu_9_ppt():
    print("  [1] 每日预测结果 → PPT（按日期扫描 output.json）")
    print("  [2] 回测报告 → PPT（选 backtest JSON）")
    print("  [0] 返回")
    c = input("选择: ").strip()
    gen = TOOL_DIR / "gen_report_ppt.py"
    if c == "1":
        day = input("日期（YYYY-MM-DD，如 2026-08-12）: ").strip()
        if day:
            run([PY, str(gen), "prediction", "--date", day], note=f"ppt_pred_{day}")
    elif c == "2":
        targets = sorted(DELIVERY.glob("backtest_*.json")) + sorted(STORE.glob("backtest_*.json"))
        if not targets:
            print("未找到 backtest JSON，先跑菜单 3 全量回测。")
            return
        for i, p in enumerate(targets[-8:], 1):
            print(f"  [{i}] {p.name}")
        c2 = input("输入编号（回车=最新一个）: ").strip()
        idx = int(c2) - 1 if c2.isdigit() and 1 <= int(c2) <= len(targets[-8:]) else -1
        src = targets[-8:][idx]
        run([PY, str(gen), "backtest", "--input", str(src)], note="ppt_backtest")


def main():
    while True:
        print(MENU)
        c = input("请选择 [0-9]: ").strip()
        if c == "0":
            print("再见。")
            break
        elif c == "1":
            menu_1_daily()
        elif c == "2":
            menu_2_settle()
        elif c == "3":
            menu_3_backtest()
        elif c == "4":
            menu_4_dual_track()
        elif c == "5":
            menu_5_version()
        elif c == "6":
            menu_6_reports()
        elif c == "7":
            menu_7_tournament()
        elif c == "8":
            menu_8_odds_intl()
        elif c == "9":
            menu_9_ppt()
        else:
            print("无效选择。")
        input("\n回车返回主菜单...")


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\n已退出。")
