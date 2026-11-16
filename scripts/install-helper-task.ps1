# ═══════════════════════════════════════════════════════════════════════
# المساعد المحلي لإضافة كروم — بيشتغل لوحده أول ما تسجّل دخول على الجهاز.
#
#   powershell -ExecutionPolicy Bypass -File scripts\install-helper-task.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\install-helper-task.ps1 -Remove
#
# بيشغّل `python -m src.helper` بـpythonw (من غير شباك أسود)، على
# 127.0.0.1:8765 بس. الإضافة بتاخد منه الإجابات والسيرة؛ الإرسال ضغطتك.
# ═══════════════════════════════════════════════════════════════════════

param([switch]$Remove)

$TaskName = "ApplyAgent-Helper"
$Root     = Split-Path -Parent $PSScriptRoot
$PyW      = Join-Path $Root ".venv\Scripts\pythonw.exe"

if ($Remove) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Output "removed: $TaskName"
    } else { Write-Output "not installed" }
    return
}

if (-not (Test-Path $PyW)) { throw "venv missing: $PyW" }

$Trigger  = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$Action   = New-ScheduledTaskAction -Execute $PyW -Argument "-m src.helper" -WorkingDirectory $Root
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -MultipleInstances IgnoreNew `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME `
    -LogonType Interactive -RunLevel Limited

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger `
    -Settings $Settings -Principal $Principal `
    -Description "Apply Agent: local helper for the Chrome extension (127.0.0.1:8765)" | Out-Null

Write-Output "installed: $TaskName (starts at logon)"
