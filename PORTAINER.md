# Purpose: Deploy RestoreProof with Portainer using Docker Hub images
# Author: Doug Hesseltine
# Created: 2026-07-12
# Modified: 2026-07-12
# Version: 1.1.0

# Deploy with Portainer

Use the pre-built images from Docker Hub — no local build required.

| Image | Purpose |
|-------|---------|
| [`yesitsmedoug/restoreproof-api`](https://hub.docker.com/r/yesitsmedoug/restoreproof-api) | FastAPI + worker |
| [`yesitsmedoug/restoreproof-web`](https://hub.docker.com/r/yesitsmedoug/restoreproof-web) | React UI (nginx) |
| `postgres:16-alpine` | Database |

Stack file in this repo: [`portainer-stack.yml`](portainer-stack.yml)

## Portainer steps

1. **Stacks → Add stack**
2. Name: `restoreproof`
3. Paste the contents of [`portainer-stack.yml`](https://raw.githubusercontent.com/hesseltined/RestoreProof/main/portainer-stack.yml)  
   (or upload the file from a git clone)
4. Under **Environment variables**, set at least:

| Variable | Example | Notes |
|----------|---------|--------|
| `POSTGRES_PASSWORD` | long random | Required |
| `SECRET_KEY` | 32+ random chars | JWT + secret encryption |
| `APP_BASE_URL` | `http://10.250.0.50:3080` | URL you open in the browser |
| `CORS_ORIGINS` | same as `APP_BASE_URL` | Comma-separated origins OK |
| `WEB_PORT` | `3080` | Host port for the UI |
| `RESTOREPROOF_TAG` | `latest` or `1.1.0` | Optional image tag |

Generate secrets:

```bash
openssl rand -base64 32   # POSTGRES_PASSWORD or SECRET_KEY
```

5. **Deploy the stack**
6. Open `http://<host>:3080` → create the first admin account
7. Add a Proxmox host (API token + SSH key for VM screenshots) → Sync guests → **Run now**

## After deploy checklist

1. **Hosts** — Test API → SSH key → Test SSH → Sync guests  
2. **Notifications** — SMTP (optional)  
3. **Schedule** — cadence + batch size when ready  
4. **Guests** — exclude anything you do not want tested; run a drill on a safe guest  

## Upgrading

In Portainer: edit the stack → set `RESTOREPROOF_TAG` to a new version (or keep `latest`) → **Pull and redeploy**.

Volumes `rp_pgdata` / `rp_data` / `rp_ssh` keep the database, evidence, and SSH keys.

**Do not recreate the worker mid-restore** — wait until the Dashboard shows idle / no active run.

## Docker Compose (same file)

On a host with Docker Compose v2:

```bash
git clone https://github.com/hesseltined/RestoreProof.git
cd RestoreProof
cp .env.example .env   # edit secrets + APP_BASE_URL
docker compose -f portainer-stack.yml --env-file .env up -d
```

For local development that builds from source, use [`docker-compose.yml`](docker-compose.yml) instead (see [DEVELOPING.md](DEVELOPING.md)).
