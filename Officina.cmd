@echo off
rem  L'Officina, con un doppio clic.
rem
rem  Questo file esiste per una ragione sola: aprire le proprie foto non deve
rem  voler dire aprire un terminale e scrivere un comando. Il collegamento sul
rem  desktop punta qui dentro, e da qui in poi il programma fa da se'.
rem
rem  La finestra nera resta aperta e ridotta a icona mentre l'Officina gira.
rem  Non e' una dimenticanza: se l'archivio e' dentro un forziere, la password
rem  si scrive li' (regola 340). Chiudendola, il programma si ferma.
rem
rem  Per farsi l'icona sul desktop:  python -m officina scorciatoia

setlocal EnableExtensions
cd /d "%~dp0"
title Officina

set "PY="
py -3 -c "" >nul 2>nul && set "PY=py -3"
if not defined PY (
    python -c "" >nul 2>nul && set "PY=python"
)

if not defined PY (
    echo.
    echo   Non trovo Python su questo computer, e senza non posso partire.
    echo.
    echo   Si scarica da python.org. Durante l'installazione va spuntata la
    echo   casella "Add Python to PATH", altrimenti Windows non lo trova
    echo   nemmeno dopo averlo installato.
    echo.
    pause
    exit /b 1
)

%PY% -m officina avvia %*
set ESITO=%ERRORLEVEL%

if not "%ESITO%"=="0" (
    echo.
    echo   L'Officina si e' fermata. La finestra resta aperta apposta, cosi'
    echo   si legge quello che c'e' scritto qui sopra.
    echo.
    pause
)
exit /b %ESITO%
