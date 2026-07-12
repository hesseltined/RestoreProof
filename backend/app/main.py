"""
Purpose: RestoreProof FastAPI application entrypoint.
Author: Doug Hesseltine
Created: 2026-07-12
Modified: 2026-07-12
Version: 1.1.0
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, guests, hosts, runs, settings
from app.config import get_settings
from app.database import Base, SessionLocal, engine, ensure_schema
from app.services.bootstrap import ensure_defaults

app = FastAPI(title="RestoreProof", version="1.1.0")

cfg = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=cfg.cors_origin_list or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(settings.router, prefix="/api")
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
    return {"status": "ok", "app": "RestoreProof", "version": "1.1.0"}
