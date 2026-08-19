@echo off
REM ============================================================
REM  TGraph - Windows EXE Build Script (PyInstaller)
REM ============================================================
echo ==========================================
echo   TGraph - Derleme Basliyor...
echo ==========================================

REM Sanal ortam olustur (opsiyonel)
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo HATA: Python bulunamadi. Lutfen Python 3.11+ yukleyin.
    pause
    exit /b 1
)

echo Bagimliliklar yukleniyor...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install pyinstaller

echo Derleniyor (tek exe)...
if exist icon.ico (
    pyinstaller --onefile --windowed --name TGraph --icon=icon.ico ^
        --add-data "app;app" main.py
) else (
    pyinstaller --onefile --windowed --name TGraph ^
        --add-data "app;app" main.py
)

echo ==========================================
echo   Derleme tamamlandi! dist\TGraph.exe
echo ==========================================
pause
