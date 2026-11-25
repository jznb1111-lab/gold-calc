@echo off
chcp 65001 >nul
schtasks /Run /TN "GoldCalcBot" >nul 2>&1 && (echo Бот запущен в фоне.) || (echo Автозапуск не установлен. Сначала запустите install_autostart.bat)
timeout /t 3 >nul
