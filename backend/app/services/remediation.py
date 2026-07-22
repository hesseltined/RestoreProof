"""
Purpose: Detect when a failed restore was remediated by a later success.
Author: Doug Hesseltine
Created: 2026-07-22
Modified: 2026-07-22
Version: 1.0.0
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import RestoreRun
from app.schemas import RunOut

# Failures older than this (from now) never show the remediations mark.
REMEDIATE_LOOKBACK_DAYS = 7
# Success must land within this window after the failure.
REMEDIATE_AFTER_FAIL_DAYS = 7


def remediation_for_runs(db: Session, runs: list[RestoreRun]) -> dict[int, int]:
    """
    For recent failed runs, map run_id → later success run_id when the same guest
    (or host+vmid) succeeded within REMEDIATE_AFTER_FAIL_DAYS of the failure.
    Only considers failures from the last REMEDIATE_LOOKBACK_DAYS.
    """
    now = datetime.now(timezone.utc)
    lookback = now - timedelta(days=REMEDIATE_LOOKBACK_DAYS)
    after_fail = timedelta(days=REMEDIATE_AFTER_FAIL_DAYS)
    out: dict[int, int] = {}
    for run in runs:
        if run.status != "failed":
            continue
        created = run.created_at
        if created is None:
            continue
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if created < lookback:
            continue
        deadline = created + after_fail
        q = db.query(RestoreRun).filter(
            RestoreRun.status == "success",
            RestoreRun.created_at > created,
            RestoreRun.created_at <= deadline,
            RestoreRun.id != run.id,
        )
        if run.guest_id is not None:
            q = q.filter(RestoreRun.guest_id == run.guest_id)
        else:
            q = q.filter(
                RestoreRun.source_vmid == run.source_vmid,
                RestoreRun.host_id == run.host_id,
            )
        later = q.order_by(RestoreRun.created_at.asc(), RestoreRun.id.asc()).first()
        if later:
            out[run.id] = later.id
    return out


def run_out_with_remediation(run: RestoreRun, remediated_by: dict[int, int]) -> RunOut:
    data = RunOut.model_validate(run)
    success_id = remediated_by.get(run.id)
    if success_id:
        data.remediated = True
        data.remediated_by_run_id = success_id
    return data
