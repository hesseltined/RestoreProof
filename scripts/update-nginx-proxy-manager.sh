#!/usr/bin/env bash
# Purpose: Update Nginx Proxy Manager on a Proxmox helper-script LXC
# Author: Doug Hesseltine
# Created: 2026-07-12
# Modified: 2026-07-12
# Version: 1.0.0
#
# Prefer the community-scripts built-in updater when present.
# Fallback: re-run the official nginxproxymanager.sh installer (update mode).
#
# Usage (as root inside the NPM LXC):
#   chmod +x update-nginx-proxy-manager.sh
#   ./update-nginx-proxy-manager.sh

set -euo pipefail

SCRIPT_VERSION="1.0.0"
COMMUNITY_UPDATE_URL="https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/ct/nginxproxymanager.sh"

log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
die() { log "ERROR: $*"; exit 1; }

require_root() {
  [[ "${EUID}" -eq 0 ]] || die "Run as root inside the NPM LXC."
}

confirm_continue() {
  cat <<'EOF'

Before updating Nginx Proxy Manager:
  1. Take a Proxmox snapshot (or backup) of this LXC.
  2. Expect a short outage while OpenResty / NPM restart.
  3. If this LXC was created by community-scripts / tteck helpers,
     the preferred method is the built-in `update` command.

EOF
  read -r -p "Snapshot/backup done and ready to update? [y/N] " ans
  [[ "${ans}" =~ ^[Yy]$ ]] || die "Aborted by user."
}

show_current_hints() {
  log "Script version: ${SCRIPT_VERSION}"
  if command -v nginx >/dev/null 2>&1; then
    log "nginx binary: $(command -v nginx)"
  fi
  if [[ -f /opt/nginx-proxy-manager/package.json ]]; then
    log "NPM package.json version: $(grep -m1 '"version"' /opt/nginx-proxy-manager/package.json | head -1 || true)"
  elif [[ -f /app/package.json ]]; then
    log "NPM package.json version: $(grep -m1 '"version"' /app/package.json | head -1 || true)"
  fi
  systemctl is-active --quiet npm 2>/dev/null && log "npm.service: active" || true
  systemctl is-active --quiet openresty 2>/dev/null && log "openresty.service: active" || true
}

try_builtin_update() {
  # community-scripts usually installs an `update` shell function/alias in the LXC.
  if type update >/dev/null 2>&1; then
    log "Found built-in helper-script updater (`update`). Running it..."
    update
    return 0
  fi

  # Some installs expose update via /usr/bin/update or a profile snippet.
  if [[ -x /usr/bin/update ]]; then
    log "Found /usr/bin/update. Running it..."
    /usr/bin/update
    return 0
  fi

  return 1
}

run_community_script_update() {
  log "Built-in updater not found. Re-running community-scripts installer (update mode)..."
  command -v curl >/dev/null 2>&1 || die "curl is required."
  bash -c "$(curl -fsSL "${COMMUNITY_UPDATE_URL}")"
}

post_checks() {
  log "Post-update service check..."
  if systemctl list-unit-files | grep -q '^npm\.service'; then
    systemctl is-active --quiet npm && log "npm.service is active" || log "WARN: npm.service is not active"
  fi
  if systemctl list-unit-files | grep -q '^openresty\.service'; then
    if systemctl is-masked --quiet openresty; then
      log "WARN: openresty.service is masked. Try: systemctl unmask openresty && systemctl restart openresty"
    else
      systemctl is-active --quiet openresty && log "openresty.service is active" || log "WARN: openresty.service is not active"
    fi
  fi
  log "Done. Open the NPM UI (:81) and confirm the new version banner is gone."
}

main() {
  require_root
  confirm_continue
  show_current_hints

  if try_builtin_update; then
    post_checks
    exit 0
  fi

  run_community_script_update
  post_checks
}

main "$@"
