# Purpose: RestoreProof — automated Proxmox PBS restore drills
# Author: Doug Hesseltine
# Created: 2026-07-12
# Modified: 2026-07-22
# Version: 1.3.0

# RestoreProof

**Community edition** (Apache-2.0) — prove your Proxmox backups actually restore.

RestoreProof runs non-destructive restore drills against [Proxmox Backup Server](https://www.proxmox.com/en/proxmox-backup-server) snapshots:

1. Restore latest PBS backup to a temporary VMID (pool `9000–9099`)
2. Detach NICs (original guest stays online)
3. Power on → wait → capture console evidence
4. Clean up the test guest
5. Email success/failure and show proof in the UI

**Public demo (no login):** [https://restoreproof.technologist.services/demo](https://restoreproof.technologist.services/demo) — same menus as production, sample data only.

## Deploy options

| Method | When to use | Guide |
|--------|-------------|--------|
| **Portainer** (recommended for Docker hosts) | Pull Hub images, paste YAML | [PORTAINER.md](PORTAINER.md) · [`portainer-stack.yml`](portainer-stack.yml) |
| **Docker Compose (Hub images)** | Same YAML without Portainer UI | [PORTAINER.md](PORTAINER.md) |
| **Compose (build from source)** | Development / custom builds | below · [DEVELOPING.md](DEVELOPING.md) |
| **LXC on Proxmox** | Nested Docker in an Ubuntu CT | [INSTALL-LXC.md](INSTALL-LXC.md) |

### Portainer (quick)

1. Generate **hex-only** secrets (see [PORTAINER.md](PORTAINER.md) — do not use base64 or `#` in passwords)
2. Stacks → Add stack → paste [`portainer-stack.yml`](portainer-stack.yml)
3. Set env: `POSTGRES_PASSWORD`, `API_SECRET_KEY`, `WORKER_SECRET_KEY` (API and worker secrets **must match**)
4. Deploy → open `http://<host>:3080`

Images: [`yesitsmedoug/restoreproof-api`](https://hub.docker.com/r/yesitsmedoug/restoreproof-api) · [`yesitsmedoug/restoreproof-web`](https://hub.docker.com/r/yesitsmedoug/restoreproof-web)

Login / page footers show **UI version · API version** (or **API unreachable** if the API container is down).

### Compose (build from source)

```bash
cp .env.example .env
# set SECRET_KEY and POSTGRES_PASSWORD to openssl rand -hex … values
docker compose up -d --build
```

Open **http://localhost:3080** — create the first admin, then add a host and run a drill.

## Architecture

| Service | Role |
|---------|------|
| `web` | React UI (nginx proxies `/api`) |
| `api` | FastAPI — auth, hosts, guests, runs |
| `worker` | Queue + schedule + restore pipeline |
| `db` | PostgreSQL |

- **Proxmox API token** = primary automation
- **SSH key** = VM screenshots, plus root fallback for USB/PCI VMs and CTs with bind mounts
- **One restore at a time** (global lock)
- Progress on the Dashboard while a restore is running (Proxmox often omits a % during disk transfer)

## Features (v1)

- Multi-host / cluster API endpoints
- QEMU VMs + LXC containers
- PBS backups only
- Global schedule (UTC or local display) + batch size to cover the fleet weekly/monthly
- Per-guest overrides + exclude + Run now → Dashboard progress
- Hosts page shows latest restore evidence (or clear failure)
- SMTP presets (M365, SMTP2GO, Zoho, Gmail, SendGrid, Mailgun, SES)
- Config export/import for rebuilds (requires same `SECRET_KEY` / `API_SECRET_KEY`)
- Local admins, password reset, TOTP 2FA
- Light/dark UI, collapsible sidebar
- Version string on login and page footers
- Banner when GitHub or Docker Hub has a newer RestoreProof, with upgrade steps

## GitHub + Docker Hub

- Source: https://github.com/hesseltined/RestoreProof  
- Images: `yesitsmedoug/restoreproof-api`, `yesitsmedoug/restoreproof-web`

Maintainer publish (does **not** restart a running local compose stack):

```bash
./scripts/push-images.sh
# optional: VERSION=1.2.0 ./scripts/push-images.sh
```

Full notes: [DEVELOPING.md](DEVELOPING.md)

## Setup wizard

After first admin creation, the Dashboard may show a **Setup wizard** checklist (SMTP, host, sync, manual drill, schedule).

- **Mark setup complete** hides it (not forced — you can hide temporarily).
- If stored Proxmox/SMTP secrets fail to decrypt (wrong `SECRET_KEY` after a rebuild), the wizard is **offered again** with a clear message — still not forced.
- Settings always shows the wizard so you can reopen or mark complete anytime.

## Security notes

- Use a dedicated Proxmox API token with restore/start/stop/delete rights on test VMIDs
- Install the RestoreProof SSH public key only on nodes that need screenshots
- Use **hex** `SECRET_KEY` / `POSTGRES_PASSWORD` (see [PORTAINER.md](PORTAINER.md)); never leave `SECRET_KEY` empty
- Prefer a dedicated restore storage pool when possible
- Do not restart the worker while a restore is in progress
- After rotating `SECRET_KEY`, re-enter all Proxmox token secrets and SMTP passwords (or restore the old key)

## License

Apache License 2.0 — see [LICENSE](LICENSE)

Copyright 2026 Doug Hesseltine

## Forum blurb

> RestoreProof is a small Docker appliance that periodically restores your latest PBS backup to a throwaway VMID (NICs detached), screenshots the console, cleans up, and emails you. Original VMs stay online. Aimed at homelab and SMB Proxmox users who want proof—not just green backup jobs.
