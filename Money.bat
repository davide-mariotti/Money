@echo off
cd /d "%~dp0"
if not exist .venv (
  python -m venv .venv || goto :err
  .venv\Scripts\python -m pip install -q -r requirements.txt || goto :err
)
rem ponytail: fixed 3s wait for the server; poll /_stcore/health if it ever opens too early
start "" /b cmd /c "timeout /t 3 /nobreak >nul & start http://localhost:8599"
.venv\Scripts\python -m streamlit run app.py
exit /b
:err
echo Serve Python 3.12+ installato. & pause
