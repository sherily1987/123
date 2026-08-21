<#
国际赔率分时快照（研究用途）

在 Windows 计划任务中分别于各批次相应的 T-24h、T-6h、T-75m 时段调用本脚本即可。
脚本不会创建或修改计划任务，不会显示 API 密钥，也不会修改生产概率或推荐。
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$MatchFile,
    [Parameter(Mandatory = $true)]
    [string]$ReportFile,
    [string]$Now,
    [int]$WindowMinutes = 15,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$workspace = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$cli = Join-Path $workspace '02_脚本\skill\football-quant-fusion\scripts\fusion_cli.py'
$dataRoot = Join-Path $workspace '04_素材\shared-data\football-quant-fusion\odds'

$args = @('odds-intl-capture', '--match-file', $MatchFile, '--out', $ReportFile,
    '--store', $dataRoot, '--window-minutes', $WindowMinutes)
if ($Now) { $args += @('--now', $Now) }
if ($DryRun) { $args += '--dry-run' }

python $cli @args
if ($LASTEXITCODE -ne 0) {
    throw "国际赔率分时快照失败，退出码：$LASTEXITCODE"
}
