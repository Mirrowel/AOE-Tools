@echo off
REM Build the launcher executable (Simplified)
echo Building the launcher executable...
python -m PyInstaller ^
--onefile ^
--icon "icon.ico" ^
--noconsole ^
--name launcher ^
--paths "." ^
--hidden-import=pydantic ^
--hidden-import=customtkinter ^
--collect-data customtkinter ^
--collect-data tkinter ^
--hidden-import=requests ^
--hidden-import=tkinterdnd2 ^
--add-data "launcher/locale;launcher/locale" ^
--add-data "launcher/assets;launcher/assets" ^
run_launcher_main.py

pause