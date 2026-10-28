@echo off
rem Project Pyrrhus (Killzone 2 PC port), portable zip: first run (from Project Helghast installer/run.cmd).
rem Offers "Use my RPCS3 install" (the game files are found in your RPCS3 folder), else asks for your own dump,
rem the 1.29 update and the decrypted EBOOT, checks them, then lifts and compiles the port
rem here with one progress bar. Saves and settings stay in this folder (portable). The log is written next to this
rem file (Project-Pyrrhus-firstrun.log). Nothing is downloaded; the optional version check asks first.
setlocal
cd /d "%~dp0"
set "PY=%~dp0toolchain\python\python.exe"
if not exist "%PY%" (
  echo The bundled Python is missing: %PY%
  echo Unpack the whole zip again, keeping its folders.
  pause
  exit /b 2
)
"%PY%" "%~dp0kz2-setup\release\firstrun.py" --interactive --portable --root "%~dp0." --log-dir "%~dp0." --log-name Project-Pyrrhus-firstrun.log %*
set "RC=%ERRORLEVEL%"
echo.
pause
exit /b %RC%
