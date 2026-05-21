#!/bin/bash
# ═══════════════════════════════════════════════════════
# NOCTYRA360™ — Share Platform Worldwide via ngrok
# Anyone anywhere can access with a public URL
# ═══════════════════════════════════════════════════════

echo ""
echo "  NOCTYRA360™ — Internet Access Setup"
echo ""

# Install ngrok if not present
if ! command -v ngrok &>/dev/null; then
    echo "  Installing ngrok..."
    curl -s https://ngrok-agent.s3.amazonaws.com/ngrok.asc | \
        sudo tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null 2>&1
    echo "deb https://ngrok-agent.s3.amazonaws.com buster main" | \
        sudo tee /etc/apt/sources.list.d/ngrok.list >/dev/null 2>&1
    sudo apt-get update -q && sudo apt-get install -y -q ngrok 2>/dev/null || \
    # Alternative: download directly
    (wget -q https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64.tgz \
        -O /tmp/ngrok.tgz && \
     tar xf /tmp/ngrok.tgz -C /usr/local/bin/ && \
     echo "✅ ngrok installed")
fi

echo ""
echo "  ⚠️  IMPORTANT:"
echo "  1. Create free account at https://ngrok.com"
echo "  2. Copy your auth token from dashboard"
echo "  3. Run: ngrok config add-authtoken YOUR-TOKEN"
echo ""
read -p "  Have you set your ngrok token? (yes/no): " READY

if [ "$READY" = "yes" ] || [ "$READY" = "y" ]; then
    echo ""
    echo "  ✅ Starting ngrok tunnel on port 8000..."
    echo "  ✅ NOCTYRA360™ will be accessible worldwide"
    echo "  ✅ Share the https://xxxx.ngrok.io URL"
    echo ""
    ngrok http 8000 --log=stdout 2>/dev/null &
    sleep 3
    # Get the public URL
    PUBLIC_URL=$(curl -s http://localhost:4040/api/tunnels 2>/dev/null | \
        python3 -c "import sys,json; d=json.load(sys.stdin); \
        print(d['tunnels'][0]['public_url'])" 2>/dev/null)
    if [ -n "$PUBLIC_URL" ]; then
        echo "  ╔══════════════════════════════════════════════╗"
        echo "  ║  NOCTYRA360™ PUBLIC URL :                    ║"
        echo "  ║  ${PUBLIC_URL}/login"
        echo "  ║                                              ║"
        echo "  ║  Share this URL with anyone worldwide.       ║"
        echo "  ║  Valid until you stop ngrok.                 ║"
        echo "  ╚══════════════════════════════════════════════╝"
    else
        echo "  ✅ ngrok running — check http://localhost:4040"
        echo "  → Your public URL is shown in the ngrok dashboard"
    fi
else
    echo "  Setup ngrok first:"
    echo "  1. Go to https://ngrok.com — create free account"
    echo "  2. Copy auth token"
    echo "  3. Run: ngrok config add-authtoken YOUR-TOKEN"
    echo "  4. Run this script again"
fi
