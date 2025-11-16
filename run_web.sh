#!/bin/bash

# Activate virtual environment and run the web app

cd "$(dirname "$0")"

if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
    source venv/bin/activate
    echo "Installing dependencies..."
    pip install -r requirements.txt
else
    source venv/bin/activate
fi

echo "Starting web app..."
echo "Open http://localhost:5001 in your browser"
python web_app.py
