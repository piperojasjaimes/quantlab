@echo off
title QuantLab - Dashboard
echo ==========================================
echo   QuantLab - Dashboard
echo   Opening at http://localhost:8501
echo ==========================================
cd /d "%~dp0"
streamlit run agents/dashboard/app.py --server.port 8501 --server.headless true
pause
