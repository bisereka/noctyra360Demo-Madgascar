#!/usr/bin/env python3
"""
NOCTYRA360™ — Single-Command Launcher
Starts the complete integrated production system.
Run: python3 start.py

Opens browser automatically at http://localhost:8000
"""

import os
import sys
import time
import signal
import subprocess
import webbrowser
from pathlib import Path

BASE_DIR = Path(__file__).parent
PORT     = int(os.environ.get("PORT", 8000))

print("""
╔══════════════════════════════════════════════════════════════╗
║         NOCTYRA360™ — PRODUCTION SYSTEM                      ║
║         Connect Now USA LLC & IntegraTouch                    ║
╚══════════════════════════════════════════════════════════════╝
""")

# Check Python dependencies
def check_deps():
    missing = []
    for pkg in ["fastapi","uvicorn","pandas","chardet","openpyxl"]:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        print(f"  Installing missing packages: {', '.join(missing)}")
        subprocess.run([sys.executable,"-m","pip","install","--quiet",
                        "--break-system-packages"] + missing, check=True)

print("  Checking dependencies...")
check_deps()
print("  ✅ All dependencies ready")

# Create required directories
for d in ["uploads","reports_out","config","logs"]:
    (BASE_DIR / d).mkdir(exist_ok=True)

# Verify frontend exists
frontend = BASE_DIR / "frontend" / "index.html"
if not frontend.exists():
    print(f"  ❌ Frontend not found at {frontend}")
    print("     Please place NOCTYRA360_PRODUCTION_INTEGRATED.html as frontend/index.html")
    sys.exit(1)
print(f"  ✅ Frontend: {frontend.stat().st_size//1024}KB")

# Start the server
print(f"\n  Starting NOCTYRA360™ on http://localhost:{PORT}")
print(f"  Press Ctrl+C to stop\n")

env = os.environ.copy()
env["PYTHONPATH"] = str(BASE_DIR)

proc = subprocess.Popen(
    [sys.executable, "-m", "uvicorn",
     "api.main:app",
     "--host",    "0.0.0.0",
     "--port",    str(PORT),
     "--workers", "1",
     "--log-level","warning"],
    cwd=str(BASE_DIR),
    env=env,
)

# Open browser after short delay
time.sleep(2)
try:
    webbrowser.open(f"http://localhost:{PORT}")
    print(f"  🌐 Browser opened at http://localhost:{PORT}")
except Exception:
    print(f"  Open your browser at: http://localhost:{PORT}")

print("""
  ╔══════════════════════════════════════════════════════╗
  ║  NOCTYRA360™ PRODUCTION is RUNNING                   ║
  ║                                                      ║
  ║  Dashboard:  http://localhost:8000                   ║
  ║  API:        http://localhost:8000/api/health        ║
  ║                                                      ║
  ║  In the dashboard:                                   ║
  ║  • Upload any CDR file → processed server-side       ║
  ║  • Any file size — no browser limits                 ║
  ║  • Results certified with SHA-256                    ║
  ║  • Download PDF + Excel reports                      ║
  ║                                                      ║
  ║  Press Ctrl+C to stop                                ║
  ╚══════════════════════════════════════════════════════╝
""")

def shutdown(sig, frame):
    print("\n  Shutting down NOCTYRA360™...")
    proc.terminate()
    sys.exit(0)

signal.signal(signal.SIGINT,  shutdown)
signal.signal(signal.SIGTERM, shutdown)

proc.wait()
