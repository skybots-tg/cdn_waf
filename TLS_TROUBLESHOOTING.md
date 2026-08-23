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


## Два центра выпуска сертификатов: панель vs certbot на origin

Для одного и того же хоста сертификат могут выпускать две независимые системы, и
какая из них способна пройти валидацию — зависит от того, включена ли хоть одна
edge-нода.

**ACME панели** (таблица `certificates`, `type=ACME`, задача
`check_expiring_certificates`) обслуживает проксируемые домены. Токены лежат в
Redis (`acme:challenge:<token>`), эндпоинт — `/.well-known/acme-challenge/{token}`
в `app/main.py`. Nginx на edge (шаблон в `edge_node/edge_config_updater.py`)
проксирует `/.well-known/acme-challenge/` на control plane `flarecloud.ru`, то
есть этот путь существует **только при живой edge-ноде**.

**certbot на origin** обслуживает локальные vhost'ы тех же хостов. Он проходит
http-01 только пока **все** edge-ноды выключены: тогда
`dns_server.get_edge_nodes_ips()` не находит ноды со `status=online AND
enabled=true`, и DNS отдаёт A-запись origin. Стоит включить edge — certbot на
origin начинает падать, потому что челлендж уходит на control plane, где его
токена нет.

### Симптом

`Failed to renew certificate <domain> with error: Some challenges have failed`
с деталью вида `Invalid response from http://<domain>/.well-known/acme-challenge/...: 404`,
где IP в сообщении — адрес edge-ноды, а не origin.

### Что должно быть настроено

1. На origin — сниппет `scripts/nginx/acme-control-plane.conf`, включённый в
   443-блок каждого проксируемого vhost'а. Это даёт ACME панели путь валидации
   и при выключенном edge-фронте.
2. `authenticator = nginx` (не `standalone`) во всех
   `/etc/letsencrypt/renewal/*.conf` — `standalone` требует свободный порт 80 и
   при живом nginx не работает никогда.
3. Один certbot на хост. Если рядом стоят apt-версия, snap и pip в venv, старая
   не умеет читать конфиги v5 (`Attempting to parse the version 5.x ... with
   version 0.40.0 of Certbot. This might not work.`).

### Проверка

```bash
# челлендж должен дойти до control plane, а не до приложения за vhost'ом
curl -s --resolve $D:443:<ORIGIN_IP> https://$D/.well-known/acme-challenge/probe
# ожидаемый ответ: {"detail":"Challenge token not found"}
```

Ответ `{"detail":"Not Found"}` значит, что запрос ушёл в приложение за
`location /`, а не в панель.

### Запрос к таблице certificates

В таблице копятся FAILED-записи от прошлых попыток (на 2026-08-11 их было ~7200)
и множество устаревших EXPIRED. `ORDER BY id LIMIT n` покажет только древние
дубли — фильтруйте по `not_after > now()` или `status = 'ISSUED'`.

## Включение edge-ноды: что проверить заранее

Ротация DNS **глобальная**: в панели нет выбора ноды для отдельного домена.
`dns_server.get_edge_nodes_ips()` берёт все ноды со `status=online AND
enabled=true`, и как только включена хотя бы одна, на неё уходят **все** записи
с `proxied=true` во всех зонах. Пока весь парк выключен, «оранжевое облачко»
не делает ничего — DNS отдаёт origin из содержимого записи.

Поэтому включение ноды — это переезд всех проксируемых хостов сразу. Перед ним:

1. **Записи, указывающие на саму ноду.** Origin для vhost'а берётся из
   содержимого A-записи (`app/api/internal.py`, `get_edge_config`). Если запись
   указывает на IP edge-ноды (так делали для formbit.ru как обход обрыва
   TLS 1.3), после регенерации конфига upstream станет самой нодой — nginx
   уйдёт в петлю. Сначала вернуть в запись настоящий origin, проксирование
   оставить включённым: фронт всё равно даст нода.

   ```sql
   SELECT r.name, d.name, r.content FROM dns_records r JOIN domains d ON d.id=r.domain_id
   WHERE r.content IN (SELECT ip_address FROM edge_nodes);
   ```

2. **Сертификат на каждый проксируемый хост.** Хост без сертификата в панели
   получает vhost только на 80 порту, а HTTPS-запрос попадает в default_server
   с самоподписанным «CDN Default» — у читателей ошибка сертификата. До
   включения проверить каждый хост через ноду (`--resolve host:443:<node>`), и
   то, для чего сертификата нет, снять с проксирования.

3. **certbot на origin.** См. раздел выше: после включения он перестаёт
   продлевать сертификаты проксируемых хостов. Пользователям это не мешает
   (TLS терминирует edge), но откат «выключить ноду» после истечения
   сертификата origin даст ошибку у читателей. Держать это в календаре.

4. **Перезапуск control plane во время работы ноды.** Агент перезаписывает
   конфиг по расписанию; если в этот момент панель недоступна, запросы
   сертификатов падают. С августа 2026 агент в такой ситуации оставляет копию
   с диска, но старые сборки агента на нодах выключали TLS у всех домов сразу —
   перед деплоем панели убедиться, что на включённых нодах агент свежий
   (в логе должно быть `keeping the copy on disk`, а не `disabling TLS`).

Проверка после включения — обойти все проксируемые хосты **не со своей машины**
(с чужой сети попадёшь под защиту от сканирования у хостера ноды и получишь
случайные таймауты), а с любого сервера:

```bash
while read -r h; do
  printf "%-30s " "$h"
  curl -sS -o /dev/null --max-time 10 -w "%{http_code}/%{ssl_verify_result}\n" "https://$h/"
done < hosts.txt
```
