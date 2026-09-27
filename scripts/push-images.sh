#!/usr/bin/env bash
# Purpose: Build and push RestoreProof images to Docker Hub (yesitsmedoug)
# Author: Doug Hesseltine
# Created: 2026-07-12
# Modified: 2026-09-27
# Version: 1.6.6
#
# Builds linux/amd64 (Portainer / Proxmox Docker hosts) and pushes.
# Does NOT run docker compose up / restart local containers.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

VERSION="${VERSION:-1.6.6}"
PLATFORM="${PLATFORM:-linux/amd64}"
REGISTRY_USER="${DOCKERHUB_USER:-yesitsmedoug}"
IMAGE_API="${REGISTRY_USER}/restoreproof-api"
IMAGE_WEB="${REGISTRY_USER}/restoreproof-web"

if ! docker info >/dev/null 2>&1; then
  echo "Docker engine not running."
  exit 1
fi

echo "Building api/worker → ${IMAGE_API}:${VERSION} + :latest (${PLATFORM})"
echo "(This does not restart your local compose stack.)"
docker buildx build \
  --platform "${PLATFORM}" \
  -t "${IMAGE_API}:${VERSION}" \
  -t "${IMAGE_API}:latest" \
  --push \
  ./backend

echo "Building web → ${IMAGE_WEB}:${VERSION} + :latest (${PLATFORM})"
docker buildx build \
  --platform "${PLATFORM}" \
  -t "${IMAGE_WEB}:${VERSION}" \
  -t "${IMAGE_WEB}:latest" \
  --push \
  ./web

echo "Done."
echo "  ${IMAGE_API}:${VERSION} / latest  (${PLATFORM})"
echo "  ${IMAGE_WEB}:${VERSION} / latest  (${PLATFORM})"
echo "Portainer stack: portainer-stack.yml  (see PORTAINER.md)"
echo "GitHub tag so in-app update checks see this version:"
echo "  git tag v${VERSION} && git push origin v${VERSION}"
