# TLS/HTTPS Troubleshooting Guide

## Problem: "The page isn't redirecting properly" (Redirect Loop)

### Причина
Бесконечный редирект происходит когда:
1. `force_https = true` (принудительный редирект HTTP → HTTPS)
2. Но у домена нет активного сертификата
3. Браузер пытается зайти по HTTPS → edge node редиректит на HTTP → браузер снова пытается HTTPS → цикл

### Решение

#### Вариант 1: Быстрое исправление (скрипт)
```bash
python fix_redirect_loop.py domain.com
```

#### Вариант 2: Через SQL
```bash
# Проверить текущие настройки
sudo -u postgres psql -d cdn_waf -f check_tls_settings.sql

# Отключить force_https для домена
sudo -u postgres psql -d cdn_waf -c "
UPDATE domain_tls_settings 
SET force_https = false, hsts_enabled = false 
WHERE domain_id = (SELECT id FROM domains WHERE name = 'domain.com');
"
```

#### Вариант 3: Через API (после деплоя исправлений)
```bash
curl -X PUT "https://flarecloud.ru/api/v1/domains/4/ssl/settings" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"force_https": false, "hsts_enabled": false}'
```

## Правильная последовательность настройки HTTPS

### Шаг 1: Убедитесь что домен активен
```bash
sudo -u postgres psql -d cdn_waf -c "
SELECT id, name, status, ns_verified FROM domains WHERE name = 'domain.com';
"
```

### Шаг 2: Выпустите сертификат
- Через UI: перейдите в настройки домена → SSL/TLS → Request Certificate
- Или через API: `POST /api/v1/domains/{domain_id}/ssl/certificates`

Дождитесь статуса `issued`:
```bash
sudo -u postgres psql -d cdn_waf -c "
SELECT id, status, not_after FROM certificates 
WHERE domain_id = (SELECT id FROM domains WHERE name = 'domain.com');
"
```

### Шаг 3: Настройте TLS (только после получения сертификата!)
```json
{
  "mode": "flexible",        // Edge HTTPS, Origin HTTP
  "force_https": true,       // ← Включать ТОЛЬКО после получения сертификата!
  "hsts_enabled": false,     // Пока оставить false
  "min_tls_version": "1.2",
  "auto_certificate": true
}
```

### Шаг 4: (Опционально) Включите HSTS
После того как всё работает стабильно неделю:
```json
{
  "hsts_enabled": true,
  "hsts_max_age": 31536000,
  "hsts_include_subdomains": false,
  "hsts_preload": false
}
```

## TLS Modes

### `flexible` (рекомендуется)
- Edge ↔ Client: HTTPS
- Edge ↔ Origin: HTTP
- **Плюсы**: работает с любым origin, не требует SSL на origin
- **Минусы**: трафик edge→origin не шифрован

### `full`
- Edge ↔ Client: HTTPS
- Edge ↔ Origin: HTTPS (любой сертификат, даже самоподписанный)
- **Плюсы**: полное шифрование
- **Минусы**: требует SSL на origin

### `strict`
- Edge ↔ Client: HTTPS
- Edge ↔ Origin: HTTPS (только валидный сертификат)
- **Плюсы**: максимальная безопасность
- **Минусы**: требует правильно настроенный SSL на origin

## Проверка настроек

### Проверить текущие TLS настройки
```bash
sudo -u postgres psql -d cdn_waf -f check_tls_settings.sql
```

### Проверить сертификаты
```bash
sudo -u postgres psql -d cdn_waf -c "
SELECT 
    d.name,
    c.id,
    c.status,
    c.cert_type,
    c.not_before,
    c.not_after,
    c.common_name,
    c.issuer
FROM certificates c
JOIN domains d ON d.id = c.domain_id
WHERE d.name = 'domain.com'
ORDER BY c.created_at DESC;
"
```

## Частые проблемы

### 1. API не обновляет настройки
**Причина**: Старая версия кода обновляла не ту таблицу
**Решение**: Деплой исправлений (этот коммит)

### 2. Ошибка "Column t.https_enabled does not exist"
**Причина**: Неправильное имя колонки в SQL запросе
**Решение**: Использовать `hsts_enabled` вместо `https_enabled`

### 3. Сертификат не выпускается
Проверьте логи:
```bash
sudo -u postgres psql -d cdn_waf -c "
SELECT * FROM certificate_logs 
WHERE certificate_id = YOUR_CERT_ID 
ORDER BY created_at DESC LIMIT 10;
"
```

## Деплой исправлений

На control plane сервере (flarecloud.ru):
```bash
cd ~/cdn_waf
git pull
sudo systemctl restart cdn_app.service cdn_celery cdn_celery_beat.service
```

Проверить что сервисы запустились:
```bash
sudo systemctl status cdn_app.service
sudo systemctl status cdn_celery.service
sudo systemctl status cdn_celery_beat.service
```

