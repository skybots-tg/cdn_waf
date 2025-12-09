#!/bin/bash
# Скрипт для проверки настройки ACME challenge

echo "=== Проверка настройки ACME для medcard.ryabich.co ==="
echo ""

echo "1. Проверка DNS (что возвращает DNS сервер):"
dig +short medcard.ryabich.co @217.198.6.85
dig +short medcard.ryabich.co @91.222.237.253
echo ""

echo "2. Проверка Edge Nodes в базе:"
psql -d cdn_waf -c "SELECT id, name, ip_address, status, enabled FROM edge_nodes WHERE enabled = true;"
echo ""

echo "3. Проверка proxied записей в базе:"
psql -d cdn_waf -c "SELECT id, name, type, content, proxied FROM dns_records WHERE domain_id = 4 AND name = 'medcard';"
echo ""

echo "4. Проверка Redis токенов:"
redis-cli --scan --pattern "acme:challenge:*"
echo ""

echo "5. Тест ACME endpoint на control plane (должен вернуть 404 - это нормально):"
curl -v http://localhost:8000/.well-known/acme-challenge/test123
echo ""

echo "6. Проверка доступности с интернета:"
curl -v http://medcard.ryabich.co/.well-known/acme-challenge/test123
echo ""

echo "=== Рекомендуемые действия ==="
echo "1. Перезапустить DNS сервер: systemctl restart cdn-waf-dns"
echo "2. Перезапустить control plane: systemctl restart cdn_waf"
echo "3. Синхронизировать Edge nodes: curl -X POST http://localhost:8000/api/v1/edge-nodes/sync-all"
echo "4. Удалить pending сертификаты и попробовать снова"

