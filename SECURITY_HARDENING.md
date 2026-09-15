# Security hardening — 2026-09-16

Closes a set of authentication / authorization holes and injection vectors found
in an audit of the control plane and edge agent.

## Emergency mitigations already applied to production (out of band)

These were applied directly to the live server to stop active exploitation and
are **superseded and made permanent by this branch**:

- `.env`: `DEBUG=False`, `APP_ENV=production`, rotated `JWT_SECRET_KEY`.
- Disabled + password-rotated the backdoor superusers `admin@example.com`
  (password was literally `admin`) and `test@test.com`.
- `app/core/security.py` hotfixed so the "optional auth" dependency requires a
  token. This branch contains the same fix (and more), so the hotfix is discarded
  at deploy time (see below).

## What this branch changes

- **Authentication is always required.** Removed the `DEBUG` fallback that logged
  anonymous callers in as superuser id 1; `get_optional_current_user` now
  delegates to `get_current_user`.
- **Per-organization tenant isolation.** New `get_domain_for_user` /
  `get_*_for_user` dependencies (`app/api/v1/dependencies.py`) resolve every
  domain-scoped and child resource and assert it belongs to one of the caller's
  organizations (404 on mismatch), wired into domains, dns, cdn, security,
  certificates and analytics. Dropped the implicit "org 1" that funnelled every
  tenant into one shared org; signup now creates a personal org per user.
- **Least privilege on infra routes.** All `dns-nodes` read routes and the global
  analytics dashboards are superuser-only; `/stats/domains` and exports are scoped
  to the caller.
- **Fail-closed secrets.** The app refuses to boot in production on a default/weak
  `JWT_SECRET_KEY` and warns loudly on a default `SECRET_KEY`; `/docs`, `/redoc`,
  `/openapi.json` are disabled outside DEBUG; `seed_data` no longer recreates the
  `admin/admin` superuser in production.
- **Web UI.** Node-management pages (which render node API tokens / SSH keys) are
  superuser-only; per-domain pages verify organization ownership.
- **Input validation** (`app/schemas/validators.py`) constrains tenant strings
  that reach the generated nginx config or the filesystem — domain/host must be a
  hostname/IP, cache & rate-limit patterns and health-check URLs may not contain
  nginx-breaking characters, DNS names are charset-restricted (blocks traversal)
  with length-capped single-line content, WAF conditions are screened, IP rules
  must be valid IP/CIDR. This is the API-boundary defense against
  config-injection → edge RCE.
- **Edge agent** (`edge_node/`): cert/key filenames and cache-purge directories
  are sanitized and asserted to stay inside their base dirs, blocking path
  traversal / `rmtree` escape. Rolls out when edge nodes update their agent.
- **SSRF guard** on origin health checks (blocks loopback / metadata / private
  addresses; no redirect following).
- **Frontend**: quote-safe `escapeHtml`, escaped stored-XSS sinks, stopped
  rendering SSH keys / node tokens into HTML, and fixed the cookie refresh.
- `scripts/rotate_secret_key.py` re-encrypts certificate private keys so
  `SECRET_KEY` can be rotated off the shipped default without breaking TLS.

## Deploy / reconcile

1. Merge this PR.
2. On the server (`/root/cdn_waf`), discard the interim hotfix so the pull is
   clean (this branch supersedes it); `.env` is gitignored and preserved:
   ```bash
   git checkout -- app/core/security.py
   git pull origin main
   ```
   If local edits to `test_acme_setup.sh` / `test_edge_download.sh` block the
   pull, stash them: `git stash push -m predeploy test_acme_setup.sh test_edge_download.sh`.
3. No DB migration is required (`alembic upgrade head` is a safe no-op).
4. `systemctl restart cdn_app cdn_celery cdn_celery_beat`.
5. Verify: `curl -s -o /dev/null -w '%{http_code}' https://flarecloud.ru/api/v1/domains` → `401`; log in with your own account.
6. Edge nodes pick up `edge_node/` changes on their next agent update.

## Recommended follow-ups (not in this PR)

1. **Rotate `SECRET_KEY`** with `scripts/rotate_secret_key.py` (dry-run first),
   set the new value in `.env`, restart. Until then it is the shipped default and
   it encrypts certificate private keys.
2. **DNS node `/api/v1/sync`** (`app/dns_server.py`, port 8000 on each DNS node)
   has no authentication and `TRUNCATE`s tables. Interim: firewall port 8000 on
   every DNS node to the control-plane IP. Proper fix: require a shared
   `NODE_SYNC_TOKEN` (already threaded through config) — a coordinated change
   because it must ship to the DNS nodes at the same time.
3. Encrypt edge/DNS node SSH keys & passwords and ACME account keys (plaintext in
   DB today); pin SSH host keys (`ssh_utils` uses `known_hosts=None`).
4. Broaden the frontend XSS pass; add rate limiting on auth + certificate issue;
   add refresh-token rotation / denylist.
5. Reassign organization 1's owner from the disabled `admin@example.com` to the
   real owner account (cosmetic; superusers see everything regardless).
