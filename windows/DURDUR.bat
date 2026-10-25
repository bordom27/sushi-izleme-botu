@echo off
chcp 65001 >nul
echo K69 islem botunun saatlik gorevi siliniyor (acik pozisyonlar Binance'te stop/hedef emirleriyle kalir).
schtasks /delete /f /tn "K69 Islem Botu"
pause
