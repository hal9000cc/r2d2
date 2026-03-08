#!/bin/bash

# Script to start the R2D2 application via supervisor.
# The supervisor manages uvicorn (FastAPI) and live trading processes.

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR/backend"

# Activate virtual environment
source venv/bin/activate

# Start the supervisor (which launches uvicorn internally)
python -m app.main
