# Install RestoreProof on an Ubuntu LXC (Proxmox)

**Author:** Doug Hesseltine  
**Created:** 2026-07-12  
**Modified:** 2026-07-12  
**Version:** 1.2.0

This guide deploys RestoreProof with Docker inside an Ubuntu LXC container on Proxmox VE.

Prefer **Portainer on a Docker host** instead? Use [PORTAINER.md](PORTAINER.md) and [`portainer-stack.yml`](portainer-stack.yml) (pulls Docker Hub images — no build).

## Secrets (read this first)

Generate **hex-only** values — never paste passwords containing `# @ : / ? % &` into YAML or env files:

```bash
openssl rand -hex 24   # POSTGRES_PASSWORD
openssl rand -hex 32   # SECRET_KEY (Portainer: API_SECRET_KEY = WORKER_SECRET_KEY)
```

See [PORTAINER.md](PORTAINER.md) for migration rules (same `SECRET_KEY` when importing config).

## 1. Create the LXC

Suggested resources:

| Resource | Suggestion |
|----------|------------|
| Template | Ubuntu 24.04 |
| CPU | 2+ |
| RAM | 2 GB+ |
| Disk | 16 GB+ (evidence + DB; restore disks live on the *Proxmox* storage, not here) |
| Nesting | **Enabled** (required for Docker) |

On the Proxmox host, ensure the container has features suitable for Docker, for example:

```bash
# On Proxmox node — adjust CTID
pct set <CTID> -features nesting=1,keyctl=1
pct reboot <CTID>
```

Some hosts also need AppArmor/fuse adjustments for Docker. If `docker run hello-world` fails inside the CT, see the [Proxmox wiki: nested containers / Docker](https://pve.proxmox.com/wiki/Linux_Container).

## 2. Install Docker inside the LXC

```bash
apt update && apt install -y ca-certificates curl git
curl -fsSL https://get.docker.com | sh
systemctl enable --now docker
```

## 3. Deploy RestoreProof

### Option A — Hub images (faster)

```bash
git clone https://github.com/hesseltined/RestoreProof.git
cd RestoreProof
cp .env.example .env
# Set SECRET_KEY=$(openssl rand -hex 32) and POSTGRES_PASSWORD=$(openssl rand -hex 24)
nano .env
docker compose -f portainer-stack.yml --env-file .env up -d
```

When using `portainer-stack.yml` with a `.env` file, also set:

```bash
API_SECRET_KEY=<same as SECRET_KEY>
WORKER_SECRET_KEY=<same as SECRET_KEY>
```

### Option B — Build from source

```bash
git clone https://github.com/hesseltined/RestoreProof.git
cd RestoreProof
cp .env.example .env
# Set SECRET_KEY and POSTGRES_PASSWORD to openssl rand -hex values
nano .env   # also APP_BASE_URL
docker compose up -d --build
```
Set `APP_BASE_URL` (and `CORS_ORIGINS`) to the URL you will use in the browser (e.g. `http://10.250.0.50:3080`) so password-reset links and CORS work.

## 4. Proxmox API token

On the Proxmox UI: **Datacenter → Permissions → API Tokens**.

1. Click **Add**
2. User: `root@pam` (or a dedicated user)
3. Token ID: e.g. `restoreproof` (short name only)
4. Leave **Privilege Separation** unchecked for a simple start
5. Copy the **secret** immediately — Proxmox shows it only once

In RestoreProof → **Hosts**, paste:

- **API token ID** as `user@realm!tokenid` (e.g. `root@pam!restoreproof`)
- **API token secret** from the create dialog

The Hosts page includes a **?** tip next to the token ID field with these steps.

Grant privileges needed to:

- List cluster resources / guests
- List PBS backup content
- Create/restore qemu & lxc
- Update config (delete `net*`)
- Start / stop / delete guests in the test VMID pool

Least privilege is preferred; many homelabs use a token with Administrator on the node for simplicity—tighten for production.

## 5. SSH key for screenshots and root-only restores

In RestoreProof → **Hosts** → **SSH key**.

Use **Copy** on the one-liner to install the key from your admin machine, or append the public key on the Proxmox node:

```bash
# On Proxmox node
mkdir -p /root/.ssh
echo 'ssh-ed25519 AAAA... restoreproof-host-1' >> /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys
```

Complete the host checklist: **1 · Test API** → **2 · Test SSH** → **3 · Sync guests**.

Use **Test SSH** in the UI before relying on:

- VM console screenshots
- VMs with USB/PCI host passthrough (API tokens cannot restore those)
- CTs with host **bind mounts** (`mp0` etc.) — Proxmox only allows root to restore bind mounts; RestoreProof falls back to `pct restore` over SSH

LXC evidence is status JSON (not VGA screenshots).

## 6. First drill

1. Open `http://<lxc-ip>:3080`
2. Create the admin account
3. Configure SMTP (optional but recommended)
4. Add host → Test API → Sync guests
5. On **Guests**, click **Run now** on a safe guest (you land on the Dashboard with live progress)
6. Review **Runs** for the screenshot / log when finished

## 7. Firewall / reverse proxy

- Expose only the web port (`3080`) to your admin network
- Optionally put Caddy/nginx TLS in front and set `APP_BASE_URL` / `CORS_ORIGINS` to `https://…`
- Do not publish Postgres externally

## Troubleshooting

| Symptom | Check |
|---------|--------|
| Docker fails in LXC | `nesting=1`, `keyctl=1`, AppArmor |
| API 401 | Token ID format `user@realm!tokenid` + secret |
| No PBS backups | Guest has PBS backup jobs; storage type `pbs` |
| Screenshot fails | SSH key installed; `qm monitor` works as root |
| Lock busy / progress stuck | Wait for current run; only one test at a time; Proxmox may not report % during disk transfer |
| Progress at ~75% forever (old builds) | Upgrade images — fake progress was capped; check Proxmox task log |

## Upgrading

```bash
cd RestoreProof
git pull
# Hub images:
docker compose -f portainer-stack.yml --env-file .env pull
docker compose -f portainer-stack.yml --env-file .env up -d
# Or source build (restarts worker — wait until idle):
docker compose up -d --build
```

Volumes `rp_pgdata` and `rp_data` preserve database and evidence.
