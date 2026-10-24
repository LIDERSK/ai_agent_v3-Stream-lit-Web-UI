' Zastavi skryty AI Agent (proces, ktory pocuva na porte 8501).
Dim sh
Set sh = CreateObject("WScript.Shell")
sh.Run "cmd /c for /f ""tokens=5"" %a in ('netstat -ano ^| findstr :8501 ^| findstr LISTENING') do taskkill /PID %a /F", 0, True
MsgBox "AI Agent bol zastaveny.", 64, "AI Agent"
