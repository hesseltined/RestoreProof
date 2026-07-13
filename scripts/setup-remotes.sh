# Purpose: One-time GitHub + Docker Hub setup for RestoreProof
# Author: Doug Hesseltine
# Created: 2026-07-12
# Modified: 2026-07-12
# Version: 1.0.0
#
# Run from the project root after Docker Desktop is running.
# Does NOT store passwords — uses interactive login where needed.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> Git remotes"
if ! git rev-parse --git-dir >/dev/null 2>&1; then
  git init -b main
fi

if ! git remote get-url origin >/dev/null 2>&1; then
  git remote add origin https://github.com/hesseltined/RestoreProof.git
  echo "Added origin → https://github.com/hesseltined/RestoreProof.git"
else
  echo "origin already set: $(git remote get-url origin)"
fi

echo ""
echo "==> GitHub CLI (hesseltined)"
if ! gh auth status -h github.com >/dev/null 2>&1; then
  echo "GitHub token missing or invalid. Starting login..."
  gh auth login -h github.com -p https -w
else
  gh auth status -h github.com
fi

echo ""
echo "==> Ensure GitHub repo exists (create if missing)"
if ! gh repo view hesseltined/RestoreProof >/dev/null 2>&1; then
  echo "Creating public repo hesseltined/RestoreProof..."
  gh repo create hesseltined/RestoreProof --public --source=. --remote=origin --description "Automated Proxmox PBS restore drills with console proof" || true
  # If remote already existed, create without --source
  if ! gh repo view hesseltined/RestoreProof >/dev/null 2>&1; then
    gh repo create hesseltined/RestoreProof --public --description "Automated Proxmox PBS restore drills with console proof"
  fi
else
  echo "Repo already exists on GitHub."
fi

echo ""
echo "==> Docker Hub login (hesseltined)"
if ! docker info >/dev/null 2>&1; then
  echo "ERROR: Docker engine is not running. Start Docker Desktop and re-run."
  exit 1
fi

echo "Logging into Docker Hub as hesseltined (browser or token prompt)..."
docker login -u hesseltined

echo ""
echo "Setup complete."
echo "  git push -u origin main   # after your first commit"
echo "  ./scripts/push-images.sh # build & push yesitsmedoug/restoreproof tags"
