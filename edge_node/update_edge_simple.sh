#!/bin/bash
# Simple script to update Edge Node code and config from control plane
# Usage: sudo bash update_edge_simple.sh

set -e

if [ "$EUID" -ne 0 ]; then 
    echo "❌ Please run as root (use sudo)"
    exit 1
fi

EDGE_DIR="/opt/cdn_waf"
CONFIG_FILE="$EDGE_DIR/config.yaml"

# Parse config
CONTROL_URL=$(grep -A1 "control_plane:" "$CONFIG_FILE" | grep "url:" | awk '{print $2}' | tr -d '"')
API_KEY=$(grep -A2 "control_plane:" "$CONFIG_FILE" | grep "api_key:" | awk '{print $2}' | tr -d '"')
NODE_ID=$(grep -A1 "edge_node:" "$CONFIG_FILE" | grep "id:" | awk '{print $2}')

echo "=== Edge Node Update Script ==="
echo "Control Plane: $CONTROL_URL"
echo "Node ID: $NODE_ID"
echo ""

# Download edge_config_updater.py
echo "[1/3] Downloading edge_config_updater.py..."
curl -f -k -H "X-Node-Id: $NODE_ID" -H "X-Node-Token: $API_KEY" \
  "$CONTROL_URL/internal/edge/download/edge_config_updater.py" \
  -o "$EDGE_DIR/edge_config_updater.py.new"

if [ $? -eq 0 ]; then
    # Backup old version
    if [ -f "$EDGE_DIR/edge_config_updater.py" ]; then
        cp "$EDGE_DIR/edge_config_updater.py" "$EDGE_DIR/edge_config_updater.py.backup"
        echo "✓ Backed up old version"
    fi
    mv "$EDGE_DIR/edge_config_updater.py.new" "$EDGE_DIR/edge_config_updater.py"
    echo "✓ Updated edge_config_updater.py"
else
    echo "❌ Failed to download code"
    exit 1
fi

# Restart agent
echo ""
echo "[2/3] Restarting Edge Agent..."
systemctl restart cdn-waf-agent
echo "✓ Agent restarted"

# Wait for config update
echo ""
echo "[3/3] Waiting for agent to apply config (10 seconds)..."
sleep 10

# Check nginx config
if nginx -t 2>&1 | grep -q "syntax is ok"; then
    echo "✓ Nginx config OK"
    systemctl reload nginx
    echo "✓ Nginx reloaded"
else
    echo "❌ Nginx config error!"
    nginx -t
    exit 1
fi

echo ""
echo "=== Update Complete ==="
echo "Current ACME config for medcard.ryabich.co:"
grep -A5 "medcard.ryabich.co" /etc/nginx/conf.d/cdn.conf | grep -A3 "acme-challenge"

