# 每日自动回测（配合 Windows 任务计划程序运行）
# 用法:  powershell -ExecutionPolicy Bypass -File run_auto_backtest.ps1
# 流程：回填共享库赛果 -> 共享库量化回测 -> 各项目待回测目录双轨回测 -> 合并报告
param([string]$Workspace = 'H:\claude AI自媒体')

$ErrorActionPreference = 'Stop'
$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
$py = 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$script = 'C:\Users\Administrator\.codex\skills\football-quant-fusion-suite\skills\football-quant-fusion\scripts\auto_backtest.py'
$outDir = 'H:\claude AI自媒体\project003_五大联赛数据下载\05_交付\auto_backtest'
$logDir = 'H:\claude AI自媒体\project003_五大联赛数据下载\04_素材\auto_backtest_logs'

New-Item -ItemType Directory -Force -Path $logDir, $outDir | Out-Null
$date = (Get-Date).ToString('yyyy-MM-dd')
$log = Join-Path $logDir ($date + '.log')

& $py $script --workspace $Workspace --output-dir $outDir 2>&1 | Out-File -FilePath $log -Encoding utf8
Write-Output "done -> $log"
