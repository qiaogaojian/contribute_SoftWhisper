@echo off
setlocal enabledelayedexpansion

:: Check Python packages one by one
set MISSING_PACKAGES=

:: Check psutil
python -c "import psutil" 2>nul
if %errorlevel% neq 0 (
  set MISSING_PACKAGES=!MISSING_PACKAGES! psutil
)

:: Check pydub
python -c "import pydub" 2>nul
if %errorlevel% neq 0 (
  set MISSING_PACKAGES=!MISSING_PACKAGES! pydub
)

:: Check vlc
python -c "import vlc" 2>nul
if %errorlevel% neq 0 (
  set MISSING_PACKAGES=!MISSING_PACKAGES! python-vlc
)

:: Check PIL (pillow)
python -c "from PIL import Image" 2>nul
if %errorlevel% neq 0 (
  set MISSING_PACKAGES=!MISSING_PACKAGES! pillow
)

:: Check numpy
python -c "import numpy" 2>nul
if %errorlevel% neq 0 (
  set MISSING_PACKAGES=!MISSING_PACKAGES! numpy
)

:: Check requests
python -c "import requests" 2>nul
if %errorlevel% neq 0 (
  set MISSING_PACKAGES=!MISSING_PACKAGES! requests
)

:: If missing packages, prompt to install
if not "!MISSING_PACKAGES!"=="" (
  echo The following packages are required but not installed:!MISSING_PACKAGES!
  echo.
  set /p INSTALL_CHOICE="Do you want to install these packages now? (Y/N): "
  if /i "!INSTALL_CHOICE!"=="Y" (
    for %%p in (!MISSING_PACKAGES!) do (
      echo Installing %%p...
      pip install %%p
    )
    echo Package installation complete.
  ) else (
    echo Installation cancelled. SoftWhisper may not work correctly.
    set /p CONTINUE_CHOICE="Continue anyway? (Y/N): "
    if /i not "!CONTINUE_CHOICE!"=="Y" (
      echo Launch cancelled.
      exit /b
    )
  )
)

:: Launch SoftWhisper in hidden mode
echo Launching SoftWhisper...
echo Set WshShell = CreateObject("WScript.Shell") > %temp%\temp_script.vbs
echo WshShell.Run "python SoftWhisper.py", 0, False >> %temp%\temp_script.vbs
wscript //nologo %temp%\temp_script.vbs
del %temp%\temp_script.vbs

echo SoftWhisper is running in the background.
exit /b