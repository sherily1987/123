# APIFootball 欧冠回测结算实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有融合回测链路中加入显式启用的 APIFootball 欧冠赛果补全，并保证90分钟、加时、点球、身份和来源歧义不会进入正式回测分母。

**Architecture:** 新增纯函数标准化器与严格比赛匹配器，再由独立供应商结算脚本读取待结算登记、批量获取比赛日赛果、输出不可覆盖的审计运行。新增融合结算编排器，先调用体彩官方结算，再仅对仍待结算比赛运行 APIFootball fallback；现有 `settle` 默认行为保持不变。

**Tech Stack:** Python 3.11+、标准库、pytest、现有 `apifootball_com_adapter.py`、现有 `settle_result.py`、JSON/JSONL。

## Global Constraints

- 体彩官方赛果优先，APIFootball 不得覆盖已有正式结果。
- 只有 `score_90_status=verified` 可以写入正式结果库。
- 点球只用于晋级，不得改变90分钟胜平负、比分、大小球或 BTTS。
- 赛后统计、首发和球员数据不得进入赛前特征。
- 缺少密钥、接口失败、身份歧义和比分阶段歧义不得阻断已完成的体彩官方结算。
- API key 只从 `APIFOOTBALL_COM_KEY` 读取，不写入日志、候选、报告或异常。
- 新项目文档与运行产物只写入 `project022_APIFootball欧冠回测结算/`；共享可调用代码写入现有 `project018_技能工作区整合/02_脚本/skill/football-quant-fusion/`。
- 现有未提交文件属于其他工作，不修改、不暂存、不提交。

---

### Task 1: 标准化比分阶段并阻止歧义结算

**Files:**
- Create: `project018_技能工作区整合/02_脚本/skill/football-quant-fusion/scripts/apifootball_settlement.py`
- Create: `project018_技能工作区整合/02_脚本/skill/football-quant-fusion/scripts/test_apifootball_settlement.py`

**Interfaces:**
- Consumes: APIFootball `get_events` 单场原始 dict 与 ISO `collected_at`。
- Produces: `normalize_event(event: dict, collected_at: str) -> dict`，schema 为 `apifootball-settlement-candidate-1.0`。

- [x] **Step 1: 写普通完赛、未完赛、加时和点球的失败测试**

```python
from apifootball_settlement import normalize_event


BASE = {
    "match_id": "7",
    "league_id": "3",
    "league_name": "UEFA Champions League",
    "match_date": "2026-03-11",
    "match_time": "20:00",
    "match_status": "Finished",
    "match_hometeam_id": "1",
    "match_hometeam_name": "Home",
    "match_awayteam_id": "2",
    "match_awayteam_name": "Away",
    "match_hometeam_score": "2",
    "match_awayteam_score": "1",
}


def test_plain_finished_match_has_verified_90_minute_score():
    row = normalize_event(BASE, "2026-08-12T00:00:00+00:00")
    assert row["score_90"] == {"home": 2, "away": 1}
    assert row["score_90_status"] == "verified"


def test_unfinished_match_is_not_settleable():
    row = normalize_event({**BASE, "match_status": "Postponed"}, "t")
    assert row["score_90"] is None
    assert row["score_90_status"] == "not_finished"


def test_extra_time_without_explicit_90_score_is_ambiguous():
    event = {**BASE, "match_hometeam_extra_score": "2", "match_awayteam_extra_score": "1"}
    row = normalize_event(event, "t")
    assert row["score_90"] is None
    assert row["score_90_status"] == "ambiguous_extra_time"


def test_penalties_without_explicit_90_score_are_ambiguous():
    event = {**BASE, "match_hometeam_penalty_score": "5", "match_awayteam_penalty_score": "4"}
    row = normalize_event(event, "t")
    assert row["score_90"] is None
    assert row["score_penalties"] == {"home": 5, "away": 4}
    assert row["score_90_status"] == "ambiguous_penalties"
```

- [x] **Step 2: 运行测试并确认因模块缺失而失败**

Run: `pytest -q project018_技能工作区整合/02_脚本/skill/football-quant-fusion/scripts/test_apifootball_settlement.py`

Expected: FAIL，`ModuleNotFoundError: No module named 'apifootball_settlement'`。

- [x] **Step 3: 实现最小标准化器**

```python
def _int(value):
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _pair(event, home_key, away_key):
    home, away = _int(event.get(home_key)), _int(event.get(away_key))
    return {"home": home, "away": away} if home is not None and away is not None else None


def normalize_event(event, collected_at):
    final = _pair(event, "match_hometeam_score", "match_awayteam_score")
    extra = _pair(event, "match_hometeam_extra_score", "match_awayteam_extra_score")
    penalties = _pair(event, "match_hometeam_penalty_score", "match_awayteam_penalty_score")
    finished = str(event.get("match_status", "")).strip().lower() == "finished"
    if not finished:
        score_90, state = None, "not_finished"
    elif final is None:
        score_90, state = None, "invalid_score"
    elif penalties is not None:
        score_90, state = None, "ambiguous_penalties"
    elif extra is not None:
        score_90, state = None, "ambiguous_extra_time"
    else:
        score_90, state = final, "verified"
    return {
        "schema": "apifootball-settlement-candidate-1.0",
        "provider": "apifootball.com",
        "provider_match_id": _int(event.get("match_id")),
        "provider_league_id": _int(event.get("league_id")),
        "competition": event.get("league_name"),
        "kickoff": f"{event.get('match_date')}T{event.get('match_time') or '00:00'}:00+08:00",
        "home": {"id": _int(event.get("match_hometeam_id")), "name": event.get("match_hometeam_name")},
        "away": {"id": _int(event.get("match_awayteam_id")), "name": event.get("match_awayteam_name")},
        "status": "finished" if finished else "not_finished",
        "score_90": score_90,
        "score_extra_time": extra,
        "score_penalties": penalties,
        "score_90_status": state,
        "raw_score_fields": {key: event.get(key) for key in (
            "match_hometeam_score", "match_awayteam_score",
            "match_hometeam_halftime_score", "match_awayteam_halftime_score",
            "match_hometeam_extra_score", "match_awayteam_extra_score",
            "match_hometeam_penalty_score", "match_awayteam_penalty_score",
        )},
        "collected_at": collected_at,
    }
```

- [x] **Step 4: 运行测试并确认通过**

Run: `pytest -q project018_技能工作区整合/02_脚本/skill/football-quant-fusion/scripts/test_apifootball_settlement.py`

Expected: `4 passed`。

- [x] **Step 5: 提交该任务**

```powershell
git add -- project018_技能工作区整合/02_脚本/skill/football-quant-fusion/scripts/apifootball_settlement.py project018_技能工作区整合/02_脚本/skill/football-quant-fusion/scripts/test_apifootball_settlement.py
git commit -m "feat: normalize APIFootball settlement scores safely"
```

---

### Task 2: 严格匹配预测登记与供应商比赛

**Files:**
- Create: `project018_技能工作区整合/02_脚本/skill/football-quant-fusion/scripts/apifootball_matcher.py`
- Create: `project018_技能工作区整合/02_脚本/skill/football-quant-fusion/scripts/test_apifootball_matcher.py`
- Create: `project018_技能工作区整合/02_脚本/skill/football-quant-fusion/config/apifootball_team_aliases.json`

**Interfaces:**
- Consumes: 登记记录 dict、Task 1 候选列表、别名配置 dict、时间窗口分钟数。
- Produces: `match_record(record: dict, candidates: list[dict], aliases: dict[str, str], tolerance_minutes: int = 30) -> dict`，返回 `matched`、`no_match` 或 `ambiguous_match`。

- [x] **Step 1: 写精确 ID、唯一身份匹配和歧义拒绝的失败测试**

```python
from apifootball_matcher import match_record


def candidate(mid, home="Arsenal", away="PSG", kickoff="2026-03-11T20:00:00+08:00"):
    return {"provider_match_id": mid, "provider_league_id": 3,
            "competition": "UEFA Champions League", "kickoff": kickoff,
            "home": {"name": home}, "away": {"name": away},
            "score_90_status": "verified", "score_90": {"home": 1, "away": 0}}


def test_provider_match_id_has_priority():
    record = {"provider_refs": {"apifootball_match_id": 22}, "match": {"home": "wrong", "away": "wrong"}}
    result = match_record(record, [candidate(21), candidate(22)], {})
    assert result["status"] == "matched"
    assert result["matched_by"] == "provider_match_id"
    assert result["candidate"]["provider_match_id"] == 22


def test_unique_identity_match_requires_aliases_and_time_window():
    record = {"match": {"home": "阿森纳", "away": "巴黎圣日耳曼",
                         "kickoff": "2026-03-11T12:05:00+00:00", "league": "欧冠"}}
    aliases = {"阿森纳": "Arsenal", "巴黎圣日耳曼": "PSG"}
    result = match_record(record, [candidate(22)], aliases)
    assert result["status"] == "matched"
    assert result["matched_by"] == "identity_unique"


def test_multiple_identity_candidates_are_not_auto_settled():
    record = {"match": {"home": "Arsenal", "away": "PSG",
                         "kickoff": "2026-03-11T12:00:00+00:00", "league": "欧冠"}}
    result = match_record(record, [candidate(21), candidate(22)], {})
    assert result["status"] == "ambiguous_match"


def test_reversed_home_and_away_do_not_match():
    record = {"match": {"home": "Arsenal", "away": "PSG",
                         "kickoff": "2026-03-11T12:00:00+00:00", "league": "欧冠"}}
    result = match_record(record, [candidate(22, home="PSG", away="Arsenal")], {})
    assert result["status"] == "no_match"
```

- [x] **Step 2: 运行测试并确认因模块缺失而失败**

Run: `pytest -q project018_技能工作区整合/02_脚本/skill/football-quant-fusion/scripts/test_apifootball_matcher.py`

Expected: FAIL，`ModuleNotFoundError: No module named 'apifootball_matcher'`。

- [x] **Step 3: 实现严格匹配器和空的已验证别名配置**

```python
def match_record(record, candidates, aliases, tolerance_minutes=30):
    ref = ((record.get("provider_refs") or {}).get("apifootball_match_id")
           or (((record.get("input") or {}).get("provider_refs") or {}).get("apifootball_match_id")))
    if ref is not None:
        exact = [row for row in candidates if str(row.get("provider_match_id")) == str(ref)]
        if len(exact) == 1:
            return {"status": "matched", "matched_by": "provider_match_id", "candidate": exact[0]}
        return {"status": "ambiguous_match" if len(exact) > 1 else "no_match", "candidates": len(exact)}

    match = record.get("match") or {}
    home = aliases.get(str(match.get("home")), str(match.get("home")))
    away = aliases.get(str(match.get("away")), str(match.get("away")))
    kickoff = parse_time(match.get("kickoff"))
    eligible = [row for row in candidates
                if is_champions_league(row.get("competition"))
                and normalize_name(row["home"]["name"]) == normalize_name(home)
                and normalize_name(row["away"]["name"]) == normalize_name(away)
                and kickoff is not None
                and abs((parse_time(row.get("kickoff")) - kickoff).total_seconds()) <= tolerance_minutes * 60]
    if len(eligible) == 1:
        return {"status": "matched", "matched_by": "identity_unique", "candidate": eligible[0]}
    return {"status": "ambiguous_match" if len(eligible) > 1 else "no_match", "candidates": len(eligible)}
```

配置文件内容固定为：

```json
{
  "schema": "apifootball-team-aliases-1.0",
  "aliases": {},
  "rule": "Only verified aliases may be added; fuzzy names never auto-settle."
}
```

- [x] **Step 4: 运行测试并确认通过**

Run: `pytest -q project018_技能工作区整合/02_脚本/skill/football-quant-fusion/scripts/test_apifootball_matcher.py`

Expected: `4 passed`。

- [x] **Step 5: 提交该任务**

```powershell
git add -- project018_技能工作区整合/02_脚本/skill/football-quant-fusion/scripts/apifootball_matcher.py project018_技能工作区整合/02_脚本/skill/football-quant-fusion/scripts/test_apifootball_matcher.py project018_技能工作区整合/02_脚本/skill/football-quant-fusion/config/apifootball_team_aliases.json
git commit -m "feat: match APIFootball settlement candidates strictly"
```

---

### Task 3: 构建幂等供应商结算运行器与审计归档

**Files:**
- Create: `project018_技能工作区整合/02_脚本/skill/football-quant-fusion/scripts/settle_from_apifootball.py`
- Create: `project018_技能工作区整合/02_脚本/skill/football-quant-fusion/scripts/test_settle_from_apifootball.py`
- Create at runtime: `project022_APIFootball欧冠回测结算/05_交付/settlement_runs/<timestamp>/`

**Interfaces:**
- Consumes: `--store`、可选 `--date`、`--dry-run`、`--output-dir`，以及 `APIFOOTBALL_COM_KEY`。
- Produces: `run_settlement(store: Path, raw_events: list[dict], aliases: dict, dry_run: bool, settle_writer: Callable) -> dict`；CLI 输出同一汇总 JSON。

- [x] **Step 1: 写幂等、冲突、歧义和密钥脱敏的失败测试**

```python
def test_verified_candidate_is_written_once(tmp_path):
    store, record = make_pending_store(tmp_path, provider_match_id=7)
    written = []
    report = runner.run_settlement(store, [finished_event(7)], {}, False, written.append)
    assert report["settled"] == 1
    assert written[0]["score_90"] == "2-1"


def test_existing_same_result_is_idempotent(tmp_path):
    store, record = make_pending_store(tmp_path, provider_match_id=7, existing_score="2-1")
    report = runner.run_settlement(store, [finished_event(7)], {}, False, lambda _: None)
    assert report["report"][0]["status"] == "existing_same"


def test_existing_different_result_becomes_source_conflict(tmp_path):
    store, record = make_pending_store(tmp_path, provider_match_id=7, existing_score="0-0")
    report = runner.run_settlement(store, [finished_event(7)], {}, False, lambda _: None)
    assert report["conflicts"] == 1
    assert report["report"][0]["status"] == "source_conflict"


def test_ambiguous_extra_time_is_needs_review(tmp_path):
    store, record = make_pending_store(tmp_path, provider_match_id=7)
    report = runner.run_settlement(store, [extra_time_event(7)], {}, False, lambda _: None)
    assert report["report"][0]["status"] == "needs_review"


def test_redact_removes_api_key_from_errors():
    assert "secret" not in runner.redact("URL?APIkey=secret&league_id=3")
```

- [x] **Step 2: 运行测试并确认因运行器缺失而失败**

Run: `pytest -q project018_技能工作区整合/02_脚本/skill/football-quant-fusion/scripts/test_settle_from_apifootball.py`

Expected: FAIL，`ModuleNotFoundError: No module named 'settle_from_apifootball'`。

- [x] **Step 3: 实现运行器**

实现必须包含以下具体行为：

```python
def decide_existing(result_path, score_90):
    if not result_path.exists():
        return "write"
    current = json.loads(result_path.read_text(encoding="utf-8"))
    old = current.get("score_90")
    wanted = {"home": score_90["home"], "away": score_90["away"]}
    return "existing_same" if old == wanted else "source_conflict"


def redact(text):
    return re.sub(r"(?i)(APIkey=)[^&\\s]+", r"\1[REDACTED]", str(text))


def default_output_dir():
    return workspace_root() / "project022_APIFootball欧冠回测结算" / "05_交付" / "settlement_runs"
```

`run_settlement` 必须：读取 `registry.jsonl` 中尚未正式结算的记录；调用 Task 1 标准化；调用 Task 2 匹配；仅对 `matched + verified + write` 调用注入的 `settle_writer`；把 `existing_same`、`source_conflict`、`needs_review`、`no_match` 和 `not_finished` 分开计数。

真实 CLI 必须按待结算比赛的本地日期调用 `get_events`，固定 `league_id=3`、`timezone=Asia/Shanghai`，并通过现有 `settle_result.py` 写入：

```python
[
    sys.executable, str(core_scripts_dir() / "settle_result.py"),
    "--match-id", record_match_id,
    "--score-90", f"{score['home']}-{score['away']}",
    "--source", "APIFootball get_events fallback",
    "--source-url", "https://apifootball.com/",
    "--store", str(store),
]
```

每次运行先写临时目录，全部报告成功落盘后再原子改名为 `<timestamp>`；输出 `candidates.jsonl`、`settlement_audit.json`、`settled.json`、`conflicts.json` 和 `run_metadata.json`。

- [x] **Step 4: 运行任务测试并确认通过**

Run: `pytest -q project018_技能工作区整合/02_脚本/skill/football-quant-fusion/scripts/test_settle_from_apifootball.py`

Expected: `5 passed`。

- [x] **Step 5: 提交该任务**

```powershell
git add -- project018_技能工作区整合/02_脚本/skill/football-quant-fusion/scripts/settle_from_apifootball.py project018_技能工作区整合/02_脚本/skill/football-quant-fusion/scripts/test_settle_from_apifootball.py
git commit -m "feat: add audited APIFootball settlement runner"
```

---

### Task 4: 接入 fusion settle 与自动回测入口

**Files:**
- Create: `project018_技能工作区整合/02_脚本/skill/football-quant-fusion/scripts/fusion_settle.py`
- Create: `project018_技能工作区整合/02_脚本/skill/football-quant-fusion/scripts/test_fusion_settle.py`
- Modify: `project018_技能工作区整合/02_脚本/skill/football-quant-fusion/scripts/fusion_cli.py`
- Modify: `project018_技能工作区整合/02_脚本/skill/football-quant-fusion/scripts/fusion_daily_pipeline.py`
- Modify: `project018_技能工作区整合/02_脚本/skill/football-quant-fusion/scripts/auto_backtest.py`
- Modify: `project018_技能工作区整合/02_脚本/skill/football-quant-fusion/SKILL.md`

**Interfaces:**
- Consumes: `fusion_cli.py settle [--apifootball-fallback]`；`auto_backtest.py --settle [--apifootball-fallback]`。
- Produces: 合并结果 `{"official": ..., "apifootball_fallback": ..., "settled": N}`；未加 fallback 参数时保持官方结算默认路径。

- [x] **Step 1: 写默认关闭与显式启用的失败测试**

```python
def test_build_commands_defaults_to_official_only(tmp_path):
    commands = fusion_settle.build_commands(tmp_path, None, False, False)
    assert len(commands) == 1
    assert commands[0]["source"] == "official"


def test_build_commands_adds_provider_only_when_explicit(tmp_path):
    commands = fusion_settle.build_commands(tmp_path, "2026-08-11", True, True)
    assert [row["source"] for row in commands] == ["official", "apifootball"]
    assert "--dry-run" in commands[1]["cmd"]


def test_combined_report_does_not_hide_official_success_when_provider_fails():
    report = fusion_settle.combine_reports(
        {"settled": 2, "report": []},
        {"status": "provider_unavailable", "settled": 0},
    )
    assert report["settled"] == 2
    assert report["official"]["settled"] == 2
```

- [x] **Step 2: 运行测试并确认因编排器缺失而失败**

Run: `pytest -q project018_技能工作区整合/02_脚本/skill/football-quant-fusion/scripts/test_fusion_settle.py`

Expected: FAIL，`ModuleNotFoundError: No module named 'fusion_settle'`。

- [x] **Step 3: 实现编排器并修改三个入口**

`fusion_settle.py` 的命令构造固定为：

```python
def build_commands(store, date, dry_run, apifootball_fallback):
    common = ["--store", str(store)] + (["--date", date] if date else []) + (["--dry-run"] if dry_run else [])
    commands = [{"source": "official", "cmd": [sys.executable, str(core_scripts_dir() / "settle_from_sporttery.py"), *common]}]
    if apifootball_fallback:
        commands.append({"source": "apifootball", "cmd": [sys.executable, str(HERE / "settle_from_apifootball.py"), *common]})
    return commands
```

入口改造：

- `fusion_cli.py settle` 改为调用 `scripts/fusion_settle.py`；所有原参数原样透传。
- `fusion_daily_pipeline.py` 增加 `--apifootball-fallback`，并调用 `fusion_settle.py`，默认仍不启用。
- `auto_backtest.py` 增加 `--apifootball-fallback`；仅当同时传入 `--settle --apifootball-fallback` 时向 `fusion_cli.py settle` 追加该参数。
- `SKILL.md` 的 settle 命令下增加明确示例：

```powershell
python fusion_cli.py settle --date YYYY-MM-DD --apifootball-fallback --dry-run
python auto_backtest.py --settle --apifootball-fallback --workspace "F:\HM足球比赛预测" --output-dir <项目>/05_交付/auto_backtest
```

并注明：普通完赛可补全；加时/点球无法确认90分钟时为 `needs_review`，不进入正式分母。

- [x] **Step 4: 运行新增测试与现有融合测试**

Run:

```powershell
pytest -q project018_技能工作区整合/02_脚本/skill/football-quant-fusion/scripts/test_fusion_settle.py
pytest -q project018_技能工作区整合/02_脚本/skill/football-quant-fusion/scripts/test_engine_full.py
```

Expected: 新增 `3 passed`；现有融合测试全部通过。

- [x] **Step 5: 运行真实历史 dry-run 并验证审计边界**

Run:

```powershell
$env:APIFOOTBALL_COM_KEY = [Environment]::GetEnvironmentVariable('APIFOOTBALL_COM_KEY','User')
python project018_技能工作区整合/02_脚本/skill/football-quant-fusion/scripts/fusion_cli.py settle --date 2026-08-11 --apifootball-fallback --dry-run
```

Expected: 命令退出码为0；输出同时含 `official` 与 `apifootball_fallback`；未完赛、未匹配、加时/点球歧义没有 `would_settle`；报告目录位于 project022 的 `05_交付/settlement_runs/`。

- [x] **Step 6: 提交入口接入**

```powershell
git add -- project018_技能工作区整合/02_脚本/skill/football-quant-fusion/scripts/fusion_settle.py project018_技能工作区整合/02_脚本/skill/football-quant-fusion/scripts/test_fusion_settle.py project018_技能工作区整合/02_脚本/skill/football-quant-fusion/scripts/fusion_cli.py project018_技能工作区整合/02_脚本/skill/football-quant-fusion/scripts/fusion_daily_pipeline.py project018_技能工作区整合/02_脚本/skill/football-quant-fusion/scripts/auto_backtest.py project018_技能工作区整合/02_脚本/skill/football-quant-fusion/SKILL.md
git commit -m "feat: add APIFootball fallback to fusion settlement"
```

---

### Task 5: 全链路验收与项目交付

**Files:**
- Create: `project022_APIFootball欧冠回测结算/05_交付/2026-08-12_实施验收报告.md`
- Modify: `project022_APIFootball欧冠回测结算/01_规划/2026-08-12_APIFootball欧冠回测结算实施计划.md`（只勾选实际完成步骤）

**Interfaces:**
- Consumes: Tasks 1–4 的测试输出、dry-run 审计和 Git 提交。
- Produces: 可复核验收报告，包含测试数、真实 dry-run 数量、未完成项和数据边界。

- [x] **Step 1: 运行完整相关测试集**

Run:

```powershell
pytest -q \
  project018_技能工作区整合/02_脚本/skill/football-quant-fusion/scripts/test_apifootball_settlement.py \
  project018_技能工作区整合/02_脚本/skill/football-quant-fusion/scripts/test_apifootball_matcher.py \
  project018_技能工作区整合/02_脚本/skill/football-quant-fusion/scripts/test_settle_from_apifootball.py \
  project018_技能工作区整合/02_脚本/skill/football-quant-fusion/scripts/test_fusion_settle.py \
  project018_技能工作区整合/02_脚本/skill/football-quant-fusion/scripts/test_engine_full.py
```

Expected: 退出码0、0 failures。

- [x] **Step 2: 核验安全与工作区边界**

Run:

```powershell
rg -n "APIFOOTBALL_COM_KEY|APIkey=" project022_APIFootball欧冠回测结算/05_交付
git diff --check
git status --short
```

Expected: 交付文件中没有密钥值；`git diff --check` 无错误；只提交本计划列明文件，不带入其他项目改动。

- [x] **Step 3: 写验收报告**

报告必须列出：

- 新增 CLI 用法；
- 新增测试与通过数量；
- dry-run 的 `official settled`、`provider would_settle`、`needs_review`、`no_match`、`source_conflict` 数量；
- APIFootball 仅为 fallback，体彩官方仍优先；
- 加时/点球无法确认90分钟时不会自动结算；
- 仍需人工补充的已验证球队别名。

- [x] **Step 4: 提交验收文档和计划勾选**

```powershell
git add -- project022_APIFootball欧冠回测结算/01_规划/2026-08-12_APIFootball欧冠回测结算实施计划.md project022_APIFootball欧冠回测结算/05_交付/2026-08-12_实施验收报告.md
git commit -m "docs: verify APIFootball UCL settlement fallback"
```
