# Краткая сводка исправлений

## 🐛 Найденные проблемы

### 1. TLS настройки не обновляются
**Причина**: Бэкенд обновлял неправильную таблицу (`domains` вместо `domain_tls_settings`)

**Симптомы**:
- Меняешь настройки в UI → сохраняешь → перезагружаешь страницу → старые значения
- API запрос уходит успешно, но данные не меняются в БД

### 2. Бесконечный редирект (redirect loop)
**Причина**: `force_https=true` включен, но сертификата нет

**Симптом**: "The page isn't redirecting properly" в браузере

**Логика**:
1. Браузер → HTTPS → Edge Node
2. Edge Node видит что сертификата нет → редирект на HTTP
3. Edge Node видит `force_https=true` → редирект на HTTPS
4. Goto 1 (бесконечный цикл)

### 3. Неправильное имя колонки в SQL
**Ошибка**: `ERROR: column t.https_enabled does not exist`

**Правильно**: Колонка называется `hsts_enabled`, а не `https_enabled`

## ✅ Что исправлено

### Файл: `app/services/ssl_service.py`
```python
# Было: обновлял domain напрямую
for key, value in settings.items():
    if hasattr(domain, key):
        setattr(domain, key, value)

# Стало: обновляет domain_tls_settings
tls_settings = DomainTLSSettings.query...
for key, value in settings.items():
    if hasattr(tls_settings, key):
        setattr(tls_settings, key, value)
```

### Файл: `app/api/v1/cdn.py`
```python
# Было: возвращал хардкод
return TLSSettingsResponse(
    mode="flexible",
    force_https=True,  # всегда True!
    ...
)

# Стало: читает из БД
tls_settings = await db.get(DomainTLSSettings, domain_id)
return TLSSettingsResponse(
    mode=tls_settings.mode.value,
    force_https=tls_settings.force_https,  # реальное значение
    ...
)
```

### Файл: `app/static/js/domain_settings.js`
```javascript
// Добавлено: перезагрузка после сохранения
async function saveTLSSettings() {
    // ... save ...
    showNotification('TLS settings saved', 'success');
    await loadTLSSettings(); // ← новая строка
}
```

## 🚀 Как задеплоить

На сервере flarecloud.ru:
```bash
cd ~/cdn_waf
git pull
sudo systemctl restart cdn_app.service cdn_celery cdn_celery_beat.service
```

## 🔧 Как исправить ryabich домен

### Вариант 1: Скрипт (рекомендуется)
```bash
cd ~/cdn_waf
source venv/bin/activate
python fix_redirect_loop.py ryabich.ru
```

### Вариант 2: SQL
```bash
sudo -u postgres psql -d cdn_waf -c "
UPDATE domain_tls_settings 
SET force_https = false, hsts_enabled = false 
WHERE domain_id = 4;
"
```

### Вариант 3: Через UI (после деплоя)
1. Зайти на https://flarecloud.ru/domains/4/settings
2. Вкладка SSL/TLS
3. Снять галочку "Force HTTPS"
4. Снять галочку "Enable HSTS"
5. Сохранить

## 📋 Проверка

### Проверить что всё работает:
```bash
# 1. Проверить текущие настройки
sudo -u postgres psql -d cdn_waf -f check_tls_settings.sql

# 2. Проверить через API
curl -H "Authorization: Bearer TOKEN" \
  https://flarecloud.ru/api/v1/domains/4/ssl/settings

# 3. Открыть в браузере
# https://flarecloud.ru/domains/4/settings
```

## 🎯 Правильная настройка HTTPS (для всех доменов)

### Шаг 1: Выпустить сертификат
```
UI: Domains → Settings → SSL/TLS → Issue Certificate
```

### Шаг 2: Дождаться статуса "issued"
```sql
SELECT status, not_after FROM certificates WHERE domain_id = 4;
```

### Шаг 3: Включить Force HTTPS
```json
{
  "mode": "flexible",
  "force_https": true,  ← Только после шага 1-2!
  "hsts_enabled": false
}
```

### Шаг 4: (Опционально) Включить HSTS
Через неделю стабильной работы:
```json
{
  "hsts_enabled": true,
  "hsts_max_age": 31536000
}
```

## 📖 Режимы TLS

| Режим | Edge↔Client | Edge↔Origin | Когда использовать |
|-------|-------------|-------------|-------------------|
| **flexible** | HTTPS | HTTP | Origin без SSL (рекомендуется) |
| **full** | HTTPS | HTTPS (любой cert) | Origin с SSL (даже самоподписанный) |
| **strict** | HTTPS | HTTPS (валидный cert) | Максимальная безопасность |

## ⚠️ Важно!

1. **НЕ включать** `force_https` до получения сертификата → будет redirect loop
2. **НЕ включать** HSTS сразу → сначала убедиться что всё работает
3. **Режим flexible** подходит для большинства случаев

## 🆘 Если что-то не работает

1. Очистить кеш браузера (Ctrl+Shift+Delete)
2. Попробовать в режиме инкогнито
3. Проверить логи: `sudo journalctl -u cdn_app.service -n 50`
4. Проверить статус: `sudo systemctl status cdn_app.service`

## 📝 Дополнительные файлы

- `TLS_TROUBLESHOOTING.md` - Подробное руководство
- `DEPLOY_INSTRUCTIONS.md` - Инструкции по деплою
- `check_tls_settings.sql` - SQL запрос для проверки
- `fix_redirect_loop.py` - Скрипт для исправления redirect loop

