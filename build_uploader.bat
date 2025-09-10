@echo off
REM Build the uploader executable (Simplified)
echo Building the uploader executable...
python -m PyInstaller ^
--onefile ^
--noconsole ^
--name uploader ^
--paths "." ^
--hidden-import=pydantic ^
--hidden-import=customtkinter ^
--hidden-import=tkinterdnd2 ^
--hidden-import=python_dotenv ^
--hidden-import=git ^
--hidden-import=requests ^
--hidden-import=uploader.providers.catbox ^
--hidden-import=uploader.providers.github_git ^
--hidden-import=uploader.providers.github_release ^
--collect-data customtkinter ^
--collect-data tkinterdnd2 ^
--add-data "uploader/locale;uploader/locale" ^
run_uploader_main.py

pause