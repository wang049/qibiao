Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("Wscript.Shell")
root = fso.GetParentFolderName(WScript.ScriptFullName)
marker = root & "\python\.deps-ok"
pyw = root & "\python\pythonw.exe"
runpy = root & "\run.py"
bat = root & "\start.bat"

If Not fso.FileExists(marker) Then
  sh.Run """" & bat & """", 1, True
  WScript.Quit 0
End If

If Not fso.FileExists(pyw) Then
  MsgBox "找不到内置 Python。请先把 zip 全部解压，进入 electrical-krow-windows 文件夹，再双击「启动SOR填表.exe」。不要在压缩包里直接双击，也不要使用安装失败的残缺目录。", 16, "电子电器 SOR填表"
  WScript.Quit 1
End If

sh.CurrentDirectory = root
sh.Run """" & pyw & """ """ & runpy & """", 1, False
