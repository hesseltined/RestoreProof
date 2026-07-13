# Purpose: Deploy RestoreProof with Portainer using Docker Hub images
# Author: Doug Hesseltine
# Created: 2026-07-12
# Modified: 2026-07-12
# Version: 1.3.0

# Deploy with Portainer

Use the pre-built images from Docker Hub — no local build required.

| Image | Purpose |
|-------|---------|
| [`yesitsmedoug/restoreproof-api`](https://hub.docker.com/r/yesitsmedoug/restoreproof-api) | FastAPI + worker |
| [`yesitsmedoug/restoreproof-web`](https://hub.docker.com/r/yesitsmedoug/restoreproof-web) | React UI (nginx) |
| `postgres:16-alpine` | Database |

Stack file: [`portainer-stack.yml`](portainer-stack.yml)

## Generate safe secrets (required)

Use **hex only**. Do **not** use `openssl rand -base64` or passwords containing `# @ : / ? % &`.

Those characters break Portainer/YAML (`#` = comment) and the Postgres URL inside the stack (`#` = URL fragment), which leads to API crash-loops and “API unreachable” / Bad Gateway.

```bash
# Database password (24 bytes → 48 hex chars)
openssl rand -hex 24

# App secret — use THE SAME value for API_SECRET_KEY and WORKER_SECRET_KEY
openssl rand -hex 32
```

Save these somewhere durable (password manager). You will need the app secret again for config import on a rebuilt VM.

## Portainer steps

1. **Stacks → Add stack** → name `restoreproof`
2. Paste [`portainer-stack.yml`](https://raw.githubusercontent.com/hesseltined/RestoreProof/main/portainer-stack.yml)
3. Under **Environment variables** (Portainer UI panel — preferred over typing secrets into YAML), set:

| Name | Value |
|------|--------|
| `POSTGRES_PASSWORD` | output of `openssl rand -hex 24` |
| `API_SECRET_KEY` | output of `openssl rand -hex 32` |
| `WORKER_SECRET_KEY` | **identical** to `API_SECRET_KEY` |

4. **Deploy** → open `http://<host>:3080` (or your NPM domain) → create admin

Login / footer show **UI v… · API v…**. If you see **API unreachable**, the API container is down — check `docker logs <stack>_api_1` (usually bad `SECRET_KEY` or DB password).

The UI proxies `/api` on the same host, so NPM only needs to forward to port **3080**.

### Optional: public URL for email links

Only if password-reset or notification emails need your public domain, add under **both** `api` and `worker` `environment:`:

```yaml
APP_BASE_URL: https://restoreproof.example.com
```

## After deploy

1. **Hosts** — paste token ID + secret → **Test API** → SSH key → Test SSH → Sync guests  
2. **Notifications** — SMTP (optional)  
3. **Schedule** — when ready  
4. **Guests** — exclude what you do not want tested; run a drill  

## Migrating / importing configuration

Settings → **Export / Import configuration** moves hosts, SMTP, schedules, and SSH keys (not run history).

| Rule | Why |
|------|-----|
| Target must use the **same** `API_SECRET_KEY` / `SECRET_KEY` as the source (and `ENCRYPTION_KEY` if you set one) | Proxmox token + SMTP password are Fernet-encrypted with that key |
| Or re-enter every API token secret and SMTP password after import | Required if you intentionally rotate the secret on the new server |
| Do **not** change `POSTGRES_PASSWORD` on an existing `rp_pgdata` volume | Postgres only applies `POSTGRES_PASSWORD` on **first** init |
| Keep `API_SECRET_KEY` and `WORKER_SECRET_KEY` identical | Worker and API must encrypt/decrypt the same way |

## Upgrading

Edit stack → **Pull and redeploy** (`latest` tag).

To pin a version: `yesitsmedoug/restoreproof-api:1.2.0` and `yesitsmedoug/restoreproof-web:1.2.0`.

Volumes `rp_pgdata` / `rp_data` / `rp_ssh` keep DB, evidence, and SSH keys.

**Do not recreate the worker mid-restore.**

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Login shows **API unreachable** / HTTP 502 on `/api/*` | API crash-loop (DB auth or empty `SECRET_KEY`) | `docker logs …_api_1`; regenerate **hex** secrets; if password changed after first boot, reset DB password or recreate `rp_pgdata` |
| **Test API** → Internal Server Error / “cannot be decrypted” | Token encrypted with a different `SECRET_KEY` (import or secret rotation) | Re-enter Proxmox token secret on the host, or restore the original `API_SECRET_KEY` |
| SSH green, API red | Same decrypt issue (SSH keys are files, not Fernet) | Re-enter API token secret |
| Stack won’t deploy / empty env | Missing Portainer env vars | Set all three required variables before deploy |
