@echo off
REM 双击此文件会打开保持不关的安装窗口（避免闪退看不到报错）
cd /d "%~dp0"
start "ArchiveV6 Install" cmd /k call "%~dp0install.bat"
