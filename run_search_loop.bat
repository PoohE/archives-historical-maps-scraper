@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Запуск поиска ИГИС с автоматическим возобновлением...

:loop
python -u run_search.py --resume
if %errorlevel% equ 0 (
    echo.
    echo Поиск завершён успешно.
    pause
    exit /b 0
)
echo.
echo Поиск прерван (код %errorlevel%), возобновляю через 5 секунд...
timeout /t 5 /nobreak >nul
goto loop
