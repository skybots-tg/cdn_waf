# Deploy Instructions - TLS Settings Fix

## Изменения в коде

### 1. Исправлен `app/services/ssl_service.py`
- **Проблема**: Метод `update_tls_settings` обновлял не ту таблицу (пытался обновить `domains` вместо `domain_tls_settings`)
- **Решение**: Теперь правильно работает с таблицей `domain_tls_settings`, создает её если не существует

### 2. Исправлен `app/api/v1/cdn.py`
- **Проблема**: Endpoint `get_tls_settings` возвращал статические данные (TODO комментарий)
- **Решение**: Теперь читает реальные данные из БД, создает настройки с безопасными дефолтами если их нет
- **Важно**: По умолчанию `force_https=False` чтобы избежать redirect loop до получения сертификата

### 3. Улучшен `app/static/js/domain_settings.js`
- Добавлена перезагрузка настроек после сохранения для отображения актуальных данных

## Дополнительные файлы (вспомогательные)

- `check_tls_settings.sql` - SQL запрос для проверки TLS настроек
- `fix_redirect_loop.py` - Python скрипт для быстрого исправления redirect loop
- `TLS_TROUBLESHOOTING.md` - Подробное руководство по устранению проблем с TLS
- `DEPLOY_INSTRUCTIONS.md` - Этот файл

## Как задеплоить

### На сервере flarecloud.ru (control plane)

```bash
# 1. Зайти на сервер
ssh root@flarecloud.ru

# 2. Перейти в директорию проекта
cd ~/cdn_waf

# 3. Сохранить текущие изменения (если есть)
git stash

# 4. Обновить код
git pull origin main

# 5. Активировать виртуальное окружение (если нужно)
source venv/bin/activate

# 6. Перезапустить сервисы
sudo systemctl restart cdn_app.service cdn_celery cdn_celery_beat.service

# 7. Проверить что всё запустилось
sudo systemctl status cdn_app.service
sudo systemctl status cdn_celery.service
sudo systemctl status cdn_celery_beat.service

# 8. Проверить логи (опционально)
sudo journalctl -u cdn_app.service -n 50 --no-pager
```

### Одной командой (быстрый деплой):
```bash
cd ~/cdn_waf && git pull && sudo systemctl restart cdn_app.service cdn_celery cdn_celery_beat.service
```

## После деплоя

### 1. Исправить текущую проблему с ryabich доменом

```bash
# Вариант А: Через Python скрипт
cd ~/cdn_waf
source venv/bin/activate
python fix_redirect_loop.py ryabich.ru

# Вариант Б: Через SQL напрямую
sudo -u postgres psql -d cdn_waf -c "
UPDATE domain_tls_settings 
SET force_https = false, hsts_enabled = false 
WHERE domain_id = 4;
"
```

### 2. Проверить через API

```bash
# Получить текущие настройки
curl -H "Authorization: Bearer YOUR_TOKEN" \
  https://flarecloud.ru/api/v1/domains/4/ssl/settings

# Обновить настройки
curl -X PUT "https://flarecloud.ru/api/v1/domains/4/ssl/settings" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "flexible",
    "force_https": false,
    "hsts_enabled": false
  }'
```

### 3. Проверить в UI

1. Зайти на https://flarecloud.ru/domains/4/settings
2. Открыть вкладку SSL/TLS
3. Убедиться что настройки отображаются корректно
4. Попробовать изменить настройки и сохранить
5. Перезагрузить страницу - настройки должны остаться измененными

## Правильная последовательность для HTTPS

После деплоя, для любого домена:

1. **Сначала**: выпустить сертификат
2. **Потом**: включить `force_https=true`
3. **В последнюю очередь**: включить HSTS (после недели стабильной работы)

## Диагностика проблем

### Проверить текущее состояние домена
```bash
cd ~/cdn_waf
sudo -u postgres psql -d cdn_waf -f check_tls_settings.sql
```

### Проверить логи сертификата
```bash
sudo -u postgres psql -d cdn_waf -c "
SELECT 
    cl.level,
    cl.message,
    cl.details,
    cl.created_at
FROM certificate_logs cl
JOIN certificates c ON c.id = cl.certificate_id
JOIN domains d ON d.id = c.domain_id
WHERE d.name = 'ryabich.ru'
ORDER BY cl.created_at DESC
LIMIT 20;
"
```

### Если редирект всё ещё происходит

1. Проверить что изменения применились в БД
2. Очистить кеш браузера (Ctrl+Shift+Delete)
3. Попробовать в режиме инкогнито
4. Проверить конфигурацию edge nodes (может кешироваться старая конфигурация)

## Откат изменений (если что-то пошло не так)

```bash
cd ~/cdn_waf
git log --oneline -5  # Посмотреть последние коммиты
git checkout <previous-commit-hash>
sudo systemctl restart cdn_app.service cdn_celery cdn_celery_beat.service
```

## Контакты для поддержки

В случае проблем с деплоем:
- Проверить логи: `sudo journalctl -u cdn_app.service -f`
- Проверить статус: `sudo systemctl status cdn_app.service`

