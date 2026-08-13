@echo off
rem Double-click launcher for Windows.
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 goto runpy
where python >nul 2>nul
if %errorlevel%==0 goto runpython
goto nopython

:runpy
py -3 "%~dp0launch.py" %*
goto done

:runpython
python "%~dp0launch.py" %*
goto done

:nopython
echo.
echo   Python 3.10 or newer is required to run watermarks-remover.
echo   Download it from https://www.python.org/downloads/
echo   During setup, tick "Add python.exe to PATH".
echo.
pause
exit /b 1

:done
if errorlevel 1 pause
endlocal
