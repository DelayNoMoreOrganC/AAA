@echo off
REM V4 依赖安装脚本

echo Installing V4 dependencies...
pip install -r ..\requirements.txt

echo.
echo Verifying installation...
python scripts\verify_deps.py

pause
