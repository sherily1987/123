param(
    [string]$CanonicalSkill,
    [string]$CanonicalCore,
    [string]$CanonicalData,
    [string]$CanonicalPlugin
)

$scriptsRoot = Split-Path -Parent $PSScriptRoot
$projectRoot = Split-Path -Parent $scriptsRoot
$materialsRoot = (Get-ChildItem -LiteralPath $projectRoot -Directory | Where-Object { $_.Name -match '^04_' }).FullName
$deliveryRoot = (Get-ChildItem -LiteralPath $projectRoot -Directory | Where-Object { $_.Name -match '^05_' }).FullName
if (-not $CanonicalSkill) { $CanonicalSkill = Join-Path $scriptsRoot 'skill\football-quant-fusion' }
if (-not $CanonicalCore) { $CanonicalCore = Join-Path $scriptsRoot 'core\zu-yu-dashi-3\scripts' }
if (-not $CanonicalData) { $CanonicalData = Join-Path $materialsRoot 'shared-data\football-quant-fusion' }
if (-not $CanonicalPlugin) { $CanonicalPlugin = Join-Path $deliveryRoot 'plugin\football-quant-fusion' }

$required = @(
    (Join-Path $CanonicalSkill "SKILL.md"),
    (Join-Path $CanonicalSkill "scripts\fusion_cli.py"),
    (Join-Path $CanonicalCore "predict.py"),
    (Join-Path $CanonicalData "backtest"),
    (Join-Path $CanonicalPlugin ".codex-plugin\plugin.json")
)
$missing = @($required | Where-Object { -not (Test-Path -LiteralPath $_) })
[pscustomobject]@{
    canonical_skill = $CanonicalSkill
    canonical_core = $CanonicalCore
    canonical_data = $CanonicalData
    canonical_plugin = $CanonicalPlugin
    all_paths_on_f_drive = @($CanonicalSkill, $CanonicalCore, $CanonicalData, $CanonicalPlugin | ForEach-Object { $_ -like 'F:\*' }) -notcontains $false
    missing = $missing
    ready = ($missing.Count -eq 0)
} | ConvertTo-Json -Depth 3
