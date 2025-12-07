# Deployment Guide

## Production Deployment

### Prerequisites

- Ubuntu 20.04/22.04 LTS (рекомендуется)
- Python 3.11+
- PostgreSQL 14+
- Redis 7+
- Nginx (для reverse proxy)
- Domain name с настроенными DNS записями

### 1. Подготовка сервера

```bash
# Обновление системы
sudo apt update && sudo apt upgrade -y

# Установка зависимостей
sudo apt install -y python3.11 python3.11-venv python3-pip postgresql postgresql-contrib redis-server nginx git

# Создание пользователя
sudo useradd -m -s /bin/bash cdnwaf
sudo su - cdnwaf
```

### 2. Установка приложения

```bash
# Клонирование репозитория
git clone https://github.com/yourusername/cdn_waf.git
cd cdn_waf

# Создание виртуального окружения
python3.11 -m venv venv
source venv/bin/activate

# Установка зависимостей
pip install -r requirements.txt
```

### 3. Настройка PostgreSQL

```bash
sudo -u postgres psql

# В PostgreSQL shell:
CREATE USER cdn_user WITH PASSWORD 'secure_password_here';
CREATE DATABASE cdn_waf OWNER cdn_user;
GRANT ALL PRIVILEGES ON DATABASE cdn_waf TO cdn_user;
\q
```

### 4. Настройка переменных окружения

```bash
cp .env.example .env
nano .env
```

Отредактируйте `.env`:

```env
APP_ENV=production
DEBUG=False
SECRET_KEY=generate-random-secure-key-here
JWT_SECRET_KEY=another-random-secure-key

DATABASE_URL=postgresql+asyncpg://cdn_user:secure_password_here@localhost:5432/cdn_waf
REDIS_URL=redis://localhost:6379/0

ACME_EMAIL=admin@yourdomain.com
```

### 5. Применение миграций

```bash
alembic upgrade head
```

### 6. Создание systemd сервисов

#### FastAPI App

```bash
sudo nano /etc/systemd/system/cdnwaf-api.service
```

```ini
[Unit]
Description=CDN WAF API
After=network.target postgresql.service redis.service

[Service]
Type=notify
User=cdnwaf
Group=cdnwaf
WorkingDirectory=/home/cdnwaf/cdn_waf
Environment="PATH=/home/cdnwaf/cdn_waf/venv/bin"
ExecStart=/home/cdnwaf/cdn_waf/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 4
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

#### Celery Worker

```bash
sudo nano /etc/systemd/system/cdnwaf-worker.service
```

```ini
[Unit]
Description=CDN WAF Celery Worker
After=network.target postgresql.service redis.service

[Service]
Type=forking
User=cdnwaf
Group=cdnwaf
WorkingDirectory=/home/cdnwaf/cdn_waf
Environment="PATH=/home/cdnwaf/cdn_waf/venv/bin"
ExecStart=/home/cdnwaf/cdn_waf/venv/bin/celery -A app.tasks.celery_app worker -l info --detach
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

#### Celery Beat

```bash
sudo nano /etc/systemd/system/cdnwaf-beat.service
```

```ini
[Unit]
Description=CDN WAF Celery Beat
After=network.target redis.service

[Service]
Type=forking
User=cdnwaf
Group=cdnwaf
WorkingDirectory=/home/cdnwaf/cdn_waf
Environment="PATH=/home/cdnwaf/cdn_waf/venv/bin"
ExecStart=/home/cdnwaf/cdn_waf/venv/bin/celery -A app.tasks.celery_app beat -l info --detach
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### 7. Запуск сервисов

```bash
sudo systemctl daemon-reload
sudo systemctl enable cdnwaf-api cdnwaf-worker cdnwaf-beat
sudo systemctl start cdnwaf-api cdnwaf-worker cdnwaf-beat

# Проверка статуса
sudo systemctl status cdnwaf-api
sudo systemctl status cdnwaf-worker
sudo systemctl status cdnwaf-beat
```

### 8. Настройка Nginx

```bash
sudo nano /etc/nginx/sites-available/cdnwaf
```

```nginx
upstream cdnwaf_backend {
    server 127.0.0.1:8000;
}

server {
    listen 80;
    server_name control.yourcdn.ru;
    
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name control.yourcdn.ru;
    
    ssl_certificate /etc/letsencrypt/live/control.yourcdn.ru/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/control.yourcdn.ru/privkey.pem;
    
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;
    
    client_max_body_size 10M;
    
    location / {
        proxy_pass http://cdnwaf_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
    
    location /static {
        alias /home/cdnwaf/cdn_waf/app/static;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/cdnwaf /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### 9. SSL сертификаты (Let's Encrypt)

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d control.yourcdn.ru
```

### 10. Настройка firewall

```bash
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

### 11. Мониторинг логов

```bash
# API logs
sudo journalctl -u cdnwaf-api -f

# Worker logs
sudo journalctl -u cdnwaf-worker -f

# Nginx logs
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log
```

## Docker Deployment

Альтернативный способ развертывания с использованием Docker:

```bash
# Клонирование репозитория
git clone https://github.com/yourusername/cdn_waf.git
cd cdn_waf

# Настройка .env
cp .env.example .env
nano .env

# Запуск
docker-compose up -d

# Применение миграций
docker-compose exec app alembic upgrade head

# Просмотр логов
docker-compose logs -f
```

## Backup

### Database Backup

```bash
# Создание backup
pg_dump -U cdn_user cdn_waf > backup_$(date +%Y%m%d_%H%M%S).sql

# Восстановление
psql -U cdn_user cdn_waf < backup_20241207_120000.sql
```

### Автоматический backup (cron)

```bash
crontab -e
```

```cron
# Daily backup at 2 AM
0 2 * * * pg_dump -U cdn_user cdn_waf > /backups/cdn_waf_$(date +\%Y\%m\%d).sql
```

## Monitoring

### Health Check Endpoints

- Application: `https://control.yourcdn.ru/health`
- API Docs: `https://control.yourcdn.ru/docs`

### Recommended Monitoring Tools

- **Prometheus + Grafana** для метрик
- **Loki** для логов
- **Uptime Kuma** для uptime monitoring

## Security Checklist

- [ ] Изменены все дефолтные пароли
- [ ] Настроен firewall
- [ ] SSL сертификаты установлены
- [ ] Регулярные backups настроены
- [ ] Логи ротируются
- [ ] Обновления безопасности автоматические
- [ ] Доступ по SSH только по ключам
- [ ] Fail2ban установлен и настроен

