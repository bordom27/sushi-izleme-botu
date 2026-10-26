@echo off
chcp 65001 >nul
echo K69 gorevi: pilde de calissin, kacirilan calistirma bilgisayar uyaninca yapilsin...
powershell -NoProfile -Command "$s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 50); Set-ScheduledTask -TaskName K69 Islem Botu -Settings $s | Out-Null; (Get-ScheduledTask -TaskName K69 Islem Botu).Settings | Select-Object DisallowStartIfOnBatteries,StopIfGoingOnBatteries,StartWhenAvailable | Format-List; Get-ScheduledTaskInfo -TaskName K69 Islem Botu | Select-Object LastRunTime,NextRunTime | Format-List"
pause
