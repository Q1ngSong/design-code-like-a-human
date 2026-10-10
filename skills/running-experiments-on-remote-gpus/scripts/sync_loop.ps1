# 周期调用 sync_remote_outputs.py,直到停止文件出现。启动方式见 references/remote-operations.md 第 8 节。
# 停止:创建停止文件;当前一轮结束后 10 秒内退出,并输出 LOOP STOPPED。
param(
  [Parameter(Mandatory = $true)][string]$Python,
  [Parameter(Mandatory = $true)][string]$Config,
  [Parameter(Mandatory = $true)][string]$StopFile,
  [int]$IntervalSeconds = 1200
)
$ErrorActionPreference = "Continue"
$env:PYTHONUTF8 = "1"
while (-not (Test-Path $StopFile)) {
  Write-Output "=== PASS $(Get-Date -Format o) ==="
  & $Python "$PSScriptRoot/sync_remote_outputs.py" $Config
  Write-Output "=== PASS exit=$LASTEXITCODE $(Get-Date -Format o) ==="
  for ($waited = 0; $waited -lt $IntervalSeconds -and -not (Test-Path $StopFile); $waited += 10) { Start-Sleep -Seconds 10 }
}
Write-Output "=== LOOP STOPPED $(Get-Date -Format o) ==="
