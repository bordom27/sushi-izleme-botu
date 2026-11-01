@echo off
chcp 65001 >nul
cd /d "%~dp0.."
python telegram_kontrol.py
