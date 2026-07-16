@echo off
rem ── Nahled webu SKELETA ─────────────────────────────────────────
rem Dvojklik spusti lokalni server a otevre web v prohlizeci.
rem Okno nechte bezet; zavrenim okna se nahled vypne.
cd /d "%~dp0"
start "" http://localhost:8765
where py >nul 2>nul && (py -m http.server 8765 & goto :eof)
where python >nul 2>nul && (python -m http.server 8765 & goto :eof)
echo Chybi Python - nainstalujte z https://www.python.org/downloads/ (staci vychozi instalace).
pause
