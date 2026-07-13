# Purpose: Developer notes — GitHub + Docker Hub workflow for RestoreProof
# Author: Doug Hesseltine
# Created: 2026-07-12
# Modified: 2026-07-12
# Version: 1.1.0

# Developing RestoreProof

## One-time auth (laptop)

### GitHub (`hesseltined`)

```bash
gh auth login -h github.com -p https -w
gh auth status
```

Repo remote:

```text
origin  https://github.com/hesseltined/RestoreProof.git
```

```bash
./scripts/setup-remotes.sh   # optional interactive helper
```

### Docker Hub (`hesseltined`)

```bash
docker login -u hesseltined
# Prefer an Access Token from hub.docker.com → Account Settings → Security
```

## Publish images (safe for a running restore)

`./scripts/push-images.sh` only **builds and pushes** Hub tags. It does **not** run `docker compose up`, so your local stack keeps running.

```bash
VERSION=1.1.0 ./scripts/push-images.sh
```

| Image | Tags |
|-------|------|
| `yesitsmedoug/restoreproof-api` | `latest`, `1.1.0`, … (API + worker) |
| `yesitsmedoug/restoreproof-web` | `latest`, `1.1.0`, … |

Consumers use [`portainer-stack.yml`](portainer-stack.yml) / [PORTAINER.md](PORTAINER.md).

Local `docker compose up --build` keeps using project-local image names (`proxmoxserver-*` or similar). Redeploying that stack **will** restart the worker — avoid mid-restore.

## Daily local loop

```bash
docker compose up -d --build   # only when no restore is active
open http://localhost:3080
docker compose logs -f api worker
```

UI: **3080** · API health: **http://localhost:8000/api/health**

## Docs map

| File | Audience |
|------|----------|
| [README.md](README.md) | Overview + quick links |
| [PORTAINER.md](PORTAINER.md) | Portainer / Hub-image deploy |
| [INSTALL-LXC.md](INSTALL-LXC.md) | Nested Docker in Proxmox LXC |
| [portainer-stack.yml](portainer-stack.yml) | Stack YAML for Portainer |
| [docker-compose.yml](docker-compose.yml) | Source-build compose |
