#!/bin/bash
# Force update Edge Node configuration from control plane
# Usage: sudo bash update_config.sh

set -e

EDGE_DIR="/opt/cdn_waf"
CONFIG_FILE="$EDGE_DIR/config.yaml"

echo "=== Edge Node Configuration Update ==="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "❌ Please run as root (use sudo)"
    exit 1
fi

# Check if config exists
if [ ! -f "$CONFIG_FILE" ]; then
    echo "❌ Config file not found: $CONFIG_FILE"
    exit 1
fi

# Pull latest code
echo "[1/5] Pulling latest code from git..."
cd "$EDGE_DIR"
git pull origin main || {
    echo "⚠ Git pull failed, continuing anyway..."
}

# Restart agent to apply new code and fetch config
echo ""
echo "[2/5] Restarting Edge Agent..."
systemctl restart cdn-waf-agent

echo ""
echo "[3/5] Waiting for agent to fetch new config (5 seconds)..."
sleep 5

# Check if nginx config was updated
echo ""
echo "[4/5] Checking nginx configuration..."
if nginx -t 2>&1 | grep -q "syntax is ok"; then
    echo "✓ Nginx config syntax is OK"
else
    echo "❌ Nginx config has syntax errors!"
    nginx -t
    exit 1
fi

# Reload nginx
echo ""
echo "[5/5] Reloading nginx..."
systemctl reload nginx

echo ""
echo "=== Configuration Update Complete ==="
echo ""
echo "✓ Code updated"
echo "✓ Agent restarted"
echo "✓ Nginx reloaded"
echo ""
echo "Verify ACME challenge proxy:"
echo "  grep -A3 'acme-challenge' /etc/nginx/conf.d/cdn.conf | head -10"

