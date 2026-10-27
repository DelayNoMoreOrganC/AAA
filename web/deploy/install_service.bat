@echo off
REM 使用 NSSM 注册为 Windows 服务（需先下载 nssm.exe 并加入 PATH）
chcp 65001 >nul
setlocal

set "SERVICE_NAME=ArchiveV6"
set "INSTALL_ROOT=%~dp0"
set "APP_DIR=%INSTALL_ROOT%app\web\backend"

set "PYTHON_CMD=python"
where python >nul 2>nul
if errorlevel 1 set "PYTHON_CMD=py -3"

for /f "delims=" %%P in ('where %PYTHON_CMD% 2^>nul') do set "PYTHON_EXE=%%P" & goto :found_py
echo [ERROR] 未找到 Python
pause
exit /b 1
:found_py

where nssm >nul 2>nul
if errorlevel 1 (
  echo [ERROR] 未找到 nssm.exe，请从 https://nssm.cc/download 下载
  pause
  exit /b 1
)

echo 安装服务 %SERVICE_NAME% ...
echo Python: %PYTHON_EXE%
echo 工作目录: %APP_DIR%

nssm install %SERVICE_NAME% "%PYTHON_EXE%" run.py
nssm set %SERVICE_NAME% AppDirectory "%APP_DIR%"
nssm set %SERVICE_NAME% AppEnvironmentExtra "PYTHONUNBUFFERED=1"
nssm set %SERVICE_NAME% Start SERVICE_AUTO_START
nssm set %SERVICE_NAME% Description "案件归档系统 V6 后端服务"
nssm set %SERVICE_NAME% AppStdout "%APP_DIR%\service_stdout.log"
nssm set %SERVICE_NAME% AppStderr "%APP_DIR%\service_stderr.log"

nssm start %SERVICE_NAME%
echo 服务已启动: http://127.0.0.1:8000
pause
