#!/bin/bash

# Activate virtual environment and run the web app

# Ensure we are running from the project root
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR/.."

# Check if venv exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
    source venv/bin/activate
    echo "Installing dependencies..."
    pip install -r requirements.txt
else
    source venv/bin/activate
fi

echo "Applying migrations..."
python manage.py migrate --noinput

echo "Starting Django dev server..."
echo "Open http://localhost:8000 in your browser"
python manage.py runserver 0.0.0.0:8000
