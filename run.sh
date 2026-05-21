#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════
# NOCTYRA360™ — Connect Now USA LLC
# Production Server — Version 13.0 — Bridge v8
# ═══════════════════════════════════════════════════════

clear
echo ""
echo "  ╔══════════════════════════════════════════════╗"
echo "  ║     NOCTYRA360™ — Connect Now USA LLC        ║"
echo "  ║     Revenue Compliance & Assurance           ║"
echo "  ║     Version 13.0 · Bridge v8 · SHA-256       ║"
echo "  ╚══════════════════════════════════════════════╝"
echo ""

# ── Install all dependencies ────────────────────────────
echo "  ⏳ Installing dependencies..."
pip3 install fastapi uvicorn python-multipart \
     reportlab openpyxl pandas \
     "python-jose[cryptography]" passlib \
     sqlalchemy psycopg2-binary \
     paramiko watchdog aiosmtplib \
     --quiet --break-system-packages 2>/dev/null \
|| pip3 install fastapi uvicorn python-multipart \
     reportlab openpyxl pandas \
     python-jose passlib \
     sqlalchemy psycopg2-binary \
     paramiko watchdog aiosmtplib \
     --quiet 2>/dev/null || true

echo "  ✅ Dependencies ready"
echo ""

# ── Detect all available IPs ────────────────────────────
WSL_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")
ALL_IPS=$(hostname -I 2>/dev/null | tr ' ' '\n' | grep -v '^$' || echo "localhost")
PORT=8000

# ── Display access URLs ─────────────────────────────────
echo "  ╔══════════════════════════════════════════════╗"
echo "  ║  ACCESS NOCTYRA360™ FROM ANYWHERE            ║"
echo "  ╠══════════════════════════════════════════════╣"
echo "  ║                                              ║"
echo "  ║  LOCAL (same computer) :                     ║"
echo "  ║  → http://localhost:${PORT}                  ║"
echo "  ║  → http://${WSL_IP}:${PORT}          ║"
echo "  ║                                              ║"
echo "  ║  SAME NETWORK (anyone on same WiFi) :        ║"
echo "  ║  → http://${WSL_IP}:${PORT}          ║"
echo "  ║                                              ║"
echo "  ║  LOGIN PAGE :                                ║"
echo "  ║  → http://${WSL_IP}:${PORT}/login    ║"
echo "  ║                                              ║"
echo "  ║  UPLOAD TOOL :                               ║"
echo "  ║  → http://${WSL_IP}:${PORT}/upload-tool ║"
echo "  ║                                              ║"
echo "  ║  API STATUS :                                ║"
echo "  ║  → http://${WSL_IP}:${PORT}/api/health ║"
echo "  ║                                              ║"
echo "  ╠══════════════════════════════════════════════╣"
echo "  ║  DEFAULT LOGINS (change before production) : ║"
echo "  ║  admin     → N360Admin2026!                  ║"
echo "  ║  dgi       → DGI_N360_2026!                  ║"
echo "  ║  artec     → ARTEC_N360_2026!                ║"
echo "  ║  ministere → MIN_N360_2026!                  ║"
echo "  ║  auditeur  → AUDIT_N360_2026!                ║"
echo "  ╠══════════════════════════════════════════════╣"
echo "  ║  SFTP (operators) : port 2222                ║"
echo "  ║  sftp -P 2222 telma@${WSL_IP}       ║"
echo "  ╚══════════════════════════════════════════════╝"
echo ""
echo "  Press Ctrl+C to stop the server"
echo ""

# ── Check if port is already in use ─────────────────────
if lsof -Pi :${PORT} -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo "  ⚠️  Port ${PORT} already in use — killing old process..."
    kill $(lsof -Pi :${PORT} -sTCP:LISTEN -t) 2>/dev/null || true
    sleep 2
fi

# ── Start server ─────────────────────────────────────────
python3 server.py
