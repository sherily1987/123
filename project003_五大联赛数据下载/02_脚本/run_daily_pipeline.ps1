# 每日融合流水线（配合 Windows 任务计划程序定时运行）
# 用法:  powershell -ExecutionPolicy Bypass -File run_daily_pipeline.ps1 [-KickoffDate 2026-08-03]
# 默认采集今天的开球日场次；若晚上运行可传明天的日期。
param([string]$KickoffDate = '')

$ErrorActionPreference = 'Stop'
$cli = 'C:\Users\Administrator\.codex\skills\football-quant-fusion-suite\skills\football-quant-fusion\scripts\fusion_cli.py'
$logDir = 'H:\claude AI自媒体\project003_五大联赛数据下载\04_素材\daily_pipeline_logs'

New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$date = if ($KickoffDate) { $KickoffDate } else { (Get-Date).ToString('yyyy-MM-dd') }
$log = Join-Path $logDir ($date + '.log')

python $cli 'daily-pipeline' '--kickoff-date' $date 2>&1 | Out-File -FilePath $log -Encoding utf8
Write-Output "done -> $log"
