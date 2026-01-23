#!/bin/bash

# Wrapper script to run the analysis via Cron
# Usage: Add to crontab to run weekly

# 1. Navigate to the project root (one level up from this script)
cd "$(dirname "$0")/.."

# 2. Activate Virtual Environment (Adjust 'venv' to your actual venv folder name)
if [ -d "venv" ]; then
    source venv/bin/activate
elif [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# 3. Execute the Python analysis script
# Redirect stdout/stderr to a log file for debugging
python scripts/analyze_json_logs.py >> live/logs/cron_analysis.log 2>&1