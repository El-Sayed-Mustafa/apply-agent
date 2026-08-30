@echo off
REM ── دعوات LinkedIn — بيتنادى من Task Scheduler ──────────────────────
REM
REM بيسجّل كل تشغيلة في logs\connect.log. لو الميزانية خلصت، السكريبت
REM بيقف قبل ما يفتح المتصفح أصلاً — فالتشغيلة بتخلص في ثانية.

setlocal
cd /d "%~dp0.."

if not exist "logs" mkdir "logs"

set "PY=%CD%\.venv\Scripts\python.exe"
if not exist "%PY%" (
    echo [%date% %time%] البيئة مش موجودة: %PY% >> "logs\connect.log"
    exit /b 1
)

set PYTHONIOENCODING=utf-8

echo. >> "logs\connect.log"
echo ================================================== >> "logs\connect.log"
echo [%date% %time%] بدأت >> "logs\connect.log"

"%PY%" -u -m src.connect --send >> "logs\connect.log" 2>&1
set RC=%ERRORLEVEL%

echo [%date% %time%] خلصت — كود الخروج %RC% >> "logs\connect.log"

REM كود 1 معناه LinkedIn اعترض. Task Scheduler بيسجّله، وتقدر تشوفه
REM في تاريخ المهمة — وساعتها متشغّلش تاني في نفس اليوم.
exit /b %RC%
