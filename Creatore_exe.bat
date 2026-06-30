@echo off
setlocal enabledelayedexpansion

REM ── Configurazione percorsi ──────────────────────────────────────────────────
set PROJECT=C:\Users\fossato\PycharmProjects\TotalCommander
set VENV=%PROJECT%\.venv

REM ── Attiva la virtual environment ───────────────────────────────────────────
call %VENV%\Scripts\activate.bat

REM ── Allinea shared_lib alla versione pinnata in requirements.txt ─────────────
echo [INFO] Allineo shared_lib a requirements.txt...
pip install -U --force-reinstall --no-deps -r "%PROJECT%\requirements.txt"
pip install -r "%PROJECT%\requirements.txt"
if errorlevel 1 (
    echo [ERRORE] Installazione dipendenze fallita.
    pause & exit /b 1
)

REM ── Cattura la versione effettivamente installata della libreria ─────────────
set LIBVER=
for /f "delims=" %%v in ('python -c "import importlib.metadata as m; print(m.version('shared_lib'))" 2^>nul') do set LIBVER=%%v
if "%LIBVER%"=="" set LIBVER=unknown
echo [INFO] shared_lib version: !LIBVER!

REM ── Trova git.exe ────────────────────────────────────────────────────────────
set GIT_EXE=
where git >nul 2>&1
if %ERRORLEVEL%==0 set GIT_EXE=git

if "!GIT_EXE!"=="" (
    for %%G in (
        "C:\Program Files\Git\cmd\git.exe"
        "C:\Program Files (x86)\Git\bin\git.exe"
    ) do (
        if exist %%G if "!GIT_EXE!"=="" set GIT_EXE=%%~G
    )
)

if "!GIT_EXE!"=="" (
    echo [ERRORE] git non trovato. Installare Git for Windows.
    pause & exit /b 1
)

echo [INFO] git trovato: !GIT_EXE!

REM ── Leggi la versione tramite file temporaneo (più affidabile del for/f) ────
set TMPVER=%TEMP%\tc_git_version.tmp
"!GIT_EXE!" -C "%PROJECT%" describe --tags --dirty=-dev > "!TMPVER!" 2>nul
set /p GIT_VERSION=<"!TMPVER!"
del "!TMPVER!" >nul 2>&1

if "!GIT_VERSION!"=="" (
    echo [WARN] Nessun tag trovato nel repository.
    echo        Creare almeno un tag annotato: git tag -a v1.0.0 -m "Prima release"
    echo        Uso versione "unknown".
    set GIT_VERSION=unknown
) else (
    echo [INFO] Versione rilevata: !GIT_VERSION!
)

REM ── Suffisso _DEBUG se NON è un tag pulito vX.Y.Z ────────────────────────────
set DEBUG_SUFFIX=
echo !GIT_VERSION!| findstr /R "^v[0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*$" >nul
if errorlevel 1 set DEBUG_SUFFIX=_DEBUG
if not "!DEBUG_SUFFIX!"=="" echo [INFO] Build NON di release: suffisso !DEBUG_SUFFIX!

REM ── Salva copia di backup di version.py prima di sovrascriverlo ──────────────
copy /Y "%PROJECT%\version.py" "%PROJECT%\version.py.bak" >nul 2>&1

REM ── Scrivi version.py congelato (una sola riga, nessuna logica) ──────────────
(
echo VERSION = "!GIT_VERSION!"
echo LIB_VERSION = "!LIBVER!"
) > "%PROJECT%\version.py"
echo [INFO] version.py scritto: VERSION=!GIT_VERSION!  LIB_VERSION=!LIBVER!

REM ── Genera i metadati Windows (version_info.txt) ────────────────────────────
set "VERSION_INFO_OUT=%PROJECT%\version_info.txt"
python "%PROJECT%\tools\make_version_info.py"
if errorlevel 1 (
    echo [ERRORE] Generazione version_info.txt fallita.
    pause & exit /b 1
)

REM ── Icona: variante debug se disponibile ────────────────────────────────────
set "ICON=%PROJECT%\justo.ico"
if not "!DEBUG_SUFFIX!"=="" (
    if exist "%PROJECT%\justo_debug.ico" (
        set "ICON=%PROJECT%\justo_debug.ico"
        echo [INFO] Uso icona debug: justo_debug.ico
    ) else (
        echo [WARN] justo_debug.ico non trovato: uso justo.ico anche per la build debug.
    )
)

REM ── Esegui PyInstaller ───────────────────────────────────────────────────────
pyinstaller --noconfirm --onefile --windowed ^
  --name=TotalCommander_!GIT_VERSION!!DEBUG_SUFFIX! ^
  --version-file="%PROJECT%\version_info.txt" ^
  --add-data="%PROJECT%\gui;gui" ^
  --add-data="%PROJECT%\logic;logic" ^
  --add-data="%PROJECT%\version.py;." ^
  --add-data="%PROJECT%\core;core" ^
  --add-data="%PROJECT%\justo.ico;." ^
  --add-data="%PROJECT%\docs\guida_total_commander.html;docs" ^
  --hidden-import=winrt.windows.foundation.collections ^
  --hidden-import=winrt ^
  --icon="!ICON!" ^
  "%PROJECT%\main.py"

set BUILD_OK=%ERRORLEVEL%

REM ── Rimuovi version_info.txt generato ────────────────────────────────────────
del "%PROJECT%\version_info.txt" >nul 2>&1

REM ── Ripristina version.py dal backup ─────────────────────────────────────────
if exist "%PROJECT%\version.py.bak" (
    copy /Y "%PROJECT%\version.py.bak" "%PROJECT%\version.py" >nul
    del "%PROJECT%\version.py.bak" >nul
    echo [INFO] version.py ripristinato dal backup.
) else (
    echo [WARN] Backup version.py non trovato, file lasciato congelato.
)

IF !BUILD_OK! NEQ 0 (
    echo.
    echo [ERRORE] Errore durante la creazione dell'eseguibile.
) ELSE (
    echo.
    echo [OK] EXE creato con successo: TotalCommander !GIT_VERSION!
)

echo.
echo Operazione completata. Premere un tasto per continuare...
pause
endlocal