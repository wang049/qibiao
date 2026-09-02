@echo off
cd /d "%~dp0"
if /i "%~1"=="INNER" goto :main
cmd /k call "%~f0" INNER
exit /b

:main
setlocal EnableExtensions EnableDelayedExpansion
set "ROOT=%~dp0"
if "!ROOT:~-1!"=="\" set "ROOT=!ROOT:~0,-1!"
set "PY=!ROOT!\python\python.exe"
set "PYDIR=!ROOT!\python"
set "APP=!ROOT!\app"
set "MARKER=!PYDIR!\.deps-ok"
set "PTH=!PYDIR!\python312._pth"
set "SITE=!PYDIR!\Lib\site-packages"

echo Console mode. Close this window to stop.
echo.

if exist "!PY!" goto :have_py
echo 找不到内置 Python。
call :hint_extract
goto :end
:have_py

if exist "!APP!\electrical_krow\__init__.py" goto :have_app
echo 找不到程序文件 app\electrical_krow。
call :hint_extract
goto :end
:have_app

set "ELECTRICAL_ROOT=!APP!\electrical"
set "ELECTRICAL_KROW_CONFIG=!ROOT!\config.ini"
set "ELECTRICAL_KROW_DATA=%LOCALAPPDATA%\electrical-krow"
set "KROW_UVICORN_LOG=info"

if exist "!MARKER!" goto :after_pip
echo 依赖没有预装进本目录。请改用完整解压后的 zip，不要用安装失败的残缺目录。
goto :end
:after_pip

if not exist "!SITE!" mkdir "!SITE!"
copy /y "!ROOT!\python312._pth" "!PTH!" >nul
copy /y "!ROOT!\sitecustomize.py" "!SITE!\sitecustomize.py" >nul
if not exist "!ELECTRICAL_KROW_DATA!" mkdir "!ELECTRICAL_KROW_DATA!"

echo Console mode. Close this window to stop. Native app window will open.
echo.
"!PY!" "!ROOT!\run.py"
echo.
echo Server exited. Code !ERRORLEVEL!

:end
echo.
pause
exit /b 0

:hint_extract
echo 当前目录: !ROOT!
echo 期望文件: !ROOT!\python\python.exe
echo.
echo 常见原因：
echo   1. 在压缩包窗口里直接双击了（Windows 只会抽出这一个文件）
echo   2. 用了上次 exe 安装失败留下的残缺目录
echo.
echo 正确做法：
echo   右键 zip - 全部解压，进入 electrical-krow-windows 文件夹，
echo   确认里面有 python 文件夹，再双击「启动SOR填表.exe」。
echo   不要双击失败的 %LOCALAPPDATA%\electrical-krow-app 里的脚本。
echo.
exit /b 0
