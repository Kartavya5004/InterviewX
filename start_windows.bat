
@echo off
cd /d "%~dp0"
echo.
echo =================================================
echo    INTERVIEWX 3.0 - VOICE STUDIO + CAREER OS
echo =================================================
echo.
where py >nul 2>nul
if %errorlevel%==0 (set "PYTHON=py") else (set "PYTHON=python")
if not exist .venv\Scripts\python.exe (
  echo Creating Python virtual environment...
  %PYTHON% -m venv .venv
  if errorlevel 1 goto failed
)
echo Installing required packages...
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto failed
if not exist .env copy .env.example .env >nul
echo.
echo OPEN IN CHROME OR EDGE: http://127.0.0.1:8001/login  then /career
echo Port 8001 intentionally differs from the older InterviewX version.
echo.
.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8001
pause
exit /b 0
:failed
echo Setup failed. Run these in VS Code from the correct project folder:
echo py -m venv --clear .venv
echo .venv\Scripts\python.exe -m ensurepip --upgrade
echo .venv\Scripts\python.exe -m pip install -r requirements.txt
pause
exit /b 1
