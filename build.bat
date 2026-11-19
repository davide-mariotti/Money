@echo off
rem Builds dist\Money.exe (one file, about 45 MB: Python, the PDF readers and the window's page in ui\) and
rem dist\Money-portable.zip (the same exe plus Money.ini: data next to the exe). Needs .venv: Money.bat creates it.
cd /d "%~dp0"
.venv\Scripts\python -m pip install -q -r requirements.txt pyinstaller==6.22.3 || goto :err
.venv\Scripts\python test_money.py || goto :err
echo Building Money.exe...
.venv\Scripts\python -m PyInstaller --noconfirm --clean --onefile --windowed --name Money --icon "%~dp0assets\icon.ico" ^
  --add-data "%~dp0ui;ui" --exclude-module streamlit --exclude-module plotly --exclude-module pandas --exclude-module numpy ^
  --exclude-module pyarrow --distpath dist --workpath build --specpath build desktop.py >build.log 2>&1 || goto :err
echo Packing Money-portable.zip (the same exe plus Money.ini)...
powershell -NoProfile -Command "$d = Join-Path $env:TEMP 'money-portable'; Remove-Item $d -Recurse -Force -ErrorAction SilentlyContinue; New-Item -ItemType Directory $d | Out-Null; Copy-Item dist\Money.exe $d; Set-Content (Join-Path $d 'Money.ini') '; While this file sits next to Money.exe, the data stays in the data folder beside it.'; Compress-Archive (Join-Path $d '*') dist\Money-portable.zip -Force; Remove-Item $d -Recurse -Force" || goto :err
echo Done: dist\Money.exe and dist\Money-portable.zip
exit /b
:err
echo Build failed (see build.log).
exit /b 1
