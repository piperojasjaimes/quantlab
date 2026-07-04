@echo off
title QuantLab - Auto-Optimization Loop
echo ==========================================
echo   QuantLab - Auto-Optimization Loop
echo   Press Ctrl+C to stop
echo ==========================================
cd /d "%~dp0"
python -m scripts.start --mode loop
pause
