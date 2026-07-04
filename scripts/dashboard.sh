#!/bin/bash
echo "Starting QuantLab Dashboard..."
cd "$(dirname "$0")/.."
streamlit run agents/dashboard/app.py --server.port 8501
