"""
Purpose: Compare the running RestoreProof version to GitHub releases/tags and Docker Hub.
Author: Doug Hesseltine
Created: 2026-09-17
Modified: 2026-09-17
Version: 1.0.0
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AppSettings
from app.services.bootstrap import get_app_settings
from app.version import APP_VERSION

logger = logging.getLogger(__name__)

CACHE_HOURS = 6
REQUEST_TIMEOUT = 8.0
_SKIP_TAGS = {"latest", "nightly", "dev", "edge", "stable"}
_VERSION_RE = re.compile(r"^v?(?P<core>\d+(?:\.\d+){0,3})(?P<rest>.*)$", re.I)

COMPOSE_UPGRADE = (
    "docker compose -f portainer-stack.yml pull\n"
    "docker compose -f portainer-stack.yml up -d"
)
PORTAINER_UPGRADE = (
    "Open Portainer → Stacks → restoreproof → Pull and redeploy. "
    "Wait until no restore is running."
)
GIT_UPGRADE = "git pull && docker compose up -d --build"


class UpdateProbe:
    def __init__(
        self,
        version: str,
        url: str,
        notes: str = "",
        source: str = "",
    ):
        self.version = version
        self.url = url
        self.notes = notes
        self.source = source


def normalize_version(raw: str) -> str:
    text = (raw or "").strip()
    match = _VERSION_RE.match(text)
    if not match:
        return ""
    core = match.group("core")
    rest = match.group("rest") or ""
    if rest and not rest.startswith("-"):
        # "1.6.4-amd64" etc. — keep the numeric core only
        return core
    return f"{core}{rest}"


def version_tuple(raw: str) -> tuple[int, ...]:
    core = normalize_version(raw).split("-", 1)[0]
    parts: list[int] = []
    for bit in core.split("."):
        if bit.isdigit():
            parts.append(int(bit))
        else:
            break
    return tuple(parts) if parts else (0,)


def is_newer(candidate: str, current: str) -> bool:
    a = version_tuple(candidate)
    b = version_tuple(current)
    n = max(len(a), len(b))
    a = a + (0,) * (n - len(a))
    b = b + (0,) * (n - len(b))
    return a > b


def _usable_tag(name: str) -> str:
    raw = (name or "").strip()
    if not raw or raw.lower() in _SKIP_TAGS:
        return ""
    if any(ch.isalpha() for ch in raw.replace("v", "", 1).replace(".", "").replace("-", "")):
        # Skip "latest-1", "main", commit-ish tags
        if not _VERSION_RE.match(raw):
            return ""
    return normalize_version(raw)


def _headers() -> dict[str, str]:
    return {
        "User-Agent": f"RestoreProof/{APP_VERSION}",
        "Accept": "application/vnd.github+json, application/json",
    }


def _get_json(url: str) -> Any:
    with httpx.Client(timeout=REQUEST_TIMEOUT, headers=_headers(), follow_redirects=True) as client:
        resp = client.get(url)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()


def fetch_github_latest(repo: str) -> Optional[UpdateProbe]:
    repo = repo.strip()
    if not repo or "/" not in repo:
        return None
    found: list[UpdateProbe] = []
    release = None
    try:
        release = _get_json(f"https://api.github.com/repos/{repo}/releases/latest")
    except Exception:  # noqa: BLE001
        logger.warning("GitHub latest-release lookup failed for %s", repo, exc_info=True)
    if isinstance(release, dict) and not release.get("draft") and not release.get("prerelease"):
        ver = _usable_tag(str(release.get("tag_name") or ""))
        if ver:
            notes = str(release.get("body") or "").strip()
            found.append(
                UpdateProbe(
                    version=ver,
                    url=str(release.get("html_url") or f"https://github.com/{repo}/releases"),
                    notes=notes[:800],
                    source="github",
                )
            )
    try:
        tags = _get_json(f"https://api.github.com/repos/{repo}/tags?per_page=30")
    except Exception:  # noqa: BLE001
        logger.warning("GitHub tags lookup failed for %s", repo, exc_info=True)
        tags = None
    if isinstance(tags, list):
        for tag in tags:
            if not isinstance(tag, dict):
                continue
            ver = _usable_tag(str(tag.get("name") or ""))
            if not ver:
                continue
            found.append(
                UpdateProbe(
                    version=ver,
                    url=f"https://github.com/{repo}/releases/tag/v{ver}",
                    notes="",
                    source="github",
                )
            )
    return _newest(found)


def fetch_dockerhub_latest(image: str) -> Optional[UpdateProbe]:
    image = image.strip().strip("/")
    if not image or "/" not in image:
        return None
    url = f"https://hub.docker.com/v2/repositories/{image}/tags?page_size=50&ordering=-last_updated"
    try:
        payload = _get_json(url)
    except Exception:  # noqa: BLE001
        logger.warning("Docker Hub tags lookup failed for %s", image, exc_info=True)
        return None
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        return None
    found: list[UpdateProbe] = []
    for row in results:
        if not isinstance(row, dict):
            continue
        ver = _usable_tag(str(row.get("name") or ""))
        if not ver:
            continue
        found.append(
            UpdateProbe(
                version=ver,
                url=f"https://hub.docker.com/r/{image}/tags",
                notes="",
                source="dockerhub",
            )
        )
    return _newest(found)


def _newest(probes: list[UpdateProbe]) -> Optional[UpdateProbe]:
    best: Optional[UpdateProbe] = None
    for probe in probes:
        if best is None or is_newer(probe.version, best.version):
            best = probe
        elif (
            best
            and version_tuple(probe.version) == version_tuple(best.version)
            and probe.notes
            and not best.notes
        ):
            best = probe
    return best


def discover_latest() -> Optional[UpdateProbe]:
    cfg = get_settings()
    github = fetch_github_latest(cfg.github_repo)
    hub = fetch_dockerhub_latest(cfg.dockerhub_image)
    return _newest([p for p in (github, hub) if p])


def cache_is_fresh(settings: AppSettings, *, now: Optional[datetime] = None) -> bool:
    last = settings.update_last_checked_at
    if last is None:
        return False
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return now - last < timedelta(hours=CACHE_HOURS)


def refresh_update_cache(db: Session, settings: AppSettings) -> AppSettings:
    probe = discover_latest()
    settings.update_last_checked_at = datetime.now(timezone.utc)
    if probe:
        settings.update_latest_version = probe.version
        settings.update_latest_url = probe.url
        settings.update_latest_notes = probe.notes
        settings.update_latest_source = probe.source
    db.add(settings)
    db.commit()
    db.refresh(settings)
    return settings


def status_payload(
    settings: AppSettings,
    *,
    error: Optional[str] = None,
) -> dict[str, Any]:
    current = APP_VERSION
    latest = (settings.update_latest_version or "").strip()
    available = bool(latest) and is_newer(latest, current)
    dismissed = (settings.update_dismissed_version or "").strip() == latest and available
    return {
        "current_version": current,
        "latest_version": latest or None,
        "update_available": available,
        "dismissed": dismissed,
        "release_url": settings.update_latest_url or None,
        "notes": settings.update_latest_notes or "",
        "source": settings.update_latest_source or None,
        "last_checked_at": settings.update_last_checked_at,
        "check_enabled": bool(getattr(settings, "update_check_enabled", True)),
        "upgrade": {
            "portainer": PORTAINER_UPGRADE,
            "compose": COMPOSE_UPGRADE,
            "git": GIT_UPGRADE,
        },
        "error": error,
    }


def get_update_status(
    db: Session,
    settings: AppSettings,
    *,
    refresh: bool = False,
) -> dict[str, Any]:
    if not getattr(settings, "update_check_enabled", True):
        payload = status_payload(settings)
        payload["update_available"] = False
        return payload
    error = None
    if refresh or not cache_is_fresh(settings):
        try:
            settings = refresh_update_cache(db, settings)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Update check failed: %s", exc)
            error = "Could not reach GitHub or Docker Hub."
            settings.update_last_checked_at = datetime.now(timezone.utc)
            db.add(settings)
            db.commit()
    return status_payload(settings, error=error)


def maybe_refresh_update_cache(db: Session) -> None:
    settings = get_app_settings(db)
    if not getattr(settings, "update_check_enabled", True):
        return
    if cache_is_fresh(settings):
        return
    try:
        refresh_update_cache(db, settings)
    except Exception:  # noqa: BLE001
        logger.warning("Background update check failed", exc_info=True)
