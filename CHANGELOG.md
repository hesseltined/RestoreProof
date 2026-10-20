# Changelog

All notable RestoreProof releases. Keep in sync with `backend/app/version.py` and Docker Hub tags.

## 1.6.12 — 2026-10-20

### Nightly restore digest
- Show **backup age in days** on each digest row (and on default single-run email templates).
- Color: green ≤7 days, **orange** >7, **red** (CSS flash where clients allow) >14.
- Age is calendar days from the PBS/vzdump snapshot time in `backup_volid` (or `result_summary`) to restore finish.
- Template variables: `backup_age_days`, `backup_age_label`, `backup_age_html`.

### Backup health
- Detect disabled covering vzdump jobs and snapshots older than the job schedule.
- Daily email/ntfy alert while the problem persists (fingerprint + cooldown).
- Guests UI and dashboard surface current / stale / missing-job status.

### Guests and runs
- Store and display short **OS labels** from Proxmox `ostype` (Windows, Debian, Ubuntu, …).
- Keep `os_label` on restore history after renames.
- Demo fleet and evidence updated to match live-style inventory.

### Ship
- Images: `yesitsmedoug/restoreproof-api:1.6.12` / `latest`, `yesitsmedoug/restoreproof-web:1.6.12` / `latest` (`linux/amd64`).

## Earlier

See git history for v1.6.11 and below (`git log --oneline`).
