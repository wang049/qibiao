Set sh = CreateObject("Wscript.Shell")
cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ""$c = Get-NetTCPConnection -LocalPort 18765 -State Listen -ErrorAction SilentlyContinue; if ($c) { $c | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }; exit 0 } else { exit 1 }"""
rc = sh.Run(cmd, 0, True)
If rc = 0 Then
  MsgBox "已停止出表服务。", 64, "电子电器 SOR填表"
Else
  MsgBox "当前没有在运行。", 64, "电子电器 SOR填表"
End If
