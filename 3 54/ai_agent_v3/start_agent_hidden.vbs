' Spusti AI Agenta bez cmd okna a otvori prehliadac. Dvojklik alebo ikona na ploche.
Option Explicit
Dim sh, fso, dir, http, i, ready, port
port = "8501"
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = dir
If Not fso.FolderExists(dir & "\logs") Then fso.CreateFolder(dir & "\logs")

Function IsUp()
  On Error Resume Next
  Dim h
  Set h = CreateObject("MSXML2.ServerXMLHTTP.6.0")
  h.setTimeouts 500, 500, 500, 500
  h.open "GET", "http://localhost:" & port & "/_stcore/health", False
  h.send
  IsUp = (Err.Number = 0 And h.status = 200)
  On Error GoTo 0
End Function

If Not IsUp() Then
  ' 0 = skryte okno; vystup ide do logs\agent.log
  sh.Run "cmd /c python -m streamlit run app.py --server.headless true --server.port " & port & _
         " --browser.gatherUsageStats false > ""logs\agent.log"" 2>&1", 0, False
  ready = False
  For i = 1 To 60
    WScript.Sleep 500
    If IsUp() Then ready = True : Exit For
  Next
  If Not ready Then
    MsgBox "Aplikacia sa nespustila do 30 sekund. Pozri logs\agent.log" & vbCrLf & _
           "(je nainstalovany Python a 'pip install -r requirements.txt'?)", 48, "AI Agent"
    WScript.Quit 1
  End If
End If
sh.Run "http://localhost:" & port
