# ═══════════════════════════════════════════════════════════════════════
# مهمة التقديم في Task Scheduler — كل نص ساعة من 8 الصبح لـ12 بالليل.
#
#   powershell -ExecutionPolicy Bypass -File scripts\install-apply-task.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\install-apply-task.ps1 -Remove
#
# بتعمل إيه: الوظايف اللي دُست عليها "✅ قدّم" بتتجهّز وتتملى، وردودك على
# أسئلة الفورم بتتقرا، واللي دُست فيه "📤 ابعت" بيتبعت.
# مفيش إرسال من غير ضغطة "📤 ابعت" منك على تليجرام.
# بتشتغل وإنت مسجّل دخول بس: الإرسال بيفتح متصفح ظاهر.
# ═══════════════════════════════════════════════════════════════════════

param([switch]$Remove)

$TaskName = "ApplyAgent-Apply"
$Root     = Split-Path -Parent $PSScriptRoot
$Script   = Join-Path $Root "scripts\run-apply.cmd"

if ($Remove) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Output "removed: $TaskName"
    } else { Write-Output "not installed" }
    return
}

$Trigger = New-ScheduledTaskTrigger -Daily -At "08:00"
$Trigger.Repetition = (New-ScheduledTaskTrigger -Once -At "08:00" `
    -RepetitionInterval (New-TimeSpan -Minutes 30) `
    -RepetitionDuration (New-TimeSpan -Hours 16)).Repetition

$Action = New-ScheduledTaskAction -Execute $Script -WorkingDirectory $Root
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 20) -MultipleInstances IgnoreNew
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME `
    -LogonType Interactive -RunLevel Limited

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger `
    -Settings $Settings -Principal $Principal `
    -Description "Apply Agent: prepare, fill, and submit after Telegram approval" | Out-Null

Write-Output "installed: $TaskName (every 30 min, 08:00-24:00)"
Write-Output "log: $Root\logs\apply.log"
