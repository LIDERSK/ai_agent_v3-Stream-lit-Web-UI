' Vytvori ikonu "AI Agent" na ploche a v ponuke Start (spusta sa bez cmd okna).
Dim sh, fso, dir, place, lnk
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
For Each place In Array(sh.SpecialFolders("Desktop"), sh.SpecialFolders("Programs"))
  Set lnk = sh.CreateShortcut(place & "\AI Agent.lnk")
  lnk.TargetPath = "wscript.exe"
  lnk.Arguments = """" & dir & "\start_agent_hidden.vbs"""
  lnk.WorkingDirectory = dir
  lnk.IconLocation = "shell32.dll,13"
  lnk.Description = "Lokalny AI Agent"
  lnk.Save
Next
MsgBox "Hotovo. Ikona 'AI Agent' je na ploche a v ponuke Start.", 64, "AI Agent"
