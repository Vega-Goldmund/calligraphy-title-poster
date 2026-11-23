@echo off
chcp 65001 >nul
echo 正在停止片名工作台...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -match 'workbench' -and $_.CommandLine -match 'server\.py' }; if ($p) { $p | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host ('已停止 PID ' + $_.ProcessId) } } else { Write-Host '没有找到运行中的片名工作台' }"
pause
