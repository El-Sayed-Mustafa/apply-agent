@echo off
REM -- Apply Agent: التقديم (src.apply) — بيتنادى من Task Scheduler كل نص ساعة
REM لو مفيش حاجة مستنية، بيخلص في ثواني من غير ما يفتح متصفح.

setlocal
cd /d "%~dp0.."
if not exist "logs" mkdir "logs"

set "PY=%CD%\.venv\Scripts\python.exe"
if not exist "%PY%" (
    echo [%date% %time%] venv missing: %PY% >> "logs\apply.log"
    exit /b 1
)
set PYTHONIOENCODING=utf-8

echo [%date% %time%] start >> "logs\apply.log"
"%PY%" -u -m src.apply >> "logs\apply.log" 2>&1
set RC=%ERRORLEVEL%
echo [%date% %time%] done rc=%RC% >> "logs\apply.log"
exit /b %RC%
