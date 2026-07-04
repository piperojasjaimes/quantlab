@echo off
title QuantLab - Full System
echo ==========================================
echo   QuantLab - Full System
echo   Loop + Dashboard
echo   Press Ctrl+C to stop
echo ==========================================
cd /d "%~dp0"
start "QuantLab Dashboard" cmd /c "streamlit run agents/dashboard/app.py --server.port 8501 --server.headless true"
timeout /t 3 /nobreak >nul
python -m scripts.start --mode loop
pause
