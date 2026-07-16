@echo off
rem =============================================================
rem  Nahled webu SKELETA
rem  Dvojklik: stahne aktualni verzi z GitHubu, spusti lokalni
rem  server a otevre web v prohlizeci.
rem  Cerne okno nechte bezet; jeho zavrenim se nahled vypne.
rem =============================================================
cd /d "%~dp0"

rem Stahni nejnovejsi verzi z GitHubu (kdyz je k dispozici git a internet)
where git >nul 2>nul
if not errorlevel 1 (
  echo Stahuji aktualni verzi z GitHubu...
  git pull --ff-only 2>nul
)

rem Kdyz uz server bezi, jen otevri prohlizec a skonci
netstat -ano | findstr /c:":8765 " | findstr /c:"LISTENING" >nul 2>nul
if not errorlevel 1 (
  start "" http://localhost:8765
  exit /b
)

rem Najdi Python (py launcher, python v PATH, nebo prima cesta k instalaci)
set "PY="
where py >nul 2>nul
if not errorlevel 1 set "PY=py"
if not defined PY (
  where python >nul 2>nul
  if not errorlevel 1 set "PY=python"
)
if not defined PY (
  if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
)
if not defined PY (
  echo Chybi Python - nainstalujte z https://www.python.org/downloads/
  echo ^(staci vychozi instalace, pak spustte tento soubor znovu^)
  pause
  exit /b
)

start "" http://localhost:8765
echo Nahled bezi na http://localhost:8765 - toto okno nechte otevrene.
"%PY%" -m http.server 8765
pause
