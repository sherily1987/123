# 每日自动回测（Windows 任务计划：FootballQuantAutoBacktest）
# 用法: powershell -ExecutionPolicy Bypass -File run_auto_backtest.ps1
# 路径已迁到 F:\HM足球比赛预测，不再使用失效的 H:\claude AI自媒体。
param(
    [string]$Workspace = 'F:\HM足球比赛预测'
)

$ErrorActionPreference = 'Stop'
$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
$env:FUSION_WORKSPACE_ROOT = $Workspace
$env:FUSION_DATA_ROOT = Join-Path $Workspace 'project018_技能工作区整合\04_素材\shared-data\football-quant-fusion'

$py = 'C:\Users\Administrator\AppData\Local\Temp\hm-train-venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $py)) {
    $py = 'F:\HM足球比赛预测\project018_技能工作区整合\02_脚本\llm\football-llm-predictor\.venv\Scripts\python.exe'
}
$script = Join-Path $Workspace 'project018_技能工作区整合\02_脚本\skill\football-quant-fusion\scripts\auto_backtest.py'
$outDir = Join-Path $Workspace 'project021_五大联赛APIFootball训练\05_交付\auto_backtest'
$logDir = Join-Path $Workspace 'project021_五大联赛APIFootball训练\05_交付\auto_backtest\logs'

if (-not (Test-Path -LiteralPath $py)) { throw "python not found: $py" }
if (-not (Test-Path -LiteralPath $script)) { throw "auto_backtest.py not found: $script" }

New-Item -ItemType Directory -Force -Path $logDir, $outDir | Out-Null
$date = (Get-Date).ToString('yyyy-MM-dd')
$log = Join-Path $logDir ($date + '.log')

& $py -u $script --workspace $Workspace --output-dir $outDir 2>&1 |
    Out-File -FilePath $log -Encoding utf8
Write-Output "done -> $log"
