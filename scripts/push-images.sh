#!/usr/bin/env bash
# Purpose: Build and push RestoreProof images to Docker Hub (yesitsmedoug)
# Author: Doug Hesseltine
# Created: 2026-07-12
# Modified: 2026-07-12
# Version: 1.2.0
#
# Builds and pushes only — does NOT run docker compose up / restart local containers.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

VERSION="${VERSION:-1.2.1}"
REGISTRY_USER="${DOCKERHUB_USER:-yesitsmedoug}"
IMAGE_API="${REGISTRY_USER}/restoreproof-api"
IMAGE_WEB="${REGISTRY_USER}/restoreproof-web"

if ! docker info >/dev/null 2>&1; then
  echo "Docker engine not running."
  exit 1
fi

echo "Building api/worker image → ${IMAGE_API}:${VERSION} (and :latest)"
echo "(This does not restart your local compose stack.)"
docker build -t "${IMAGE_API}:${VERSION}" -t "${IMAGE_API}:latest" ./backend

echo "Building web image → ${IMAGE_WEB}:${VERSION} (and :latest)"
docker build -t "${IMAGE_WEB}:${VERSION}" -t "${IMAGE_WEB}:latest" ./web

echo "Pushing to Docker Hub..."
docker push "${IMAGE_API}:${VERSION}"
docker push "${IMAGE_API}:latest"
docker push "${IMAGE_WEB}:${VERSION}"
docker push "${IMAGE_WEB}:latest"

echo "Done."
echo "  ${IMAGE_API}:${VERSION} / latest"
echo "  ${IMAGE_WEB}:${VERSION} / latest"
echo "Portainer stack: portainer-stack.yml  (see PORTAINER.md)"
