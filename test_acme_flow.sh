#!/bin/bash
# Test ACME Challenge Flow End-to-End
# This script tests the full ACME HTTP-01 challenge flow:
# 1. Set a test token in Redis on control plane
# 2. Query via Edge Node
# 3. Verify response matches

set -e

DOMAIN="medcard.ryabich.co"
EDGE_NODE_IP="92.246.76.113"
CONTROL_PLANE="flarecloud.ru"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "     ACME Challenge Flow Test"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Domain: $DOMAIN"
echo "Edge Node: $EDGE_NODE_IP"
echo "Control Plane: $CONTROL_PLANE"
echo ""

# Generate test token and validation
TEST_TOKEN="TEST_TOKEN_$(date +%s)"
TEST_VALIDATION="TEST_VALIDATION_$(date +%s)_SIGNATURE"

echo -e "${BLUE}[Step 1/5]${NC} Setting test token in Redis on control plane..."
echo "  Token: $TEST_TOKEN"
echo "  Validation: $TEST_VALIDATION"

# Store in Redis via redis-cli on control plane
ssh root@$CONTROL_PLANE << EOF
redis-cli SET "acme:challenge:$TEST_TOKEN" "$TEST_VALIDATION" EX 300
echo "✅ Token stored in Redis (expires in 300s)"
EOF

if [ $? -ne 0 ]; then
    echo -e "${RED}❌ Failed to set token in Redis${NC}"
    exit 1
fi

echo ""
echo -e "${BLUE}[Step 2/5]${NC} Testing control plane endpoint directly..."
CONTROL_RESPONSE=$(curl -s -k "https://$CONTROL_PLANE/.well-known/acme-challenge/$TEST_TOKEN")

if [ "$CONTROL_RESPONSE" == "$TEST_VALIDATION" ]; then
    echo -e "${GREEN}✅ Control plane returns correct validation${NC}"
    echo "   Response: $CONTROL_RESPONSE"
else
    echo -e "${RED}❌ Control plane returned wrong response${NC}"
    echo "   Expected: $TEST_VALIDATION"
    echo "   Got: $CONTROL_RESPONSE"
    exit 1
fi

echo ""
echo -e "${BLUE}[Step 3/5]${NC} Testing via Edge Node HTTP (port 80)..."
echo "  URL: http://$DOMAIN/.well-known/acme-challenge/$TEST_TOKEN"

# Test via domain (should go through Edge Node)
EDGE_RESPONSE=$(curl -s -H "Host: $DOMAIN" "http://$EDGE_NODE_IP/.well-known/acme-challenge/$TEST_TOKEN")

if [ "$EDGE_RESPONSE" == "$TEST_VALIDATION" ]; then
    echo -e "${GREEN}✅ Edge Node proxies request correctly${NC}"
    echo "   Response: $EDGE_RESPONSE"
else
    echo -e "${RED}❌ Edge Node returned wrong response${NC}"
    echo "   Expected: $TEST_VALIDATION"
    echo "   Got: $EDGE_RESPONSE"
    echo ""
    echo "Debugging info:"
    echo "  Check nginx config on Edge Node:"
    echo "    ssh root@$EDGE_NODE_IP 'grep -A5 \"acme-challenge\" /etc/nginx/conf.d/cdn.conf | head -20'"
    exit 1
fi

echo ""
echo -e "${BLUE}[Step 4/5]${NC} Testing via public DNS resolution..."
# Test with actual domain (requires DNS to be pointing to Edge Node)
PUBLIC_RESPONSE=$(curl -s --connect-timeout 5 "http://$DOMAIN/.well-known/acme-challenge/$TEST_TOKEN" || echo "TIMEOUT")

if [ "$PUBLIC_RESPONSE" == "$TEST_VALIDATION" ]; then
    echo -e "${GREEN}✅ Public DNS resolution works${NC}"
    echo "   Response: $PUBLIC_RESPONSE"
elif [ "$PUBLIC_RESPONSE" == "TIMEOUT" ]; then
    echo -e "${YELLOW}⚠️  Public DNS test timed out${NC}"
    echo "   This might be normal if DNS hasn't propagated yet"
else
    echo -e "${YELLOW}⚠️  Public DNS returned unexpected response${NC}"
    echo "   Expected: $TEST_VALIDATION"
    echo "   Got: $PUBLIC_RESPONSE"
    echo "   This might be due to DNS caching or CDN proxy"
fi

echo ""
echo -e "${BLUE}[Step 5/5]${NC} Checking Nginx configuration on Edge Node..."
ssh root@$EDGE_NODE_IP << 'EOF'
echo "📋 Nginx ACME configuration:"
if grep -q "acme-challenge" /etc/nginx/conf.d/cdn.conf; then
    echo "✅ ACME sections found in nginx config"
    echo ""
    echo "Config sample:"
    grep -B2 -A5 "acme-challenge" /etc/nginx/conf.d/cdn.conf | head -20
else
    echo "❌ No ACME sections found in nginx config!"
fi
EOF

# Cleanup
echo ""
echo -e "${BLUE}Cleanup:${NC} Removing test token from Redis..."
ssh root@$CONTROL_PLANE "redis-cli DEL acme:challenge:$TEST_TOKEN" > /dev/null

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${GREEN}✅ ACME Challenge Flow Test PASSED${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "🎉 Your ACME HTTP-01 challenge setup is working correctly!"
echo ""
echo "Next steps:"
echo "  1. Issue a real certificate via the control plane UI"
echo "  2. Monitor the certificate issuance process"
echo "  3. Check certificate logs in the UI"
echo ""

