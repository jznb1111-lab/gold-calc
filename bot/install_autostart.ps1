# Устанавливает автозапуск бота в фоне (Планировщик заданий Windows).
# Запускается через install_autostart.bat — двойным щелчком.
$ErrorActionPreference = "Stop"
$TaskName = "GoldCalcBot"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Service = Join-Path $Here "service.pyw"

# 1. Ищем pythonw.exe
$py = (Get-Command pythonw.exe -ErrorAction SilentlyContinue | Select-Object -First 1).Source
if (-not $py) {
    $pyExe = (Get-Command python.exe -ErrorAction SilentlyContinue | Where-Object { $_.Source -notlike "*WindowsApps*" } | Select-Object -First 1).Source
    if ($pyExe) { $py = Join-Path (Split-Path $pyExe) "pythonw.exe" }
}
if (-not $py -or -not (Test-Path $py)) {
    Write-Host "Не найден Python. Установите его с python.org (галочка 'Add Python to PATH') и запустите снова." -ForegroundColor Red
    exit 1
}
Write-Host "Python: $py"

# 2. Проверяем .env
if (-not (Test-Path (Join-Path $Here ".env"))) {
    Write-Host "Нет файла .env в папке bot. Скопируйте .env.example в .env и впишите BOT_TOKEN." -ForegroundColor Red
    exit 1
}

# 3. Ставим библиотеки
$pyConsole = Join-Path (Split-Path $py) "python.exe"
Write-Host "Устанавливаю библиотеки..."
& $pyConsole -m pip install --disable-pip-version-check -q -r (Join-Path $Here "requirements.txt")

# 4. Создаём задание: запуск при входе в Windows, без окна, перезапуск при сбое
$action   = New-ScheduledTaskAction -Execute $py -Argument "`"$Service`"" -WorkingDirectory $Here
$trigger  = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
            -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
            -MultipleInstances IgnoreNew -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -Principal $principal -Description "Telegram-бот калькулятора XAUUSD (@Lotcalcubot)" -Force | Out-Null

# 5. Останавливаем старую копию (если бот был запущен вручную) и запускаем
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" |
    Where-Object { $_.CommandLine -like "*service.pyw*" -or $_.CommandLine -like "*bot.py*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 1
Start-ScheduledTask -TaskName $TaskName

Write-Host ""
Write-Host "Готово! Бот запущен в фоне и будет сам стартовать при входе в Windows." -ForegroundColor Green
Write-Host "Журнал работы: $(Join-Path $Here 'bot.log')"
