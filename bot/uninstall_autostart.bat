@echo off
chcp 65001 >nul
call "%~dp0stop_bot.bat"
schtasks /Delete /TN "GoldCalcBot" /F >nul 2>&1
echo Автозапуск удалён. Бот больше не будет стартовать сам.
pause
