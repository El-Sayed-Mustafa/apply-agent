# ═══════════════════════════════════════════════════════════════════════
# تسجيل مهمة دعوات LinkedIn في Task Scheduler.
#
#   powershell -ExecutionPolicy Bypass -File scripts\install-task.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\install-task.ps1 -Remove
#
# مفيش صلاحيات مدير — المهمة بتتسجّل لحسابك إنت.
#
# ثلاثة قرارات في الجدولة:
#
#   · 4 مرات في اليوم، مش كل ساعة. الميزانية 12 دعوة في اليوم،
#     والتشغيلات الزيادة بتقف قبل ما تفتح المتصفح فمش بتكلّف حاجة —
#     بس مفيش داعي أصلاً.
#
#   · تأخير عشوائي لحد 40 دقيقة. التشغيل الساعة 9:00 بالظبط كل يوم
#     إيقاع آلة. ده بيشيله.
#
#   · بتشتغل وإنت مسجّل دخول بس. المتصفح محتاج جلسة تفاعلية، والملف
#     الشخصي بتاع Chrome على حسابك.
# ═══════════════════════════════════════════════════════════════════════

param([switch]$Remove)

$TaskName = "ApplyAgent-LinkedIn"
$Root     = Split-Path -Parent $PSScriptRoot
$Script   = Join-Path $Root "scripts\run-connect.cmd"

if ($Remove) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Output "اتشالت: $TaskName"
    } else {
        Write-Output "مش موجودة أصلاً."
    }
    return
}

if (-not (Test-Path $Script)) {
    Write-Error "مش لاقي $Script"
    return
}

# ── المحفّزات: 4 مواعيد في اليوم ──
$Times = @("09:20", "13:40", "17:10", "20:30")
$Triggers = foreach ($t in $Times) {
    $tr = New-ScheduledTaskTrigger -Daily -At $t
    # التأخير العشوائي بيتحط على الـ XML مباشرة — الـ cmdlet مفيهوش
    $tr.RandomDelay = "PT40M"
    $tr
}

$Action = New-ScheduledTaskAction -Execute $Script -WorkingDirectory $Root

$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 25) `
    -MultipleInstances IgnoreNew

# S4U: بتشتغل من غير ما تحفظ كلمة السر، وبتحتاج جلسة مفتوحة.
# المتصفح محتاج الاتنين.
$Principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Triggers `
    -Settings $Settings -Principal $Principal `
    -Description "دعوات LinkedIn — Apply Agent. الميزانية والوقف في الكود." | Out-Null

Write-Output "اتسجّلت: $TaskName"
Write-Output ""
Write-Output "المواعيد:  $($Times -join '  ·  ')   (+ تأخير عشوائي لحد 40 دقيقة)"
Write-Output "السكريبت:  $Script"
Write-Output "السجل:     $Root\logs\connect.log"
Write-Output ""
Write-Output "تشغيل فوري للتجربة:"
Write-Output "   Start-ScheduledTask -TaskName $TaskName"
Write-Output ""
Write-Output "للإيقاف:"
Write-Output "   Disable-ScheduledTask -TaskName $TaskName"
Write-Output "للحذف:"
Write-Output "   powershell -ExecutionPolicy Bypass -File scripts\install-task.ps1 -Remove"
