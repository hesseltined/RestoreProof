"""
Purpose: Default notification templates and proof sections for restore emails.
Author: Doug Hesseltine
Created: 2026-07-12
Modified: 2026-07-12
Version: 1.0.0
"""

from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.models import RestoreRun

DEFAULT_SUCCESS_SUBJECT = "✅ RestoreProof passed — {{guest_name}} (VMID {{vmid}})"
DEFAULT_FAILURE_SUBJECT = "❌ RestoreProof failed — {{guest_name}} (VMID {{vmid}})"

DEFAULT_SUCCESS_BODY = """<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#eef2f6;font-family:Segoe UI,Helvetica,Arial,sans-serif;">
  <div style="max-width:620px;margin:24px auto;background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 8px 32px rgba(15,28,46,0.1);">
    <div style="background:linear-gradient(135deg,#047857,#10b981);padding:28px 26px;color:#ffffff;">
      <div style="font-size:12px;opacity:0.9;letter-spacing:0.08em;text-transform:uppercase;">RestoreProof</div>
      <h1 style="margin:10px 0 0;font-size:26px;font-weight:700;line-height:1.3;">Backup restore verified ✓</h1>
    </div>
    <div style="padding:26px;color:#1e293b;line-height:1.65;font-size:15px;">
      <p style="margin-top:0;">Good news! <strong>{{guest_name}}</strong> (VMID <strong>{{vmid}}</strong>) restored from PBS, booted in a throwaway test guest, and passed our proof check.</p>
      <table style="width:100%;border-collapse:collapse;margin:18px 0;font-size:14px;">
        <tr><td style="padding:7px 0;color:#64748b;width:38%;">Guest type</td><td style="padding:7px 0;"><strong>{{guest_type_label}}</strong></td></tr>
        <tr><td style="padding:7px 0;color:#64748b;">Test VMID</td><td style="padding:7px 0;"><code style="background:#f1f5f9;padding:2px 6px;border-radius:4px;">{{test_vmid}}</code></td></tr>
        <tr><td style="padding:7px 0;color:#64748b;">Backup used</td><td style="padding:7px 0;font-size:13px;word-break:break-all;">{{backup_volid}}</td></tr>
        <tr><td style="padding:7px 0;color:#64748b;">Backups available</td><td style="padding:7px 0;">{{backup_count}}</td></tr>
        <tr><td style="padding:7px 0;color:#64748b;">Started</td><td style="padding:7px 0;">{{started_at}}</td></tr>
        <tr><td style="padding:7px 0;color:#64748b;">Finished</td><td style="padding:7px 0;">{{finished_at}}</td></tr>
      </table>
      {{proof_section}}
      <div style="margin:18px 0;padding:14px 16px;background:#f8fafc;border-radius:10px;border-left:4px solid #0f766e;font-size:13px;color:#475569;white-space:pre-wrap;">{{result_summary}}</div>
      <a href="{{run_url}}" style="display:inline-block;margin-top:8px;padding:13px 22px;background:#0f766e;color:#ffffff;text-decoration:none;border-radius:10px;font-weight:600;font-size:14px;">View full run →</a>
    </div>
    <div style="padding:16px 26px;background:#f8fafc;font-size:12px;color:#94a3b8;text-align:center;">
      Original guest stayed online · NICs detached on the test restore
    </div>
  </div>
</body>
</html>"""

DEFAULT_FAILURE_BODY = """<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#eef2f6;font-family:Segoe UI,Helvetica,Arial,sans-serif;">
  <div style="max-width:620px;margin:24px auto;background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 8px 32px rgba(15,28,46,0.1);">
    <div style="background:linear-gradient(135deg,#b91c1c,#ef4444);padding:28px 26px;color:#ffffff;">
      <div style="font-size:12px;opacity:0.9;letter-spacing:0.08em;text-transform:uppercase;">RestoreProof</div>
      <h1 style="margin:10px 0 0;font-size:26px;font-weight:700;line-height:1.3;">Restore test failed</h1>
    </div>
    <div style="padding:26px;color:#1e293b;line-height:1.65;font-size:15px;">
      <p style="margin-top:0;">RestoreProof could not verify <strong>{{guest_name}}</strong> (VMID <strong>{{vmid}}</strong>). Your production guest is untouched, but this backup may not be restorable.</p>
      <div style="margin:16px 0;padding:14px 16px;background:#fef2f2;border-radius:10px;border-left:4px solid #ef4444;font-size:14px;color:#991b1b;white-space:pre-wrap;">{{error_message}}</div>
      <table style="width:100%;border-collapse:collapse;margin:18px 0;font-size:14px;">
        <tr><td style="padding:7px 0;color:#64748b;width:38%;">Guest type</td><td style="padding:7px 0;"><strong>{{guest_type_label}}</strong></td></tr>
        <tr><td style="padding:7px 0;color:#64748b;">Backup tried</td><td style="padding:7px 0;font-size:13px;word-break:break-all;">{{backup_volid}}</td></tr>
        <tr><td style="padding:7px 0;color:#64748b;">Backups available</td><td style="padding:7px 0;">{{backup_count}}</td></tr>
        <tr><td style="padding:7px 0;color:#64748b;">Used older backup</td><td style="padding:7px 0;">{{used_fallback_backup}}</td></tr>
      </table>
      {{proof_section}}
      <div style="margin:18px 0;padding:14px 16px;background:#f8fafc;border-radius:10px;border-left:4px solid #b45309;font-size:13px;color:#475569;white-space:pre-wrap;">{{result_summary}}</div>
      <a href="{{run_url}}" style="display:inline-block;margin-top:8px;padding:13px 22px;background:#b91c1c;color:#ffffff;text-decoration:none;border-radius:10px;font-weight:600;font-size:14px;">View run details →</a>
    </div>
    <div style="padding:16px 26px;background:#f8fafc;font-size:12px;color:#94a3b8;text-align:center;">
      Check PBS verify state and run logs for next steps
    </div>
  </div>
</body>
</html>"""

LEGACY_SUCCESS_BODY = (
    "Restore test succeeded for {{guest_name}} (VMID {{vmid}}).\n"
    "{{result_summary}}\n"
    "Backup used: {{backup_volid}}\n"
    "Backups available: {{backup_count}}\n"
    "Test ID: {{test_vmid}}\n"
    "Started: {{started_at}}\nFinished: {{finished_at}}\n"
    "View: {{run_url}}\n"
)

LEGACY_FAILURE_BODY = (
    "Restore test FAILED for {{guest_name}} (VMID {{vmid}}).\n"
    "Error: {{error_message}}\n\n"
    "{{result_summary}}\n\n"
    "Backup tried: {{backup_volid}}\n"
    "Backups available: {{backup_count}}\n"
    "View: {{run_url}}\n"
)

LEGACY_SUCCESS_SUBJECT = "[RestoreProof] SUCCESS: {{guest_name}} ({{vmid}})"
LEGACY_FAILURE_SUBJECT = "[RestoreProof] FAILURE: {{guest_name}} ({{vmid}})"

INLINE_SCREENSHOT_CID = "restoreproof-screenshot"


def guest_type_label(guest_type: str) -> str:
    if guest_type == "lxc":
        return "LXC container"
    return "QEMU virtual machine"


def format_timestamp(value: Optional[datetime]) -> str:
    if not value:
        return "—"
    try:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).strftime("%b %d, %Y %H:%M UTC")
    except (TypeError, ValueError, OSError):
        return str(value)


def _format_uptime(seconds: Any) -> str:
    try:
        total = int(seconds)
    except (TypeError, ValueError):
        return str(seconds or "—")
    if total < 60:
        return f"{total}s"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m {secs}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"


def build_proof_section(run: RestoreRun) -> str:
    """HTML fragment embedded in notification templates via {{proof_section}}."""
    if run.status != "success":
        return (
            '<div style="margin:18px 0;padding:14px 16px;background:#fff7ed;border-radius:10px;'
            'border:1px solid #fed7aa;font-size:14px;color:#9a3412;">'
            "<strong>Proof not captured</strong> — the restore did not complete successfully."
            "</div>"
        )

    if run.evidence_kind == "screenshot":
        return (
            '<div style="margin:20px 0;padding:18px;background:#ecfdf5;border-radius:12px;'
            'border:1px solid #86efac;">'
            '<div style="font-size:13px;font-weight:700;color:#047857;margin-bottom:10px;'
            'letter-spacing:0.04em;text-transform:uppercase;">🖥️ VM console proof</div>'
            '<p style="margin:0 0 12px;font-size:14px;color:#166534;">'
            "Console screenshot from the restored test VM (attached inline below)."
            "</p>"
            '<img src="cid:restoreproof-screenshot" alt="VM console screenshot" '
            'style="max-width:100%;height:auto;border-radius:8px;border:1px solid #d1d5db;display:block;" />'
            "</div>"
        )

    if run.evidence_kind == "container_proof":
        proof: dict[str, Any] = {}
        if run.evidence_json:
            try:
                proof = json.loads(run.evidence_json)
            except json.JSONDecodeError:
                proof = {}
        status = html.escape(str(proof.get("status") or "unknown"))
        uptime = html.escape(_format_uptime(proof.get("uptime")))
        name = html.escape(str(proof.get("name") or run.source_name))
        captured = html.escape(str(proof.get("captured_at") or format_timestamp(run.finished_at)))
        status_color = "#15803d" if str(status).lower() == "running" else "#b45309"
        return (
            '<div style="margin:20px 0;padding:18px;background:#eff6ff;border-radius:12px;'
            'border:1px solid #93c5fd;">'
            '<div style="font-size:13px;font-weight:700;color:#1d4ed8;margin-bottom:10px;'
            'letter-spacing:0.04em;text-transform:uppercase;">📦 Container proof</div>'
            '<p style="margin:0 0 14px;font-size:14px;color:#1e40af;">'
            "LXC containers have no VGA console — proof is the restored container status after boot."
            "</p>"
            '<table style="width:100%;border-collapse:collapse;font-size:14px;">'
            f'<tr><td style="padding:6px 0;color:#64748b;width:34%;">Name</td>'
            f'<td style="padding:6px 0;"><strong>{name}</strong></td></tr>'
            f'<tr><td style="padding:6px 0;color:#64748b;">Status</td>'
            f'<td style="padding:6px 0;"><strong style="color:{status_color};">{status}</strong></td></tr>'
            f'<tr><td style="padding:6px 0;color:#64748b;">Uptime</td>'
            f'<td style="padding:6px 0;"><strong>{uptime}</strong></td></tr>'
            f'<tr><td style="padding:6px 0;color:#64748b;">Captured</td>'
            f'<td style="padding:6px 0;">{captured}</td></tr>'
            "</table></div>"
        )

    return (
        '<div style="margin:18px 0;padding:14px 16px;background:#f8fafc;border-radius:10px;'
        'border:1px solid #e2e8f0;font-size:14px;color:#64748b;">'
        "<strong>No proof file</strong> — restore succeeded but no evidence was saved for this run."
        "</div>"
    )


def screenshot_attachment(run: RestoreRun) -> Optional[tuple[str, bytes, str]]:
    """Return (cid, bytes, subtype) when a VM screenshot should be inlined."""
    if run.status != "success" or run.evidence_kind != "screenshot" or not run.evidence_path:
        return None
    path = Path(run.evidence_path)
    if not path.exists() or path.suffix.lower() != ".png":
        return None
    return INLINE_SCREENSHOT_CID, path.read_bytes(), "png"


def build_notification_context(run: RestoreRun, app_url: str) -> dict[str, Any]:
    proof_section = build_proof_section(run)
    return {
        "guest_name": run.source_name,
        "vmid": run.source_vmid,
        "guest_type": run.guest_type,
        "guest_type_label": guest_type_label(run.guest_type),
        "test_vmid": run.test_vmid or "",
        "backup_volid": run.backup_volid,
        "backup_count": run.backup_count if run.backup_count is not None else "",
        "backup_used_index": run.backup_used_index if run.backup_used_index is not None else "",
        "latest_backup_volid": run.latest_backup_volid or "",
        "used_fallback_backup": "yes" if run.used_fallback_backup else "no",
        "result_summary": run.result_summary or "",
        "error_message": run.error_message or "",
        "started_at": format_timestamp(run.started_at),
        "finished_at": format_timestamp(run.finished_at),
        "run_url": f"{app_url.rstrip('/')}/runs/{run.id}",
        "status": run.status,
        "evidence_kind": run.evidence_kind or "none",
        "proof_section": proof_section,
    }


def html_to_plain(html: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    text = re.sub(r"</p>", "\n\n", text, flags=re.I)
    text = re.sub(r"</tr>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def apply_default_templates(settings: Any) -> None:
    settings.email_success_subject = DEFAULT_SUCCESS_SUBJECT
    settings.email_failure_subject = DEFAULT_FAILURE_SUBJECT
    settings.email_success_body = DEFAULT_SUCCESS_BODY
    settings.email_failure_body = DEFAULT_FAILURE_BODY


def is_legacy_template(settings: Any) -> bool:
    return (
        settings.email_success_body.strip() == LEGACY_SUCCESS_BODY.strip()
        or settings.email_failure_body.strip() == LEGACY_FAILURE_BODY.strip()
        or (
            "<html" not in settings.email_success_body.lower()
            and settings.email_success_subject.strip() == LEGACY_SUCCESS_SUBJECT
        )
    )
