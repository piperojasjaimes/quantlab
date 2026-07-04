@echo off
echo Starting QuantLab Dashboard...
cd /d "%~dp0.."
streamlit run agents/dashboard/app.py --server.port 8501
