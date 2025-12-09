#!/bin/bash
# Deploy Edge Node updates to production servers
# This script updates code on edge nodes via the control plane API
# Usage: bash deploy_edge_update.sh [edge_node_ip]

set -e

CONTROL_PLANE="flarecloud.ru"
EDGE_NODES=(
    "92.246.76.113"  # Edge Node RU-MSK-01
    # Add more edge nodes here
)

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "=== Edge Node Update Deployment ==="
echo "Control Plane: $CONTROL_PLANE"
echo ""

# If argument provided, update only that node
if [ -n "$1" ]; then
    EDGE_NODES=("$1")
    echo "Single node mode: $1"
fi

update_edge_node() {
    local NODE_IP=$1
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo -e "${YELLOW}Updating Edge Node: $NODE_IP${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    # Execute update script on remote node
    ssh -o ConnectTimeout=10 root@$NODE_IP << 'EOF'
#!/bin/bash
set -e

EDGE_DIR="/opt/cdn_waf"
CONFIG_FILE="$EDGE_DIR/config.yaml"

# Check if config exists
if [ ! -f "$CONFIG_FILE" ]; then
    echo "❌ Config file not found: $CONFIG_FILE"
    exit 1
fi

# Parse config
CONTROL_URL=$(grep -A1 "control_plane:" "$CONFIG_FILE" | grep "url:" | awk '{print $2}' | tr -d '"' | tr -d "'")
API_KEY=$(grep -A2 "control_plane:" "$CONFIG_FILE" | grep "api_key:" | awk '{print $2}' | tr -d '"' | tr -d "'")
NODE_ID=$(grep -A1 "edge_node:" "$CONFIG_FILE" | grep "id:" | awk '{print $2}')

echo "📡 Control Plane: $CONTROL_URL"
echo "🆔 Node ID: $NODE_ID"
echo ""

# Download edge_config_updater.py
echo "[1/5] Downloading edge_config_updater.py from control plane..."
DOWNLOAD_URL="$CONTROL_URL/internal/edge/download/edge_config_updater.py"

curl -f -k -H "X-Node-Id: $NODE_ID" -H "X-Node-Token: $API_KEY" \
  "$DOWNLOAD_URL" -o "$EDGE_DIR/edge_config_updater.py.new"

if [ $? -eq 0 ]; then
    # Backup old version
    if [ -f "$EDGE_DIR/edge_config_updater.py" ]; then
        cp "$EDGE_DIR/edge_config_updater.py" "$EDGE_DIR/edge_config_updater.py.backup.$(date +%s)"
        echo "✅ Backed up old version"
    fi
    mv "$EDGE_DIR/edge_config_updater.py.new" "$EDGE_DIR/edge_config_updater.py"
    echo "✅ Updated edge_config_updater.py"
else
    echo "❌ Failed to download code from $DOWNLOAD_URL"
    exit 1
fi

# Install/update dependencies
echo ""
echo "[2/5] Updating Python dependencies..."
cd "$EDGE_DIR"
if [ -f "requirements.txt" ]; then
    ./venv/bin/pip install -q -r requirements.txt
    echo "✅ Dependencies updated"
else
    echo "⚠️  requirements.txt not found, skipping"
fi

# Restart agent
echo ""
echo "[3/5] Restarting Edge Agent..."
systemctl restart cdn-waf-agent
echo "✅ Agent restarted"

# Wait for config update
echo ""
echo "[4/5] Waiting for agent to fetch and apply config (15 seconds)..."
sleep 15

# Check nginx config
echo ""
echo "[5/5] Validating and reloading Nginx..."
if nginx -t 2>&1 | grep -q "syntax is ok"; then
    echo "✅ Nginx config syntax is OK"
    systemctl reload nginx
    echo "✅ Nginx reloaded"
else
    echo "❌ Nginx config error!"
    nginx -t
    exit 1
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Update complete!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Show ACME config for verification
echo ""
echo "📋 ACME Challenge Configuration:"
if grep -q "acme-challenge" /etc/nginx/conf.d/cdn.conf; then
    echo "✅ ACME challenge sections found in nginx config"
    echo ""
    echo "Sample ACME config (first 10 lines):"
    grep -A3 "acme-challenge" /etc/nginx/conf.d/cdn.conf | head -10
else
    echo "⚠️  No ACME challenge sections found in /etc/nginx/conf.d/cdn.conf"
fi

# Show agent status
echo ""
echo "📊 Edge Agent Status:"
systemctl status cdn-waf-agent --no-pager | grep -E "(Active|Main PID|Memory|CPU)"

EOF

    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✅ Successfully updated $NODE_IP${NC}"
    else
        echo -e "${RED}❌ Failed to update $NODE_IP${NC}"
        return 1
    fi
}

# Update all nodes
FAILED_NODES=()
for NODE in "${EDGE_NODES[@]}"; do
    if ! update_edge_node "$NODE"; then
        FAILED_NODES+=("$NODE")
    fi
done

# Summary
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "          DEPLOYMENT SUMMARY            "
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Total nodes: ${#EDGE_NODES[@]}"
echo "Successful: $((${#EDGE_NODES[@]} - ${#FAILED_NODES[@]}))"
echo "Failed: ${#FAILED_NODES[@]}"

if [ ${#FAILED_NODES[@]} -gt 0 ]; then
    echo ""
    echo -e "${RED}Failed nodes:${NC}"
    for NODE in "${FAILED_NODES[@]}"; do
        echo "  - $NODE"
    done
    exit 1
else
    echo ""
    echo -e "${GREEN}✅ All nodes updated successfully!${NC}"
    echo ""
    echo "🧪 Next steps:"
    echo "  1. Test ACME challenge: curl http://medcard.ryabich.co/.well-known/acme-challenge/TEST"
    echo "  2. Issue certificate via control plane UI"
    echo "  3. Monitor logs: ssh root@92.246.76.113 'journalctl -u cdn-waf-agent -f'"
fi

