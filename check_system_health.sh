#!/bin/bash
# System Health Check for CDN WAF Infrastructure
# Checks Control Plane and all Edge Nodes

set -e

CONTROL_PLANE="flarecloud.ru"
EDGE_NODES=(
    "92.246.76.113"
)

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "     CDN WAF System Health Check"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

check_control_plane() {
    echo -e "${BLUE}═══ Control Plane: $CONTROL_PLANE ═══${NC}"
    echo ""
    
    # Check services
    echo "📊 Services Status:"
    ssh root@$CONTROL_PLANE << 'EOF'
services=("cdn_app.service" "cdn_celery" "cdn_celery_beat.service" "redis" "postgresql")
for service in "${services[@]}"; do
    if systemctl is-active --quiet $service; then
        echo "  ✅ $service: running"
    else
        echo "  ❌ $service: not running"
    fi
done
EOF

    echo ""
    echo "🌐 API Endpoint:"
    API_STATUS=$(curl -s -k -o /dev/null -w "%{http_code}" "https://$CONTROL_PLANE/health" || echo "000")
    if [ "$API_STATUS" == "200" ]; then
        echo -e "  ${GREEN}✅ API responding (HTTP $API_STATUS)${NC}"
    else
        echo -e "  ${RED}❌ API not responding (HTTP $API_STATUS)${NC}"
    fi
    
    echo ""
    echo "🔑 ACME Challenge Endpoint:"
    ACME_STATUS=$(curl -s -k -o /dev/null -w "%{http_code}" "https://$CONTROL_PLANE/.well-known/acme-challenge/TEST" || echo "000")
    if [ "$ACME_STATUS" == "404" ]; then
        echo -e "  ${GREEN}✅ ACME endpoint responding (HTTP $ACME_STATUS - expected)${NC}"
    else
        echo -e "  ${YELLOW}⚠️  ACME endpoint (HTTP $ACME_STATUS)${NC}"
    fi
    
    echo ""
    echo "💾 Redis Status:"
    ssh root@$CONTROL_PLANE << 'EOF'
redis_info=$(redis-cli INFO server 2>&1 | grep "redis_version" || echo "")
if [ -n "$redis_info" ]; then
    echo "  ✅ Redis is running"
    redis_keys=$(redis-cli DBSIZE | awk '{print $2}')
    echo "  📊 Keys in database: $redis_keys"
    acme_keys=$(redis-cli KEYS "acme:challenge:*" | wc -l)
    echo "  🔐 ACME challenge keys: $acme_keys"
else
    echo "  ❌ Redis is not responding"
fi
EOF

    echo ""
    echo "📂 Disk Space:"
    ssh root@$CONTROL_PLANE "df -h / | tail -1 | awk '{print \"  💿 Root: \" \$3 \" used / \" \$2 \" total (\" \$5 \" used)\"}'"
    
    echo ""
}

check_edge_node() {
    local NODE_IP=$1
    echo -e "${BLUE}═══ Edge Node: $NODE_IP ═══${NC}"
    echo ""
    
    # Ping test
    if ! ping -c 1 -W 2 $NODE_IP > /dev/null 2>&1; then
        echo -e "  ${RED}❌ Node is unreachable${NC}"
        return 1
    fi
    echo -e "  ${GREEN}✅ Node is reachable${NC}"
    
    # SSH and check services
    echo ""
    echo "📊 Services Status:"
    ssh -o ConnectTimeout=5 root@$NODE_IP << 'EOF'
services=("cdn-waf-agent" "nginx")
for service in "${services[@]}"; do
    if systemctl is-active --quiet $service; then
        echo "  ✅ $service: running"
    else
        echo "  ❌ $service: not running"
    fi
done
EOF

    echo ""
    echo "⚙️  Configuration:"
    ssh root@$NODE_IP << 'EOF'
if [ -f /opt/cdn_waf/config.yaml ]; then
    echo "  ✅ config.yaml exists"
    control_url=$(grep -A1 "control_plane:" /opt/cdn_waf/config.yaml | grep "url:" | awk '{print $2}' | tr -d '"' | tr -d "'")
    echo "  🌐 Control Plane: $control_url"
else
    echo "  ❌ config.yaml not found"
fi

if [ -f /etc/nginx/conf.d/cdn.conf ]; then
    echo "  ✅ nginx cdn.conf exists"
    domain_count=$(grep -c "server_name" /etc/nginx/conf.d/cdn.conf || echo "0")
    echo "  📋 Configured domains: $domain_count"
    
    if grep -q "acme-challenge" /etc/nginx/conf.d/cdn.conf; then
        echo "  ✅ ACME challenge sections present"
    else
        echo "  ❌ ACME challenge sections missing"
    fi
else
    echo "  ❌ nginx cdn.conf not found"
fi
EOF

    echo ""
    echo "🧪 ACME Challenge Test:"
    TEST_TOKEN="HEALTH_CHECK_$(date +%s)"
    
    # Set token in Redis
    ssh root@$CONTROL_PLANE "redis-cli SET acme:challenge:$TEST_TOKEN 'test_validation' EX 60" > /dev/null
    
    # Test via Edge Node
    RESPONSE=$(curl -s -H "Host: medcard.ryabich.co" "http://$NODE_IP/.well-known/acme-challenge/$TEST_TOKEN" || echo "ERROR")
    
    if [ "$RESPONSE" == "test_validation" ]; then
        echo -e "  ${GREEN}✅ ACME challenge proxying works${NC}"
    else
        echo -e "  ${RED}❌ ACME challenge proxying failed${NC}"
        echo "     Response: $RESPONSE"
    fi
    
    # Cleanup
    ssh root@$CONTROL_PLANE "redis-cli DEL acme:challenge:$TEST_TOKEN" > /dev/null
    
    echo ""
    echo "📂 Disk Space:"
    ssh root@$NODE_IP "df -h / | tail -1 | awk '{print \"  💿 Root: \" \$3 \" used / \" \$2 \" total (\" \$5 \" used)\"}'"
    
    echo ""
    echo "📊 System Resources:"
    ssh root@$NODE_IP << 'EOF'
cpu_usage=$(top -bn1 | grep "Cpu(s)" | awk '{print $2}' | sed 's/%us,//')
mem_usage=$(free | grep Mem | awk '{printf "%.1f", $3/$2 * 100.0}')
echo "  🖥️  CPU Usage: ${cpu_usage}%"
echo "  💾 Memory Usage: ${mem_usage}%"
EOF
    
    echo ""
}

# Run checks
check_control_plane

for NODE in "${EDGE_NODES[@]}"; do
    echo ""
    check_edge_node "$NODE"
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${GREEN}✅ System Health Check Complete${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "📝 Notes:"
echo "  • All services should be running"
echo "  • ACME challenge proxying should work"
echo "  • Disk usage should be below 80%"
echo ""

