@echo off
title Sistem Pencatatan Woodchip & Upah PLTU
color 0A
echo ================================================================
echo    SISTEM LOGISTIK WOODCHIP & PENGIRIMAN PLTU DENGAN QR SCANNER
echo ================================================================
echo.

cd /d "%~dp0"

echo [1/3] Menyiapkan direktori dan dependensi...
set PYTHON_EXE=C:\Users\MSI\.gemini\antigravity\scratch\.venv\Scripts\python.exe

if not exist "%PYTHON_EXE%" (
    echo [ERROR] Virtual environment tidak ditemukan di C:\Users\MSI\.gemini\antigravity\scratch\.venv!
    pause
    exit /b 1
)

echo [2/3] Memeriksa inisialisasi database...
"%PYTHON_EXE%" seed_data.py

echo.
echo [3/3] Menjalankan Server Web Woodchip Logistics...
echo ----------------------------------------------------------------
echo   * Akses dari Komputer ini: http://localhost:8000
echo   * Scanner QR Driver Mobile: http://localhost:8000/scanner
echo ----------------------------------------------------------------
echo.
echo Tekan CTRL+C di jendela ini untuk menghentikan server.
echo.

"%PYTHON_EXE%" -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload

pause
