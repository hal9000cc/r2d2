#!/bin/bash

# Script to start FastAPI application

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR/backend"

# Activate virtual environment
source venv/bin/activate

# Start the application
uvicorn app.main:app --reload --host 0.0.0.0 --port 8202

