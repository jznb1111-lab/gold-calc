@echo off
if exist "%~dp0bot.log" (start "" notepad "%~dp0bot.log") else (echo Журнала пока нет. & pause)
