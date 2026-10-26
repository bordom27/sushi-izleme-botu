@echo off
chcp 65001 >nul
cd /d "%~dp0.."
echo === K69 islem botu kurulumu ===
where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo Python bulunamadi. python.org adresinden Python 3.11 veya ustunu kur
  echo ^(kurulumda "Add python.exe to PATH" kutusunu isaretle^), sonra bu dosyayi tekrar calistir.
  pause
  exit /b 1
)
python -m pip install -q -r requirements.txt
if errorlevel 1 (
  echo Kutuphaneler kurulamadi. Internet baglantisini kontrol et.
  pause
  exit /b 1
)
if not exist k69_islem.env (
  copy /y k69_islem.env.ornek k69_islem.env >nul
)
echo.
echo Simdi Not Defteri acilacak: API Key, Secret Key ve Telegram bilgilerini yapistir, kaydet, kapat.
notepad k69_islem.env
echo.
echo Baglanti testi yapiliyor...
python k69_test.py
if errorlevel 1 (
  echo.
  echo Test basarisiz. Yukaridaki hatayi Claude'a ilet.
  pause
  exit /b 1
)
echo.
echo Saatlik gorev olusturuluyor (her saatin 7. dakikasi)...
schtasks /create /f /tn "K69 Islem Botu" /sc hourly /mo 1 /st 00:07 /tr "wscript.exe \"%CD%\windows\gizli_calistir.vbs\"" >nul
if errorlevel 1 (
  echo Gorev olusturulamadi. Bu dosyaya sag tikla, "Yonetici olarak calistir" ile tekrar dene.
  pause
  exit /b 1
)
powershell -NoProfile -Command "$s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 50); Set-ScheduledTask -TaskName 'K69 Islem Botu' -Settings $s | Out-Null"
echo.
echo Kurulum tamam. Bot her saatin 7. dakikasinda arka planda calisacak.
echo Kayitlar: %CD%\k69_log.txt
echo Ilk calistirma simdi basliyor (birkac dakika surer, pencere arka planda).
wscript.exe "%CD%\windows\gizli_calistir.vbs"
pause
