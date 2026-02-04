# Edge Node Configuration

Этот модуль отвечает за работу edge-нод (CDN серверов), которые проксируют трафик от клиентов к origin-серверам.

## Архитектура

Edge-нода состоит из:

1. **Nginx** - HTTP(S) reverse proxy с кэшированием
2. **Config Updater (Agent)** - Python скрипт, который получает конфигурацию с control plane
3. **Monitoring Agent** - Отправляет метрики и логи в центральную систему

## Установка Edge-ноды

### Требования

- Ubuntu 22.04 или 24.04 (рекомендуется)
- Python 3.10+ (встроен в Ubuntu)
- Nginx (устанавливается автоматически)
- Минимум 2GB RAM, 20GB диск
- Root или sudo доступ

### Быстрая установка (автоматическая)

**Вариант 1: Через веб-интерфейс Control Plane**

1. Добавьте edge-ноду в Control Plane (указав IP, SSH credentials)
2. Нажмите "Install System" → "Install Nginx" → "Install Python" → "Install Agent"
3. Нода автоматически начнёт получать конфигурацию

**Вариант 2: Через скрипт (на самой ноде)**

1. Скопируйте файлы на сервер:
```bash
scp -r edge_node/ root@your-edge-ip:/opt/cdn_waf/
```

2. Создайте конфигурационный файл:
```bash
ssh root@your-edge-ip
cd /opt/cdn_waf
cp config.example.yaml config.yaml
nano config.yaml  # Укажите id, api_key, control_plane url
```

3. Запустите полную установку:
```bash
sudo ./setup.sh install_all
```

### Пошаговая установка (ручная)

Если нужен более гранулярный контроль:

```bash
# 1. Установка системных зависимостей
sudo ./setup.sh install_deps

# 2. Установка и настройка Nginx
sudo ./setup.sh install_nginx

# 3. Установка Certbot (опционально, для локальных сертификатов)
sudo ./setup.sh install_certbot

# 4. Настройка Python окружения
sudo ./setup.sh install_python

# 5. Создание конфигурации (ВАЖНО: сделать до следующего шага!)
cp config.example.yaml config.yaml
# Отредактируйте config.yaml - укажите:
#   - edge_node.id (уникальный ID ноды из Control Plane)
#   - edge_node.name (имя ноды)
#   - control_plane.url (URL вашего Control Plane)
#   - control_plane.api_key (API ключ ноды из Control Plane)

# 6. Установка и запуск агента
sudo ./setup.sh install_agent_service

# 7. Проверка установки
sudo ./setup.sh verify
```

### Проверка статуса

```bash
# Статус nginx
sudo systemctl status nginx

# Статус агента
sudo systemctl status cdn-waf-agent

# Логи агента
sudo journalctl -u cdn-waf-agent -f

# Проверка nginx конфига
sudo nginx -t
```

## Конфигурация

### config.yaml

```yaml
edge_node:
  id: 1
  name: "ru-msk-01"
  location: "RU-MSK"
  
control_plane:
  url: "https://control.yourcdn.ru"
  api_key: "your-api-key-here"
  
update_interval: 30  # seconds

nginx:
  config_path: "/usr/local/openresty/nginx/conf/cdn.conf"
  reload_command: "sudo systemctl reload openresty"
  
monitoring:
  enabled: true
  endpoint: "https://control.yourcdn.ru/api/v1/edge/metrics"
```

## Работа Config Updater

Config updater периодически запрашивает конфигурацию с control plane:

```
GET /internal/edge/config?node_id=1&version=42
```

Если есть обновления, получает новый конфиг и генерирует Nginx конфиг:

```nginx
# Пример сгенерированного конфига
server {
    listen 443 ssl http2;
    server_name example.com;
    
    ssl_certificate /etc/ssl/certs/example.com.crt;
    ssl_certificate_key /etc/ssl/private/example.com.key;
    
    # Cache configuration
    proxy_cache_path /var/cache/nginx/example.com levels=1:2 keys_zone=example_com:10m;
    proxy_cache example_com;
    proxy_cache_valid 200 1h;
    
    # WAF rules
    # ... (generated from database)
    
    location / {
        proxy_pass https://origin.example.com;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## Мониторинг

Edge-нода отправляет метрики каждые N секунд:

```json
{
  "node_id": 1,
  "timestamp": "2024-12-07T10:20:30Z",
  "metrics": {
    "cpu_usage": 45.2,
    "memory_usage": 62.1,
    "disk_usage": 28.5,
    "requests_per_sec": 1250,
    "bandwidth_mbps": 125.5
  }
}
```

## Безопасность

1. **mTLS** для связи с control plane (рекомендуется)
2. **IP whitelist** для internal API endpoints
3. **API ключи** с ограниченными правами
4. **Регулярные обновления** системы и пакетов

## Масштабирование

Для добавления новой edge-ноды:

1. Зарегистрируйте ноду в control plane
2. Получите API ключ
3. Установите и настройте по инструкции выше
4. Нода автоматически начнёт получать конфигурацию

## Troubleshooting

### Нода не получает конфиг

Проверьте:
- Доступность control plane
- Правильность API ключа
- Логи в `/var/log/cdn_edge/updater.log`

### Nginx не перезагружается

Проверьте:
- Синтаксис конфига: `nginx -t`
- Права доступа к файлам сертификатов
- Логи Nginx: `/var/log/nginx/error.log`

### Высокая нагрузка

Оптимизируйте:
- Увеличьте worker_processes в Nginx
- Настройте лимиты соединений
- Добавьте больше RAM для кэша
- Распределите нагрузку на дополнительные ноды


