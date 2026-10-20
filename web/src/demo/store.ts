/**
 * Purpose: In-memory sample fleet for the public RestoreProof /demo walkthrough.
 * Author: Doug Hesseltine
 * Created: 2026-07-13
 * Modified: 2026-10-19
 * Version: 2.9.0
 *
 * Datacenter servers only (Windows VMs, Linux VMs, and a few containers).
 * Run history is synthetic so the walkthrough has evidence to open.
 */

import { LIVE_BACKUP_SUMMARY, LIVE_GUESTS } from "./liveFleet";
import { assessBackup, fleetBackupHealth } from "../backupHealth";

export type DemoUser = {
  id: number;
  email: string;
  is_active: boolean;
  is_admin: boolean;
  totp_enabled: boolean;
};

export type DemoGuest = {
  id: number;
  host_id: number;
  host_name: string;
  vmid: number;
  name: string;
  guest_type: string;
  os_label: string;
  node: string;
  status: string;
  cpu_cores: number | null;
  memory_bytes: number | null;
  disk_bytes: number | null;
  excluded: boolean;
  in_backup_job: boolean;
  backup_job_enabled: boolean;
  backup_job_summary: string;
  backup_schedule: string;
  backup_snapshot_count: number;
  last_backup_at: string | null;
  schedule_cron: string | null;
  schedule_enabled: boolean;
  last_tested_at: string | null;
  next_due_at: string | null;
};

export type DemoRun = {
  id: number;
  guest_id: number | null;
  host_id: number | null;
  source_vmid: number;
  source_name: string;
  guest_type: string;
  os_label: string;
  test_vmid: number | null;
  backup_volid: string;
  backup_count: number | null;
  backup_used_index: number | null;
  latest_backup_volid: string;
  used_fallback_backup: boolean;
  backups_attempted: number;
  result_summary: string;
  status: string;
  trigger: string;
  progress_pct: number | null;
  progress_label: string | null;
  proxmox_upid: string | null;
  proxmox_node: string | null;
  error_message: string | null;
  evidence_path: string | null;
  evidence_kind: string;
  evidence_json: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  log_text: string;
  remediated?: boolean;
  remediated_by_run_id?: number | null;
};

export type DemoHost = {
  id: number;
  name: string;
  api_url: string;
  token_id: string;
  verify_ssl: boolean;
  ssh_host: string;
  ssh_port: number;
  ssh_user: string;
  ssh_private_key_path: string;
  preferred_restore_storage: string;
  test_vmid_start: number;
  test_vmid_end: number;
  enabled: boolean;
  last_sync_at: string | null;
  api_ok_at: string | null;
  ssh_ok_at: string | null;
  last_error: string | null;
  has_token_secret: boolean;
  has_ssh_key: boolean;
};

export type DemoSettings = {
  branding_title: string;
  boot_wait_seconds: number;
  retention_days: number;
  retention_max_runs: number;
  global_cron: string;
  schedule_enabled: boolean;
  schedule_batch_size: number;
  schedule_coverage_goal: string;
  enforce_2fa: boolean;
  setup_completed: boolean;
  notify_on_success: boolean;
  notify_on_failure: boolean;
  notify_to: string;
  notify_cc: string;
  public_base_url: string;
  gap_alert_enabled: boolean;
  gap_alert_hours: number;
  gap_alert_last_sent_at: string | null;
  unbacked_nudge_enabled: boolean;
  unbacked_nudge_last_sent_at: string | null;
  email_success_subject: string;
  email_failure_subject: string;
  email_success_body: string;
  email_failure_body: string;
};

export type DemoSmtp = {
  provider: string;
  host: string;
  port: number;
  use_tls: boolean;
  use_ssl: boolean;
  username: string;
  from_email: string;
  from_name: string;
  password_set: boolean;
  smtp_ok_at: string | null;
};

export type DemoHeartbeat = {
  enabled: boolean;
  url: string;
  interval_seconds: number;
  verify_ssl: boolean;
  last_ping_at: string | null;
  last_error: string;
};

export type DemoPush = {
  enabled: boolean;
  provider: string;
  url: string;
  verify_ssl: boolean;
  on_success: boolean;
  on_failure: boolean;
  token_set: boolean;
  push_ok_at: string | null;
};

const GiB = 1024 ** 3;
const MiB = 1024 ** 2;
const HISTORY_DAYS = 90;
const REMEDIATE_LOOKBACK_MS = 7 * 86400_000;
const REMEDIATE_AFTER_FAIL_MS = 7 * 86400_000;

const SUCCESS_BODY = `<!DOCTYPE html><html><body style="font-family:sans-serif;padding:24px;">
  <h1 style="color:#047857;">Backup restore verified ✓</h1>
  <p><strong>{{guest_name}}</strong> (VMID {{vmid}}) restored from PBS and passed proof.</p>
  {{proof_section}}
</body></html>`;

const FAILURE_BODY = `<!DOCTYPE html><html><body style="font-family:sans-serif;padding:24px;">
  <h1 style="color:#b91c1c;">Restore test failed</h1>
  <p>{{error_message}}</p>
  {{proof_section}}
</body></html>`;

export const DEMO_SMTP_PRESETS = [
  {
    id: "generic",
    label: "Generic SMTP",
    host: "",
    port: 587,
    use_tls: true,
    use_ssl: false,
    fields: ["host", "port", "use_tls", "use_ssl", "username", "password", "from_email", "from_name"],
    help: "Enter any SMTP server settings manually.",
  },
  {
    id: "microsoft365",
    label: "Microsoft 365 / Outlook",
    host: "smtp.office365.com",
    port: 587,
    use_tls: true,
    use_ssl: false,
    fields: ["username", "password", "from_email", "from_name"],
    help: "Use a mailbox or SMTP AUTH-enabled account. Username is usually the full email.",
  },
  {
    id: "smtp2go",
    label: "SMTP2GO",
    host: "mail.smtp2go.com",
    port: 587,
    use_tls: true,
    use_ssl: false,
    fields: ["username", "password", "from_email", "from_name"],
    help: "Username/password come from the SMTP2GO dashboard (SMTP Users).",
  },
  {
    id: "zoho",
    label: "Zoho Mail",
    host: "smtp.zoho.com",
    port: 587,
    use_tls: true,
    use_ssl: false,
    fields: ["username", "password", "from_email", "from_name"],
    help: "For Zoho EU use smtp.zoho.eu. Enable app-specific password if MFA is on.",
  },
  {
    id: "gmail",
    label: "Gmail (App Password)",
    host: "smtp.gmail.com",
    port: 587,
    use_tls: true,
    use_ssl: false,
    fields: ["username", "password", "from_email", "from_name"],
    help: "Use a Google App Password (not your normal Gmail password).",
  },
  {
    id: "sendgrid",
    label: "SendGrid SMTP",
    host: "smtp.sendgrid.net",
    port: 587,
    use_tls: true,
    use_ssl: false,
    fields: ["password", "from_email", "from_name"],
    help: "Username is always 'apikey'. Paste the API key as the password.",
    username: "apikey",
  },
  {
    id: "mailgun",
    label: "Mailgun SMTP",
    host: "smtp.mailgun.org",
    port: 587,
    use_tls: true,
    use_ssl: false,
    fields: ["username", "password", "from_email", "from_name"],
    help: "Use SMTP credentials from the Mailgun domain settings.",
  },
  {
    id: "amazon_ses",
    label: "Amazon SES SMTP",
    host: "email-smtp.us-east-1.amazonaws.com",
    port: 587,
    use_tls: true,
    use_ssl: false,
    fields: ["host", "username", "password", "from_email", "from_name"],
    help: "Set host to your SES region endpoint. Use SMTP credentials (not IAM access keys).",
  },
];

/** Deterministic PRNG so the demo fleet is stable across reloads. */
function mulberry32(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function pick<T>(rand: () => number, items: T[]): T {
  return items[Math.floor(rand() * items.length)];
}

function intBetween(rand: () => number, min: number, max: number): number {
  return min + Math.floor(rand() * (max - min + 1));
}

function hoursAgo(h: number): string {
  return new Date(Date.now() - h * 3600_000).toISOString();
}

function daysAgo(d: number): string {
  return new Date(Date.now() - d * 86400_000).toISOString();
}

function hoursFromNow(h: number): string {
  return new Date(Date.now() + h * 3600_000).toISOString();
}

/** Current means the job is enabled and the newest snapshot is inside its schedule. */
export function isRestorable(g: DemoGuest): boolean {
  return assessBackup(g).status === "current";
}

function isoAt(ms: number): string {
  return new Date(ms).toISOString();
}

const FAIL_MESSAGES = [
  "Boot wait expired — no console activity within 90s",
  "PBS snapshot integrity check failed on latest index",
  "Insufficient free space on restore-test storage",
  "QEMU guest agent never responded after start",
  "Temporary lock on PBS datastore (busy)",
  "Restore aborted: test VMID range exhausted",
];

function makeRun(opts: {
  id: number;
  guest: DemoGuest;
  createdMs: number;
  status: "success" | "failed";
  trigger: "schedule" | "manual" | "retry";
  rand: () => number;
}): DemoRun {
  const { id, guest, createdMs, status, trigger, rand } = opts;
  const durationMin = 8 + Math.floor(rand() * 25);
  const startedMs = createdMs;
  const finishedMs = createdMs + durationMin * 60_000;
  const kind = guest.guest_type === "lxc" ? "ct" : "vm";
  const backupIso = isoAt(createdMs - (1 + Math.floor(rand() * 36)) * 3600_000);
  const backup_volid = `pbs:backup/${kind}/${guest.vmid}/${backupIso}`;
  const backup_count = intBetween(rand, 6, 28);
  const usedFallback = status === "success" && rand() < 0.08;
  const backup_used_index = usedFallback ? intBetween(rand, 2, Math.min(4, backup_count)) : 1;
  const test_vmid = 9000 + (id % 90);
  const failMsg = pick(rand, FAIL_MESSAGES);

  if (status === "failed") {
    return {
      id,
      guest_id: guest.id,
      host_id: guest.host_id,
      source_vmid: guest.vmid,
      source_name: guest.name,
      guest_type: guest.guest_type,
      os_label: guest.os_label,
      test_vmid,
      backup_volid,
      backup_count,
      backup_used_index: 1,
      latest_backup_volid: backup_volid,
      used_fallback_backup: false,
      backups_attempted: 1,
      result_summary: failMsg,
      status: "failed",
      trigger,
      progress_pct: null,
      progress_label: null,
      proxmox_upid: null,
      proxmox_node: guest.node,
      error_message: failMsg,
      evidence_path: null,
      evidence_kind: "none",
      evidence_json: null,
      started_at: isoAt(startedMs),
      finished_at: isoAt(finishedMs),
      created_at: isoAt(createdMs),
      log_text: `[demo] restore ${guest.name} → ${test_vmid}\n[demo] ${failMsg}\n[demo] FAILED`,
    };
  }

  const isLxc = guest.guest_type === "lxc";
  return {
    id,
    guest_id: guest.id,
    host_id: guest.host_id,
    source_vmid: guest.vmid,
    source_name: guest.name,
    guest_type: guest.guest_type,
    os_label: guest.os_label,
    test_vmid,
    backup_volid: usedFallback
      ? `pbs:backup/${kind}/${guest.vmid}/${isoAt(createdMs - 3 * 86400_000)}`
      : backup_volid,
    backup_count,
    backup_used_index,
    latest_backup_volid: backup_volid,
    used_fallback_backup: usedFallback,
    backups_attempted: usedFallback ? backup_used_index : 1,
    result_summary: usedFallback
      ? "Latest backup failed integrity check on restore\nFell back to previous snapshot\nEvidence captured\nTest guest removed"
      : isLxc
        ? "LXC restore OK · container status proof captured (no VGA)\nTest guest removed"
        : "Restored PBS snapshot to test VMID\nNICs detached\nBoot wait complete\nConsole screenshot captured\nTest guest removed",
    status: "success",
    trigger,
    progress_pct: null,
    progress_label: null,
    proxmox_upid: `UPID:${guest.node}:000${(id % 9000).toString(16).toUpperCase()}:...`,
    proxmox_node: guest.node,
    error_message: null,
    evidence_path: isLxc ? null : "demo",
    evidence_kind: isLxc ? "container_proof" : "screenshot",
    evidence_json: isLxc
      ? JSON.stringify(
          {
            status: "running",
            hostname: guest.name,
            uptime: intBetween(rand, 20, 120),
            note: "Demo container proof — LXC has no VGA screenshot",
          },
          null,
          2
        )
      : null,
    started_at: isoAt(startedMs),
    finished_at: isoAt(finishedMs),
    created_at: isoAt(createdMs),
    log_text: `[demo] queued restore for ${guest.name} (${guest.vmid})
[demo] restore → test VMID ${test_vmid}
[demo] detach NICs
[demo] start + boot wait
[demo] evidence OK
[demo] cleanup test guest
[demo] success`,
  };
}

function buildGuestsAndRuns(rand: () => number) {
  const hosts: DemoHost[] = [
    {
      id: 1,
      name: "datacenter",
      api_url: "https://pve.datacenter.local:8006",
      token_id: "root@pam!restoreproof",
      verify_ssl: false,
      ssh_host: "pve.datacenter.local",
      ssh_port: 22,
      ssh_user: "root",
      ssh_private_key_path: "/data/ssh/host-1",
      preferred_restore_storage: "",
      test_vmid_start: 9000,
      test_vmid_end: 9099,
      enabled: true,
      last_sync_at: hoursAgo(1),
      api_ok_at: hoursAgo(1),
      ssh_ok_at: hoursAgo(2),
      last_error: null,
      has_token_secret: true,
      has_ssh_key: true,
    },
  ];

  const guests: DemoGuest[] = LIVE_GUESTS.map((bp, idx) => {
    const restorable = !bp.excluded && bp.in_backup_job && bp.backup_snapshot_count > 0;
    return {
      id: idx + 1,
      host_id: 1,
      host_name: "datacenter",
      vmid: bp.vmid,
      name: bp.name,
      guest_type: bp.guest_type,
      os_label: bp.os_label,
      node: "dc-pve1",
      status: bp.status,
      cpu_cores: bp.cpu_cores,
      memory_bytes: bp.memory_bytes,
      disk_bytes: bp.disk_bytes,
      excluded: bp.excluded,
      in_backup_job: bp.in_backup_job,
      backup_job_enabled: bp.backup_job_enabled,
      backup_job_summary: bp.in_backup_job ? LIVE_BACKUP_SUMMARY : "",
      backup_schedule: bp.in_backup_job ? "sun 01:00" : "",
      backup_snapshot_count: bp.backup_snapshot_count,
      last_backup_at: bp.backup_snapshot_count > 0 ? hoursAgo(6 + (idx % 18)) : null,
      schedule_cron: null,
      schedule_enabled: true,
      last_tested_at: null,
      next_due_at: restorable ? hoursFromNow(4 + (idx % 40)) : null,
    };
  });
  const intervals = new Map<number, number>(guests.map((g) => [g.id, 7]));
  const nextGuestId = guests.length + 1;

  const runs: DemoRun[] = [];
  let nextRunId = 1000;
  const now = Date.now();
  const oldest = now - HISTORY_DAYS * 86400_000;

  // Per-guest history along their cadence
  for (const guest of guests) {
    if (guest.excluded || !isRestorable(guest)) continue;
    const intervalDays = intervals.get(guest.id) ?? 10;
    let cursor = oldest + intBetween(rand, 0, intervalDays) * 86400_000 + guest.id * 3600_000;
    let prevFailed = false;

    while (cursor < now - 2 * 3600_000) {
      let status: "success" | "failed" = rand() < 0.06 ? "failed" : "success";
      let trigger: "schedule" | "manual" | "retry" =
        guest.schedule_cron && rand() < 0.15 ? "manual" : "schedule";

      // After a recent failure, often remediate with retry/success within a few days
      if (prevFailed && rand() < 0.75) {
        status = "success";
        trigger = "retry";
        prevFailed = false;
      } else {
        prevFailed = status === "failed";
      }

      const run = makeRun({
        id: nextRunId++,
        guest,
        createdMs: cursor,
        status,
        trigger,
        rand,
      });
      runs.push(run);
      cursor += (intervalDays + intBetween(rand, -1, 2)) * 86400_000;
    }
  }

  // Ensure a few remediable failures in the last 7 days + a couple open failures
  const eligible = guests.filter((g) => !g.excluded && isRestorable(g));
  const remTargets = [...eligible].sort(() => rand() - 0.5).slice(0, 3);
  for (const guest of remTargets) {
    const failMs = now - intBetween(rand, 2, 5) * 86400_000;
    const okMs = failMs + intBetween(rand, 12, 48) * 3600_000;
    runs.push(
      makeRun({
        id: nextRunId++,
        guest,
        createdMs: failMs,
        status: "failed",
        trigger: "schedule",
        rand,
      })
    );
    runs.push(
      makeRun({
        id: nextRunId++,
        guest,
        createdMs: okMs,
        status: "success",
        trigger: "retry",
        rand,
      })
    );
  }

  const openFails = [...eligible].sort(() => rand() - 0.5).slice(0, 2);
  for (const guest of openFails) {
    runs.push(
      makeRun({
        id: nextRunId++,
        guest,
        createdMs: now - intBetween(rand, 8, 36) * 3600_000,
        status: "failed",
        trigger: "schedule",
        rand,
      })
    );
  }

  // Newest runs are the Windows VMs that already have live console screenshots,
  // so the host card and the top of Runs open on a Windows desktop.
  for (const [index, name] of ["DC1", "Win11Pro", "FS1"].entries()) {
    const guest = guests.find((g) => g.name === name);
    if (!guest) continue;
    runs.push(
      makeRun({
        id: nextRunId++,
        guest,
        createdMs: now - (12 + index * 8) * 60_000,
        status: "success",
        trigger: "schedule",
        rand,
      })
    );
  }

  // Keep only last 90 days; cap volume for UI
  const cutoff = now - HISTORY_DAYS * 86400_000;
  let kept = runs.filter((r) => new Date(r.created_at).getTime() >= cutoff);
  kept.sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());
  // Re-number chronologically for nicer IDs
  let id = 1000;
  kept = kept.map((r) => ({ ...r, id: id++ }));
  kept.sort((a, b) => b.id - a.id);

  // Stamp guest last_tested_at from newest finished run
  for (const guest of guests) {
    const latest = kept.find(
      (r) => r.guest_id === guest.id && (r.status === "success" || r.status === "failed")
    );
    if (latest?.finished_at) guest.last_tested_at = latest.finished_at;
  }

  return { hosts, guests, runs: kept, nextGuestId, nextRunId: id };
}

function createStore() {
  const rand = mulberry32(20260722);
  const { hosts, guests, runs, nextGuestId, nextRunId } = buildGuestsAndRuns(rand);

  const users: DemoUser[] = [
    {
      id: 1,
      email: "demo@restoreproof.example",
      is_active: true,
      is_admin: true,
      totp_enabled: true,
    },
    {
      id: 2,
      email: "ops@acme.lab",
      is_active: true,
      is_admin: true,
      totp_enabled: false,
    },
  ];

  const settings: DemoSettings = {
    branding_title: "RestoreProof",
    boot_wait_seconds: 60,
    retention_days: 90,
    retention_max_runs: 500,
    global_cron: "45 3 * * *",
    schedule_enabled: true,
    schedule_batch_size: 5,
    schedule_coverage_goal: "weekly",
    enforce_2fa: false,
    setup_completed: true,
    notify_on_success: true,
    notify_on_failure: true,
    notify_to: "ops@acme.lab",
    notify_cc: "",
    public_base_url: "https://restoreproof.technologist.services",
    gap_alert_enabled: true,
    gap_alert_hours: 26,
    gap_alert_last_sent_at: null,
    unbacked_nudge_enabled: true,
    unbacked_nudge_last_sent_at: null,
    email_success_subject: "✅ RestoreProof passed — {{guest_name}} (VMID {{vmid}})",
    email_failure_subject: "❌ RestoreProof failed — {{guest_name}} (VMID {{vmid}})",
    email_success_body: SUCCESS_BODY,
    email_failure_body: FAILURE_BODY,
  };

  const smtp: DemoSmtp = {
    provider: "smtp2go",
    host: "mail.smtp2go.com",
    port: 587,
    use_tls: true,
    use_ssl: false,
    username: "restoreproof-demo",
    from_email: "restoreproof@acme.lab",
    from_name: "RestoreProof",
    password_set: true,
    smtp_ok_at: hoursAgo(24),
  };

  const push: DemoPush = {
    enabled: true,
    provider: "ntfy",
    url: "https://ntfy.sh/restoreproof-demo-7f3a91",
    verify_ssl: true,
    on_success: false,
    on_failure: true,
    token_set: false,
    push_ok_at: hoursAgo(24),
  };

  const heartbeat: DemoHeartbeat = {
    enabled: true,
    url: "http://uptime-kuma:3001/api/push/DemoPush01",
    interval_seconds: 300,
    verify_ssl: true,
    last_ping_at: new Date(Date.now() - 90_000).toISOString(),
    last_error: "",
  };

  return {
    users,
    hosts,
    guests,
    runs,
    settings,
    smtp,
    push,
    heartbeat,
    nextHostId: 4,
    nextGuestId,
    nextRunId,
    nextUserId: 3,
    activeRunId: null as number | null,
    lockHeld: false,
    lockHeldBy: null as string | null,
    wizardCompleted: true,
  };
}

export type DemoStore = ReturnType<typeof createStore>;

let store: DemoStore = createStore();

export function getDemoStore(): DemoStore {
  return store;
}

export function resetDemoStore(): void {
  store = createStore();
}

/** Annotate failed runs with remediation flags (mirrors backend 7-day window). */
export function withRemediation(runs: DemoRun[]): DemoRun[] {
  const now = Date.now();
  const lookback = now - REMEDIATE_LOOKBACK_MS;
  return runs.map((run) => {
    if (run.status !== "failed") {
      return { ...run, remediated: false, remediated_by_run_id: null };
    }
    const created = new Date(run.created_at).getTime();
    if (created < lookback) {
      return { ...run, remediated: false, remediated_by_run_id: null };
    }
    const deadline = created + REMEDIATE_AFTER_FAIL_MS;
    const later = store.runs
      .filter((r) => {
        if (r.status !== "success" || r.id === run.id) return false;
        const t = new Date(r.created_at).getTime();
        if (t <= created || t > deadline) return false;
        if (run.guest_id != null) return r.guest_id === run.guest_id;
        return r.host_id === run.host_id && r.source_vmid === run.source_vmid;
      })
      .sort((a, b) => a.id - b.id)[0];
    if (!later) return { ...run, remediated: false, remediated_by_run_id: null };
    return { ...run, remediated: true, remediated_by_run_id: later.id };
  });
}

export function guestWithLatest(guest: DemoGuest) {
  const latest = store.runs
    .filter((r) => r.guest_id === guest.id && (r.status === "success" || r.status === "failed"))
    .sort((a, b) => b.id - a.id)[0];
  return {
    ...guest,
    latest_run: latest
      ? {
          id: latest.id,
          status: latest.status,
          used_fallback_backup: latest.used_fallback_backup,
          finished_at: latest.finished_at,
          started_at: latest.started_at,
          error_message: latest.error_message,
        }
      : null,
  };
}

export function hostWithLatest(host: DemoHost) {
  const latest = store.runs
    .filter((r) => r.host_id === host.id && (r.status === "success" || r.status === "failed"))
    .sort((a, b) => {
      const ta = new Date(a.finished_at || a.created_at).getTime();
      const tb = new Date(b.finished_at || b.created_at).getTime();
      return tb - ta;
    })[0];
  return {
    ...host,
    latest_run: latest
      ? {
          id: latest.id,
          status: latest.status,
          source_name: latest.source_name,
          source_vmid: latest.source_vmid,
          guest_type: latest.guest_type,
          evidence_kind: latest.evidence_kind,
          error_message: latest.error_message,
          result_summary: latest.result_summary,
          used_fallback_backup: latest.used_fallback_backup,
          backup_count: latest.backup_count,
          backup_used_index: latest.backup_used_index,
          finished_at: latest.finished_at,
          started_at: latest.started_at,
        }
      : null,
  };
}

/** Rough tick counts so a daily cron is not described as a weekly Sunday job. */
function cronCadence(cron: string): { ticksWeek: number; ticksMonth: number; perDay: number } {
  const parts = cron.trim().split(/\s+/);
  const dom = parts[2] ?? "*";
  const dow = parts[4] ?? "*";
  if (dom !== "*") return { ticksWeek: 0.25, ticksMonth: 1, perDay: 1 / 30 };
  if (dow === "*") return { ticksWeek: 7, ticksMonth: 30, perDay: 1 };
  const days = dow.split(",").filter(Boolean).length || 1;
  return { ticksWeek: days, ticksMonth: days * 4, perDay: days / 7 };
}

export function buildSchedulePlan() {
  const s = store.settings;
  const total = store.guests.length;
  const excluded = store.guests.filter((g) => g.excluded).length;
  const notBackedUp = store.guests.filter((g) => !g.excluded && !g.in_backup_job).length;
  const noSnapshot = store.guests.filter(
    (g) => !g.excluded && g.in_backup_job && g.backup_snapshot_count === 0
  ).length;
  const eligible = store.guests.filter(
    (g) => !g.excluded && g.schedule_enabled && isRestorable(g)
  ).length;
  const batch = Math.max(1, s.schedule_batch_size);
  const cadence = cronCadence(s.global_cron);
  const ticksWeek = cadence.ticksWeek;
  const ticksMonth = cadence.ticksMonth;
  const ticksToCover = eligible ? Math.ceil(eligible / batch) : 0;
  const days = Math.round((ticksToCover / cadence.perDay) * 10) / 10;
  return {
    total_guests: total,
    excluded_count: excluded,
    not_backed_up_count: notBackedUp,
    no_snapshot_count: noSnapshot,
    eligible_count: eligible,
    schedule_batch_size: batch,
    schedule_coverage_goal: s.schedule_coverage_goal,
    global_cron: s.global_cron,
    ticks_per_week: ticksWeek,
    ticks_per_month: ticksMonth,
    suggested_batch_weekly: Math.max(1, Math.ceil(eligible / 1)),
    suggested_batch_monthly: Math.max(1, Math.ceil(eligible / ticksMonth)),
    ticks_to_cover_all: ticksToCover,
    days_to_cover_all_estimate: days,
    cover_weekly_ok: batch * ticksWeek >= eligible,
    cover_monthly_ok: batch * ticksMonth >= eligible,
    enqueued_this_window: 0,
    window_remaining: batch,
    summary:
      eligible === 0
        ? "No eligible guests — un-exclude VMs on the Guests page."
        : `${batch} restore(s) per schedule tick · ~${ticksWeek} ticks/week · ${eligible} eligible · ~${Math.round(days)} days for a full cycle.`,
  };
}

/** `recentLimit` of 0 means all, matching the API's recent_limit contract. */
export function buildDashboard(recentLimit = 10) {
  const s = store.settings;
  const excluded = store.guests.filter((g) => g.excluded).length;
  const nextDue =
    store.guests
      .filter((g) => !g.excluded && isRestorable(g) && g.next_due_at)
      .sort((a, b) => String(a.next_due_at).localeCompare(String(b.next_due_at)))[0] || null;
  const active = store.activeRunId
    ? store.runs.find((r) => r.id === store.activeRunId) || null
    : null;
  const ordered = [...store.runs].sort((a, b) => b.id - a.id);
  const recent = withRemediation(recentLimit ? ordered.slice(0, recentLimit) : ordered);
  return {
    setup_completed: true,
    schedule_enabled: s.schedule_enabled,
    global_cron: s.global_cron,
    lock_held: store.lockHeld,
    lock_held_by: store.lockHeldBy,
    lock_run_id: store.activeRunId,
    recent_runs: recent,
    recent_runs_total: store.runs.length,
    guest_count: store.guests.length,
    excluded_count: excluded,
    host_count: store.hosts.length,
    backup_health: fleetBackupHealth(store.guests),
    next_due: nextDue,
    active_run: active
      ? {
          id: active.id,
          status: active.status,
          source_name: active.source_name,
          source_vmid: active.source_vmid,
          guest_type: active.guest_type,
          os_label: active.os_label,
          host_id: active.host_id,
          test_vmid: active.test_vmid,
          progress_pct: active.progress_pct,
          progress_label: active.progress_label,
          started_at: active.started_at,
          created_at: active.created_at,
        }
      : null,
  };
}

// Re-export helpers used by pages that may display relative times in demos
export { hoursAgo, daysAgo };
