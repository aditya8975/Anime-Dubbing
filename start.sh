#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

echo ""
echo " =========================================="
echo "  AniDub Studio v4.0 — Starting..."
echo " =========================================="
echo ""

# Check Python
if ! command -v python3 &>/dev/null; then
    echo " [ERROR] python3 not found."
    exit 1
fi

python3 backend/check.py || {
    echo ""
    echo " [ERROR] System check failed. Run: pip3 install -r backend/requirements.txt"
    exit 1
}

echo ""
echo " Backend on http://localhost:5050"
echo " Open: frontend/index.html"
echo ""

# Try opening browser
if command -v xdg-open &>/dev/null; then
    xdg-open "frontend/index.html" &
elif command -v open &>/dev/null; then
    open "frontend/index.html" &
fi

python3 backend/app.py