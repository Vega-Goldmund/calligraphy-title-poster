@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -u server.py --detach
if errorlevel 1 (
  echo.
  echo 启动失败：请确认 python 在 PATH 中，且已安装 requirements.txt 依赖。
  pause
)
