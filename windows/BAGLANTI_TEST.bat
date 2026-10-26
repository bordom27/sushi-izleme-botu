@echo off
chcp 65001 >nul
cd /d "%~dp0.."
echo Binance baglanti testi (emir acmaz)...
python k69_test.py
pause
