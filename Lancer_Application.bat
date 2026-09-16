@echo off
title Famelomana NY HAVANA - Gestion
echo Ambelona ny Server Python...
cd /d "%~dp0"

:: Sokafy ao amin'ny Chrome/Edge avy hatrany ny pejy rehefa afaka 2 segondra
start http://127.0.0.1:5000/

:: Alefaso ny Python app.py
python app.py
pause