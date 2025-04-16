@echo off
REM Attiva la virtual environment
call C:\Users\fossato\PycharmProjects\TotalCommander\.venv\Scripts\activate.bat

REM Esegui PyInstaller con le opzioni richieste
pyinstaller --noconfirm --onefile --windowed ^
  --name=TotalCommander ^
  --add-data="C:\Users\fossato\PycharmProjects\TotalCommander\gui;gui" ^
  --add-data="C:\Users\fossato\PycharmProjects\TotalCommander\logic;logic" ^
  --add-data="C:\Users\fossato\PycharmProjects\TotalCommander\.venv\Lib\site-packages\shared_lib\LorenzProtokollDll_x64.dll;shared_lib" ^
  --hidden-import=winrt.windows.foundation.collections ^
  --hidden-import=winrt ^
  --icon=justo.ico ^
  "C:\Users\fossato\PycharmProjects\TotalCommander\main.py"

IF %ERRORLEVEL% NEQ 0 (
    echo Si è verificato un errore durante la creazione dell'eseguibile.
) ELSE (
    echo EXE creato con successo.
)

REM Disattiva la virtual environment (opzionale)
REM call deactivate

echo.
echo Operazione completata. Premere un tasto per continuare...
pause
