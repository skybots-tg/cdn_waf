---
name: cdn-waf-server
description: Deploy and troubleshoot the CDN WAF project on production server 188.116.24.50. Use when the user asks to deploy, update, restart, check logs, or diagnose issues on the CDN WAF server, or mentions deploy, production, сервер, деплой.
---

# CDN WAF Server Operations

## Server Details

- **IP**: 188.116.24.50
- **User**: root
- **SSH key**: `~/.ssh/qufa`
- **SSH alias**: `cdn_waf` (in `~/.ssh/config`)
- **Project path**: `/root/cdn_waf`
- **Python venv**: `/root/cdn_waf/venv`
- **Git remote**: `https://github.com/skybots-tg/cdn_waf` (branch: `main`)

## SSH Access

```bash
ssh -i ~/.ssh/qufa root@188.116.24.50
```

Or via SSH MCP (connectionName: `cdn_waf`) if configured.

## Systemd Services

| Service | Description | Command |
|---------|-------------|---------|
| `cdn_app` | Uvicorn API (port 2000) | `systemctl restart cdn_app` |
| `cdn_celery` | Celery worker (solo pool) | `systemctl restart cdn_celery` |
| `cdn_celery_beat` | Celery Beat scheduler | `systemctl restart cdn_celery_beat` |

## Deploy Workflow (manual, only when asked)

1. Push changes to `origin/main` from local repo
2. SSH into server and pull:
   ```bash
   cd /root/cdn_waf && git pull origin main
   ```
3. Install new dependencies (if requirements.txt changed):
   ```bash
   source venv/bin/activate && pip install -r requirements.txt
   ```
4. Run database migrations (if any):
   ```bash
   source venv/bin/activate && alembic upgrade head
   ```
5. Restart services:
   ```bash
   systemctl restart cdn_app cdn_celery cdn_celery_beat
   ```

## Quick Restart (no code changes)

```bash
systemctl restart cdn_app cdn_celery cdn_celery_beat
```

## Diagnostics

### Check service status
```bash
systemctl status cdn_app cdn_celery cdn_celery_beat
```

### View logs (last 100 lines)
```bash
journalctl -u cdn_app -n 100 --no-pager
journalctl -u cdn_celery -n 100 --no-pager
journalctl -u cdn_celery_beat -n 50 --no-pager
```

### Search for errors in logs
```bash
journalctl -u cdn_celery --since "1 hour ago" --no-pager | grep -i "error\|exception\|traceback"
```

### Check database
```bash
sudo -u postgres psql cdn_waf -c "SELECT count(*) FROM domains;"
sudo -u postgres psql cdn_waf -c "SELECT id, name, ip_address, enabled, disabled_by, status FROM dns_nodes;"
sudo -u postgres psql cdn_waf -c "SELECT id, name, ip_address, enabled, status FROM edge_nodes;"
```

## Database

- **Engine**: PostgreSQL (local)
- **Connection**: `postgresql+asyncpg://postgres:...@localhost:5432/cdn_waf`
- **Migrations**: Alembic (`alembic upgrade head`)

## Important Notes

- **Never deploy automatically** — only when the user explicitly asks
- Always `git pull` before restarting services
- The `.env` file on the server should NOT be overwritten unless specifically asked
- Celery worker uses `--pool=solo` (single-threaded)
- API runs on port 2000 behind Nginx
