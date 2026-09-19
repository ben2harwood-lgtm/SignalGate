@echo off
setlocal
cd /d "%~dp0\.."

echo SignalGate MT5 compile evidence harness
echo.
echo This compiles mt5_ea\SignalGateEA.mq5 with MetaEditor and requires 0 errors / 0 warnings.
echo MetaEditor and the MQL5 data root are auto-detected only when exactly one safe candidate exists.
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0capture_mt5_compile_evidence.ps1" %*
set EXITCODE=%ERRORLEVEL%

echo.
if "%EXITCODE%"=="0" (
  echo PASS - compile evidence was written under artifacts\mt5-acceptance.
) else (
  echo FAIL - no accepted compile receipt was produced. Exit code %EXITCODE%.
)
exit /b %EXITCODE%
