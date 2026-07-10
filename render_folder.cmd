@echo off
setlocal
python "%~dp0render_all_vehicles.py" --asset-types all --cutout %*
exit /b %ERRORLEVEL%
