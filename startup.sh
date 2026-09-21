#!/bin/bash
# App Service Linux "Startup Command" for this app. Streamlit is not a WSGI
# app, so Oryx's default gunicorn autodetection won't work here -- this
# script must be configured explicitly as the Startup Command.
set -euo pipefail

python -m streamlit run app/main.py \
    --server.port 8000 \
    --server.address 0.0.0.0 \
    --server.headless true \
    --browser.gatherUsageStats false
