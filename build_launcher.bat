@echo off
REM Build the launcher executable (Simplified)
echo Building the launcher executable...
python -m PyInstaller ^
--onefile ^
--noconsole ^
--name launcher ^
--paths "." ^
--hidden-import=pydantic ^
--hidden-import=customtkinter ^
--collect-data customtkinter ^
--collect-data tkinter ^
--hidden-import=requests ^
--hidden-import=tkinterdnd2 ^
run_launcher_main.py

pause