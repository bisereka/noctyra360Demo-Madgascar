#!/bin/bash
# NOCTYRA360™ — Run locally for demo (no server needed)
# Works on any laptop with Python 3.9+

echo "Starting NOCTYRA360™ Production Backend (local demo mode)..."
cd "$(dirname "$0")/.."

# Create virtual env if not exists
if [ ! -d "venv" ]; then
    echo "Setting up Python environment (first time only)..."
    python3 -m venv venv
    source venv/bin/activate
    pip install --quiet fastapi uvicorn[standard] pandas numpy chardet aiofiles python-multipart reportlab openpyxl
else
    source venv/bin/activate
fi

echo ""
echo "=================================================="
echo "  NOCTYRA360™ running at http://localhost:8000"
echo "  API docs:  http://localhost:8000/docs"
echo "  Press Ctrl+C to stop"
echo "=================================================="
echo ""

uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
