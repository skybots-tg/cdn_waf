#!/bin/bash
# Test edge node download endpoint

echo "=== Testing Edge Node Download Endpoint ==="
echo ""

echo "[1] Testing locally (without auth - should fail):"
curl -v http://localhost:2000/internal/edge/download/edge_config_updater.py 2>&1 | grep -E "HTTP|detail"
echo ""

echo "[2] Testing locally (with auth):"
curl -v -H "X-Node-Id: 1" -H "X-Node-Token: NaPPEZCPCahjBaeJetPcTnsrN-GtRKadCtWEb3nFRgA" \
  http://localhost:2000/internal/edge/download/edge_config_updater.py 2>&1 | head -50
echo ""

echo "[3] Testing via public URL:"
curl -I -H "X-Node-Id: 1" -H "X-Node-Token: NaPPEZCPCahjBaeJetPcTnsrN-GtRKadCtWEb3nFRgA" \
  https://flarecloud.ru/internal/edge/download/edge_config_updater.py
echo ""

echo "[4] Checking if file exists:"
ls -lh edge_node/edge_config_updater.py
echo ""

echo "[5] Checking app routes:"
curl -s http://localhost:2000/docs | grep -o "edge_config_updater" || echo "Route not found in docs"

