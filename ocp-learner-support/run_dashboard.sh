#!/bin/bash
# Runs the Streamlit dashboard with the project root on PYTHONPATH so
# `from app.config import settings` (and other `app.*` imports) resolve.
# Streamlit only puts the target script's own directory on sys.path,
# not the project root, so this is required for `app` to be importable.
set -e
cd "$(dirname "$0")"
PYTHONPATH="$(pwd)" streamlit run app/dashboard.py "$@"
