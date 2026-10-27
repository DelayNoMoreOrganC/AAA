@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PYTHON="
set "PYARGS="
where python >nul 2>nul && for /f "delims=" %%P in ('where python 2^>nul') do set "PYTHON=%%P" & goto :run
where py >nul 2>nul && for /f "delims=" %%P in ('where py 2^>nul') do set "PYTHON=%%P" & set "PYARGS=-3" & goto :run
echo Python not found
pause
exit /b 1

:run
cd /d "%~dp0app\web\backend"
echo Server: http://127.0.0.1:8000
"%PYTHON%" %PYARGS% run.py
pause
