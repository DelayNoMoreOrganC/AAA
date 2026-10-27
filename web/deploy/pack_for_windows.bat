@echo off
REM ============================================
REM  案件归档系统 V6 - Windows 部署包生成脚本
REM  在开发机上运行，生成 v6_deploy.zip
REM ============================================
chcp 65001 >nul
setlocal EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
set "WEB_DIR=%SCRIPT_DIR%.."
set "GD_ROOT=%WEB_DIR%\.."
set "TMPDIR=%TEMP%\v6_deploy_pkg"
set "OUTZIP=%TEMP%\v6_deploy.zip"

echo.
echo === 案件归档 V6 部署包打包 ===
echo 项目根目录: %GD_ROOT%
echo.

REM ---------- 1. 构建前端 ----------
where npm >nul 2>nul
if errorlevel 1 (
  echo [WARN] 未找到 npm，跳过前端构建。请确保 frontend\dist 已存在。
) else (
  echo [1/4] 构建前端...
  pushd "%WEB_DIR%\frontend"
  call npm install
  if errorlevel 1 (
    echo [ERROR] npm install 失败
    popd
    pause
    exit /b 1
  )
  call npm run build
  if errorlevel 1 (
    echo [ERROR] npm run build 失败
    popd
    pause
    exit /b 1
  )
  popd
  echo [OK] 前端构建完成
)

if not exist "%WEB_DIR%\frontend\dist\index.html" (
  echo [ERROR] 缺少 frontend\dist\index.html，请先执行 npm run build
  pause
  exit /b 1
)

REM ---------- 2. 准备目录 ----------
echo [2/4] 准备打包目录...
if exist "%TMPDIR%" rmdir /s /q "%TMPDIR%"
mkdir "%TMPDIR%\app"
mkdir "%TMPDIR%\app\web"
mkdir "%TMPDIR%\app\templates"
mkdir "%TMPDIR%\app\prompts"

REM ---------- 3. 复制文件 ----------
echo [3/4] 复制运行文件...

REM V6 Web（排除运行时与缓存）
robocopy "%WEB_DIR%\backend" "%TMPDIR%\app\web\backend" /E /XD __pycache__ .pytest_cache outputs /XF *.db /NFL /NDL /NJH /NJS /nc /ns /np >nul
robocopy "%WEB_DIR%\deploy" "%TMPDIR%\app\web\deploy" /E /NFL /NDL /NJH /NJS /nc /ns /np >nul
robocopy "%WEB_DIR%\frontend\dist" "%TMPDIR%\app\web\frontend\dist" /E /NFL /NDL /NJH /NJS /nc /ns /np >nul

if exist "%WEB_DIR%\.env.example" (
  copy /Y "%WEB_DIR%\.env.example" "%TMPDIR%\app\web\.env" >nul
)

REM V4 核心：根目录全部 .py（Web 运行时通过 sys.path 桥接）
for %%f in ("%GD_ROOT%\*.py") do (
  copy /Y "%%f" "%TMPDIR%\app\" >nul
)

REM 模板与提示词
robocopy "%GD_ROOT%\templates\bundled" "%TMPDIR%\app\templates\bundled" /E /NFL /NDL /NJH /NJS /nc /ns /np >nul
robocopy "%GD_ROOT%\templates\manifests" "%TMPDIR%\app\templates\manifests" /E /NFL /NDL /NJH /NJS /nc /ns /np >nul
robocopy "%GD_ROOT%\prompts" "%TMPDIR%\app\prompts" /E /NFL /NDL /NJH /NJS /nc /ns /np >nul

if exist "%GD_ROOT%\config.json.example" (
  copy /Y "%GD_ROOT%\config.json.example" "%TMPDIR%\app\config.json.example" >nul
)

REM 安装脚本放解压根目录
copy /Y "%SCRIPT_DIR%install.bat" "%TMPDIR%\install.bat" >nul
copy /Y "%SCRIPT_DIR%install.ps1" "%TMPDIR%\install.ps1" >nul
copy /Y "%SCRIPT_DIR%打开安装窗口.bat" "%TMPDIR%\打开安装窗口.bat" >nul
copy /Y "%SCRIPT_DIR%start_server.bat" "%TMPDIR%\start_server.bat" >nul
copy /Y "%SCRIPT_DIR%install_service.bat" "%TMPDIR%\install_service.bat" >nul
copy /Y "%SCRIPT_DIR%DEPLOY_README.md" "%TMPDIR%\部署说明.md" >nul

REM ---------- 4. 压缩 ----------
echo [4/4] 压缩为 ZIP...
if exist "%OUTZIP%" del /f /q "%OUTZIP%"
powershell -NoProfile -Command "Compress-Archive -Path '%TMPDIR%\*' -DestinationPath '%OUTZIP%' -Force"
if errorlevel 1 (
  echo [ERROR] 压缩失败
  pause
  exit /b 1
)

for %%A in ("%OUTZIP%") do set "ZIPSIZE=%%~zA"
set /a ZIPSIZE_MB=!ZIPSIZE!/1048576

echo.
echo ========================================
echo  部署包已生成
echo  路径: %OUTZIP%
echo  大小: 约 !ZIPSIZE_MB! MB
echo ========================================
echo.
echo 目标机使用步骤:
echo   1. 复制 v6_deploy.zip 到目标 Windows 电脑
echo   2. 解压到任意目录，例如 D:\ArchiveV6
echo   3. 首次运行 install.bat
echo   4. 以后日常启动用 start_server.bat
echo.
pause
