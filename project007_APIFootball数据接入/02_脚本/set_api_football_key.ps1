<#
  Securely set the user-level API_FOOTBALL_KEY (api-sports / v3.football.api-sports.io)
  without putting the key in project files, command history, or terminal output.

  与 set_apifootball_com_key.ps1 同款流程，但设置的是**另一个供应商**的 key：
    APIFOOTBALL_COM_KEY -> apifootball.com   （欧洲联赛，当前已可用）
    API_FOOTBALL_KEY    -> api-sports.io     （本脚本；巴甲/日职/韩K1 等）

  用法：
    powershell -ExecutionPolicy Bypass -File .\set_api_football_key.ps1
  key 获取：https://dashboard.api-football.com
  设置后需**新开一个终端**，已运行的进程读不到新值。
#>
$secure = Read-Host "Enter api-sports API Key (input hidden)" -AsSecureString
$ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
    $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
    if ([string]::IsNullOrWhiteSpace($plain)) {
        throw "Key cannot be empty"
    }
    [Environment]::SetEnvironmentVariable("API_FOOTBALL_KEY", $plain, "User")
    $env:API_FOOTBALL_KEY = $plain
    Write-Output "User-level API_FOOTBALL_KEY configured (value hidden)"
    Write-Output "Verify with: python .\api_football_adapter.py status"
}
finally {
    if ($ptr -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
    }
    $plain = $null
}
