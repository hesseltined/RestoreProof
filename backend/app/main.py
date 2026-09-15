"""
Purpose: RestoreProof FastAPI application entrypoint.
Author: Doug Hesseltine
Created: 2026-07-12
Modified: 2026-09-15
Version: 1.6.2
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, config_transfer, guests, hosts, runs, settings
from app.config import get_settings
from app.database import Base, SessionLocal, engine, ensure_schema
from app.services.bootstrap import ensure_defaults
from app.services.secrets_guard import validate_runtime_secrets

APP_VERSION = "1.6.2"

app = FastAPI(title="RestoreProof", version=APP_VERSION)

cfg = get_settings()
validate_runtime_secrets(cfg, role="api")

app.add_middleware(
    CORSMiddleware,
    allow_origins=cfg.cors_origin_list or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(settings.router, prefix="/api")
app.include_router(config_transfer.router, prefix="/api")
app.include_router(hosts.router, prefix="/api")
app.include_router(guests.router, prefix="/api")
app.include_router(runs.router, prefix="/api")


@app.on_event("startup")
def on_startup() -> None:
    Path(cfg.data_dir).mkdir(parents=True, exist_ok=True)
    (Path(cfg.data_dir) / "evidence").mkdir(parents=True, exist_ok=True)
    (Path(cfg.data_dir) / "keys").mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    ensure_schema()
    db = SessionLocal()
    try:
        ensure_defaults(db)
    finally:
        db.close()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "app": "RestoreProof", "version": APP_VERSION}
