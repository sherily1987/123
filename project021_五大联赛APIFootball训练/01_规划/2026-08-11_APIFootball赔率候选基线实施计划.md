# APIFootball 赔率候选基线 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将五大联赛候选训练的离线市场基线替换为 APIFootball `get_odds` 的可审计赛前 1X2 共识概率。

**Architecture:** 赛果下载保持每联赛、每月缓存；赔率下载读取已下载赛果的唯一比赛日并每日期请求一次，再按 `match_id` 联接。每个 bookmaker 只保留开球前最后一条完整 1X2，先各自去水，再取逐项中位数并归一化为 `provider_market_1x2`；核心验证器以可选基线名称读取该概率而不改变既有 `market` API。

**Tech Stack:** Python 3.11 标准库（`zoneinfo`、`json`、`statistics`）、现有 APIFootball 适配器、pytest、Dixon-Coles team_strength。

## Global Constraints

- 只读 `APIFOOTBALL_COM_KEY`；密钥不可落盘或出现在异常、日志、报告。
- `get_odds` 原始响应仅存 `project021/04_素材/`，不提交 Git；模型与轻量报告可提交。
- `odd_date` 按 `Europe/Berlin` 运行时解释并写入 `timestamp_basis=provider_undocumented_assumed_europe_berlin`；不能解析、等于或晚于开球的赔率拒绝。
- 输出永远标 `provider_only=true`、`sporttery_compatible=false`；不得生成体彩玩法或生产推荐。
- `get_predictions`、statistics、lineup、player_statistics 不得进入训练或市场基线。

---

### Task 1: 可续跑的全局赔率下载与赛前联接

**Files:**
- Create: `project007_APIFootball数据接入/02_脚本/download_apifootball_com_odds.py`
- Create: `project007_APIFootball数据接入/02_脚本/test_download_apifootball_com_odds.py`

**Interfaces:**
- Consumes: 标准化赛果行的 `match_id`、`kickoff` 和 `actual`；`adapter.request("get_odds", {"from": day, "to": day})`。
- Produces: `download_odds_for_dates(dates: set[date], project: Path, refresh=False, retries=2, delay_seconds=0.7) -> dict`，以及 `attach_provider_market(events: list[dict], odds_rows: list[dict]) -> tuple[list[dict], dict]`。
- Raw cache: `04_素材/apifootball_com_odds_raw/YYYY-MM-DD.json`；标准化的目标赛事赔率：`04_素材/标准化/provider_market_1x2.jsonl`。

- [ ] **Step 1: 写失败测试：拒绝赛后和不完整赔率，并生成可审计共识**

```python
def test_attach_provider_market_uses_last_pre_kickoff_quote_per_bookmaker():
    events = [{"match_id": 7, "kickoff": "2024-08-17T20:00:00", "actual": [1, 0]}]
    odds = [
        {"match_id": 7, "bookmaker": "A", "observed_at": "2024-08-17 18:00:00", "odds_1x2": [2.0, 3.0, 4.0]},
        {"match_id": 7, "bookmaker": "A", "observed_at": "2024-08-17 21:00:00", "odds_1x2": [9.0, 9.0, 1.1]},
        {"match_id": 7, "bookmaker": "B", "observed_at": "2024-08-17 19:00:00", "odds_1x2": [2.2, 3.1, 3.8]},
    ]
    rows, audit = odds_history.attach_provider_market(events, odds)
    assert rows[0]["provider_market_1x2"] is not None
    assert rows[0]["provider_market_meta"]["bookmaker_count"] == 2
    assert audit["rejected_after_kickoff"] == 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest -q project007_APIFootball数据接入/02_脚本/test_download_apifootball_com_odds.py -k pre_kickoff`

Expected: FAIL，因为模块或 `attach_provider_market` 尚不存在。

- [ ] **Step 3: 实现最小下载、缓存与联接逻辑**

```python
def download_odds_for_dates(dates, project, refresh=False, retries=2, delay_seconds=0.7):
    for day in sorted(dates):
        path = raw_dir / f"{day:%Y-%m-%d}.json"
        payload = cached(path) if path.exists() and not refresh else request_with_retry(day)
        write_provider_envelope(path, payload)
    return {"rows": normalized_rows, "failures": failures, "dates_reused": reused, "dates_downloaded": downloaded}

def attach_provider_market(events, odds_rows):
    # Europe/Berlin: last valid pre-kickoff price for each bookmaker;
    # de-vig each book, coordinate median, normalize, and retain audit metadata.
```

`provider_market_meta` 必须包含：`bookmakers`、`bookmaker_count`、`selected_observed_at`、`timestamp_basis`、`selection_rule`。无入选赔率的比赛保留赛果并写 `provider_market_1x2=null`。

- [ ] **Step 4: 运行新测试与既有下载测试**

Run: `python -m pytest -q project007_APIFootball数据接入/02_脚本/test_download_apifootball_com_odds.py project007_APIFootball数据接入/02_脚本/test_download_apifootball_com_history.py`

Expected: PASS；缓存复用、API key 脱敏和赛后赔率拒绝均通过。

- [ ] **Step 5: 提交 Task 1**

```powershell
git add project007_APIFootball数据接入/02_脚本/download_apifootball_com_odds.py project007_APIFootball数据接入/02_脚本/test_download_apifootball_com_odds.py
git commit -m "feat: add apifootball provider odds history"
```

### Task 2: 为 core 验证器增加命名的供应商概率基线

**Files:**
- Modify: `project018_技能工作区整合/02_脚本/core/zu-yu-dashi-3/scripts/team_strength.py:52-72,211-281`
- Modify: `project007_APIFootball数据接入/02_脚本/test_team_strength_training.py`

**Interfaces:**
- Consumes: JSONL 行中的 `provider_market_1x2: list[float] | null` 和 `provider_market_meta`。
- Produces: `load_matches(..., provider_market_key="provider_market_1x2")` 在 match 中保留 `provider_market`；`validate(..., baseline_key="market", baseline_label="market")` 在报告中使用给定标签。

- [ ] **Step 1: 写失败测试：供应商概率出现在独立报告字段**

```python
def test_validate_reports_named_provider_market_baseline(monkeypatch):
    matches = [{"home": "A", "away": "B", "gh": 1, "ga": 0, "day": 2,
                "league": "152", "odds": [], "provider_market": [0.5, 0.3, 0.2]}]
    report = strength.validate(matches, model, from_day=2,
                               baseline_key="provider_market", baseline_label="provider_market")
    assert report["provider_market"]["n"] == 1
    assert "market" not in report
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest -q project007_APIFootball数据接入/02_脚本/test_team_strength_training.py -k provider_market`

Expected: FAIL，因为 `validate` 目前只读取 `odds` 并固定输出 `market`。

- [ ] **Step 3: 实现最小兼容扩展**

```python
def validate(matches, model, from_day, half_life=500.0, to_day=None,
             baseline_key="market", baseline_label="market"):
    # baseline_key == "market" 继续由 odds 去水产生；
    # baseline_key == "provider_market" 直接读取已去水的三项概率。
    # 返回 {baseline_label: metrics(...)}，默认调用方输出保持不变。
```

`load_matches` 必须继续允许 results-only 输入，并仅在字段为三个正数且和约为 1 时保留 `provider_market`。

- [ ] **Step 4: 运行核心回归测试**

Run: `python -m pytest -q project007_APIFootball数据接入/02_脚本/test_team_strength_training.py`

Expected: PASS；results-only 的默认 `market=UNAVAILABLE` 不变，provider 基线走独立标签。

- [ ] **Step 5: 提交 Task 2**

```powershell
git add project018_技能工作区整合/02_脚本/core/zu-yu-dashi-3/scripts/team_strength.py project007_APIFootball数据接入/02_脚本/test_team_strength_training.py
git commit -m "feat: evaluate team strength against provider market"
```

### Task 3: 重排五联赛流水线并输出赔率覆盖审计

**Files:**
- Modify: `project021_五大联赛APIFootball训练/02_脚本/run_five_league_pipeline.py`
- Modify: `project021_五大联赛APIFootball训练/02_脚本/train_five_leagues.py`
- Modify: `project021_五大联赛APIFootball训练/02_脚本/test_run_five_league_pipeline.py`
- Modify: `project021_五大联赛APIFootball训练/02_脚本/test_train_five_leagues.py`
- Modify: `project018_技能工作区整合/02_脚本/skill/football-quant-fusion/SKILL.md`

**Interfaces:**
- Consumes: `download_odds_for_dates` 和 `attach_provider_market` 的报告及每联赛富化 JSONL。
- Produces: `04_素材/标准化/<slug>_events_provider_market.jsonl`、每联赛训练报告的 `provider_market`、全局 `provider_market_coverage`。

- [ ] **Step 1: 写失败测试：五联赛只进行一次跨联赛赔率下载**

```python
def test_pipeline_downloads_provider_odds_once_for_all_event_dates(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline, "download_history", fake_complete_history)
    calls = []
    monkeypatch.setattr(pipeline, "download_odds_for_dates", lambda dates, *args, **kwargs: calls.append(dates) or fake_odds())
    pipeline.run_pipeline(tmp_path)
    assert len(calls) == 1
    assert calls[0] == {date(2024, 8, 17)}
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest -q project021_五大联赛APIFootball训练/02_脚本/test_run_five_league_pipeline.py -k provider_odds_once`

Expected: FAIL，因为当前流水线每下载一个联赛就立即训练，未调用赔率下载器。

- [ ] **Step 3: 实现两阶段编排与训练接线**

```python
# phase 1: all five result downloads
# phase 2: unique kickoff dates -> one global odds download -> attach_provider_market per league
trained = training.train_one_league(enriched_path, league, model_dir,
                                    baseline_key="provider_market", baseline_label="provider_market")
result["provider_market_coverage"] = odds_report["coverage"]
```

只有赛果下载失败阻止该联赛训练；赔率失败标记 `status=partial` 和失败日期，但已验证的开球前赔率仍可用于候选评估，报告必须列出覆盖率与拒绝计数。

- [ ] **Step 4: 运行流水线离线测试与文档检查**

Run: `python -m pytest -q project021_五大联赛APIFootball训练/02_脚本/test_train_five_leagues.py project021_五大联赛APIFootball训练/02_脚本/test_run_five_league_pipeline.py; python -m py_compile project021_五大联赛APIFootball训练/02_脚本/run_five_league_pipeline.py project021_五大联赛APIFootball训练/02_脚本/train_five_leagues.py`

Expected: PASS；技能文档写明 provider-only 候选基线及其时间假设。

- [ ] **Step 5: 提交 Task 3**

```powershell
git add project021_五大联赛APIFootball训练/02_脚本 project018_技能工作区整合/02_脚本/skill/football-quant-fusion/SKILL.md
git commit -m "feat: add provider market to five league pipeline"
```

### Task 4: 真实续跑、覆盖审计与候选再训练

**Files:**
- Create: `project021_五大联赛APIFootball训练/05_交付/provider_market_coverage_report.json`
- Modify: `project021_五大联赛APIFootball训练/05_交付/five_league_pipeline_report.json`
- Modify: `project021_五大联赛APIFootball训练/03_模型/*_candidate.json`

**Interfaces:**
- Consumes: 现有 8,956 场标准化赛果、用户级 `APIFOOTBALL_COM_KEY`、Task 3 流水线。
- Produces: 五个使用 `provider_market` 验证的 candidate 报告；任何数据缺口必须以 `partial`、`UNAVAILABLE` 或拒绝原因呈现。

- [ ] **Step 1: 运行全量流水线，不打印密钥**

```powershell
$env:APIFOOTBALL_COM_KEY = [Environment]::GetEnvironmentVariable('APIFOOTBALL_COM_KEY','User')
python project021_五大联赛APIFootball训练/02_脚本/run_five_league_pipeline.py --project project021_五大联赛APIFootball训练
Remove-Item Env:APIFOOTBALL_COM_KEY
```

- [ ] **Step 2: 验证报告边界和覆盖**

Run: `python -c "import json; x=json.load(open('project021_五大联赛APIFootball训练/05_交付/five_league_pipeline_report.json', encoding='utf-8')); assert 'provider_market_coverage' in x; assert all(v['training']['lifecycle']=='candidate' for v in x['leagues'].values())"`

Expected: provider 覆盖、失败日期和拒绝原因均可读取；无任何 `sporttery_compatible=true` 或生产推荐。

- [ ] **Step 3: 运行完整回归与编译校验**

Run: `python -m pytest -q project007_APIFootball数据接入/02_脚本/test_apifootball_com_adapter.py project007_APIFootball数据接入/02_脚本/test_download_apifootball_com_history.py project007_APIFootball数据接入/02_脚本/test_download_apifootball_com_odds.py project007_APIFootball数据接入/02_脚本/test_team_strength_training.py project021_五大联赛APIFootball训练/02_脚本/test_train_five_leagues.py project021_五大联赛APIFootball训练/02_脚本/test_run_five_league_pipeline.py`

Expected: PASS；报告中 provider 市场仅为候选基线，不能声明优于体彩或生产市场。

- [ ] **Step 4: 提交轻量工件和报告**

```powershell
git add project021_五大联赛APIFootball训练/03_模型 project021_五大联赛APIFootball训练/05_交付
git commit -m "data: evaluate five leagues against provider market"
```
