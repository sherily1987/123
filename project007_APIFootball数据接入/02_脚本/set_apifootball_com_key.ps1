<#
  Securely set the user-level APIFOOTBALL_COM_KEY without putting the key
  in project files, command history, or terminal output.
#>
$secure = Read-Host "Enter apifootball.com API Key (input hidden)" -AsSecureString
$ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
    $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
    if ([string]::IsNullOrWhiteSpace($plain)) {
        throw "Key cannot be empty"
    }
    [Environment]::SetEnvironmentVariable("APIFOOTBALL_COM_KEY", $plain, "User")
    $env:APIFOOTBALL_COM_KEY = $plain
    Write-Output "User-level APIFOOTBALL_COM_KEY configured (value hidden)"
}
finally {
    if ($ptr -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
    }
    $plain = $null
}
