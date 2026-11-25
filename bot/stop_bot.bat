@echo off
chcp 65001 >nul
schtasks /End /TN "GoldCalcBot" >nul 2>&1
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe' OR Name='python.exe'\" | Where-Object { $_.CommandLine -like '*service.pyw*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
echo Бот остановлен. Снова запустить: start_bot.bat (или он сам запустится при следующем входе в Windows).
timeout /t 4 >nul
