' K69 islem botunu pencere acmadan bir kez calistirir; ciktiyi k69_log.txt dosyasina ekler.
Set fso = CreateObject("Scripting.FileSystemObject")
klasor = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = klasor
sh.Run "cmd /c chcp 65001 >nul & set PYTHONIOENCODING=utf-8 & python k69_islem_kos.py --tek >> k69_log.txt 2>&1", 0, False
