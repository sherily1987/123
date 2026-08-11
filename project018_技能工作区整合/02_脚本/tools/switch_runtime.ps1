param(
    [ValidateSet('Verify', 'Switch')]
    [string]$Mode = 'Verify',
    [string]$CanonicalSkill,
    [string]$CanonicalCore,
    [string]$CanonicalData,
    [string]$CanonicalPlugin
)

$ErrorActionPreference = 'Stop'

$skillLink = 'C:\Users\Administrator\.codex\skills\football-quant-fusion'
$pluginLink = 'C:\Users\Administrator\plugins\football-quant-fusion'
$verification = & (Join-Path $PSScriptRoot 'verify_runtime.ps1') -CanonicalSkill $CanonicalSkill -CanonicalCore $CanonicalCore -CanonicalData $CanonicalData -CanonicalPlugin $CanonicalPlugin | ConvertFrom-Json
if (-not $verification.ready -or -not $verification.all_paths_on_f_drive) {
    throw 'Canonical workspace verification failed; refusing to switch runtime.'
}
$CanonicalSkill = $verification.canonical_skill
$CanonicalCore = $verification.canonical_core
$CanonicalData = $verification.canonical_data
$CanonicalPlugin = $verification.canonical_plugin

function Test-JunctionTarget {
    param([string]$Path, [string]$ExpectedTarget)
    if (-not (Test-Path -LiteralPath $Path)) { return $false }
    $item = Get-Item -LiteralPath $Path
    if ($item.LinkType -ne 'Junction' -or -not $item.Target) { return $false }
    $actual = [IO.Path]::GetFullPath([string]($item.Target | Select-Object -First 1)).TrimEnd('\\')
    $expected = [IO.Path]::GetFullPath($ExpectedTarget).TrimEnd('\\')
    return $actual -ieq $expected
}

function Remove-JunctionOnly {
    param([string]$Path)
    $item = Get-Item -LiteralPath $Path
    if ($item.LinkType -ne 'Junction') {
        throw "Refusing to remove non-Junction path: $Path"
    }
    # .NET removes the reparse-point entry itself; it does not traverse into its target.
    [System.IO.Directory]::Delete($Path)
    if (Test-Path -LiteralPath $Path) {
        throw "Junction removal did not complete: $Path"
    }
}

$state = [ordered]@{
    checked_at = (Get-Date).ToString('o')
    mode = $Mode
    skill_link = $skillLink
    plugin_link = $pluginLink
    canonical_skill = $CanonicalSkill
    canonical_core = $CanonicalCore
    canonical_data = $CanonicalData
    canonical_plugin = $CanonicalPlugin
    prior_skill_target = if (Test-Path -LiteralPath $skillLink) { (Get-Item -LiteralPath $skillLink).Target } else { $null }
    prior_plugin_target = if (Test-Path -LiteralPath $pluginLink) { (Get-Item -LiteralPath $pluginLink).Target } else { $null }
}
if ($Mode -eq 'Verify') { $state | ConvertTo-Json -Depth 4; exit 0 }

if (-not (Test-JunctionTarget -Path $skillLink -ExpectedTarget $CanonicalSkill)) {
    if ((Get-Item -LiteralPath $skillLink).LinkType -ne 'Junction') {
        throw "Refusing to replace non-Junction skill path: $skillLink"
    }
    Remove-JunctionOnly -Path $skillLink
    New-Item -ItemType Junction -Path $skillLink -Target $CanonicalSkill | Out-Null
}
$backupToken = Get-Date -Format 'yyyyMMdd_HHmmss'
$pluginBackup = "$pluginLink.pre-migration-$backupToken"
if (-not (Test-JunctionTarget -Path $pluginLink -ExpectedTarget $CanonicalPlugin)) {
    if (Test-Path -LiteralPath $pluginLink) {
        $item = Get-Item -LiteralPath $pluginLink
        if ($item.LinkType -eq 'Junction') {
            Remove-JunctionOnly -Path $pluginLink
        } else {
            Move-Item -LiteralPath $pluginLink -Destination $pluginBackup
        }
    }
    New-Item -ItemType Junction -Path $pluginLink -Target $CanonicalPlugin | Out-Null
    $state.plugin_backup = if (Test-Path -LiteralPath $pluginBackup) { $pluginBackup } else { $null }
}
[Environment]::SetEnvironmentVariable('FUSION_WORKSPACE_ROOT', (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))), 'User')
[Environment]::SetEnvironmentVariable('FUSION_DATA_ROOT', $CanonicalData, 'User')
[Environment]::SetEnvironmentVariable('FUSION_CORE_DIR', $CanonicalCore, 'User')
$state.completed_at = (Get-Date).ToString('o')
$state | ConvertTo-Json -Depth 4
