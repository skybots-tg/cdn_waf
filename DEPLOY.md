# Деплой обновлений

## Control Plane (flarecloud.ru)

```bash
ssh root@flarecloud.ru
cd /opt/cdn_waf
git pull && systemctl restart cdn_app.service cdn_celery cdn_celery_beat.service
```

## Edge Node (92.246.76.113)

```bash
ssh root@92.246.76.113
sudo systemctl restart cdn-waf-agent
```

## Проверка ACME

```bash
# На Control Plane - записать тестовый токен
ssh root@flarecloud.ru
redis-cli SET "acme:challenge:TEST" "validation123" EX 300

# Проверить через Edge Node
curl -H "Host: medcard.ryabich.co" http://92.246.76.113/.well-known/acme-challenge/TEST
# Должен вернуть: validation123

# Очистить
ssh root@flarecloud.ru
redis-cli DEL "acme:challenge:TEST"
```

## Исправления

✅ **app/api/internal.py** (строка 283): `acme_url` → `control_plane_url`

✅ **edge_node/edge_config_updater.py** (строки 378-392): Правильная обработка `control_plane_url`

