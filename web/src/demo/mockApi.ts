/**
 * Purpose: Client-side mock API for RestoreProof /demo (no backend, no login).
 * Author: Doug Hesseltine
 * Created: 2026-07-13
 * Modified: 2026-07-31
 * Version: 2.5.0
 */

import { APP_VERSION } from "../version";
import { buildDemoEvidenceBlob } from "./evidence";
import {
  DEMO_SMTP_PRESETS,
  buildDashboard,
  buildSchedulePlan,
  getDemoStore,
  guestWithLatest,
  hostWithLatest,
  withRemediation,
  type DemoHost,
  type DemoRun,
  type DemoSettings,
  type DemoHeartbeat,
  type DemoPush,
  type DemoSmtp,
  type DemoUser,
} from "./store";

export class DemoApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function parseBody(options: RequestInit): unknown {
  if (!options.body) return null;
  if (typeof options.body === "string") {
    try {
      return JSON.parse(options.body);
    } catch {
      return null;
    }
  }
  return null;
}

function parseQuery(path: string): URLSearchParams {
  const q = path.includes("?") ? path.split("?")[1] : "";
  return new URLSearchParams(q);
}

function tickActiveRun() {
  const store = getDemoStore();
  if (store.activeRunId == null) return;
  const run = store.runs.find((r) => r.id === store.activeRunId);
  if (!run || (run.status !== "queued" && run.status !== "running")) return;

  const pct = run.progress_pct ?? 0;
  if (run.status === "queued") {
    run.status = "running";
    run.progress_pct = 5;
    run.progress_label = "Restoring PBS snapshot to test VMID…";
    run.started_at = new Date().toISOString();
    store.lockHeld = true;
    store.lockHeldBy = `${run.source_name} (${run.source_vmid})`;
    return;
  }

  if (pct < 95) {
    const next = Math.min(95, pct + 12 + Math.random() * 10);
    run.progress_pct = next;
    if (next < 40) run.progress_label = "Transferring disk images…";
    else if (next < 70) run.progress_label = "Configuring test guest (NICs detached)…";
    else run.progress_label = "Boot wait — capturing console evidence…";
    return;
  }

  run.status = "success";
  run.progress_pct = 100;
  run.progress_label = "Complete";
  run.finished_at = new Date().toISOString();
  run.evidence_kind = run.guest_type === "lxc" ? "container_proof" : "screenshot";
  if (run.guest_type === "lxc") {
    run.evidence_json = JSON.stringify(
      { status: "running", hostname: run.source_name, note: "Demo container proof" },
      null,
      2
    );
  } else {
    run.evidence_path = "demo";
  }
  run.result_summary =
    "Demo restore finished successfully\nNICs detached\nEvidence captured\nTest guest cleaned up";
  run.log_text += `\n[demo] finished at ${run.finished_at}`;
  store.activeRunId = null;
  store.lockHeld = false;
  store.lockHeldBy = null;
  const guest = store.guests.find((g) => g.id === run.guest_id);
  if (guest) guest.last_tested_at = run.finished_at;
}

function queueRunForGuest(
  guestId: number,
  trigger: "manual" | "retry"
): { run?: DemoRun; error?: { status: number; detail: string } } {
  const store = getDemoStore();
  if (store.activeRunId != null) {
    return { error: { status: 409, detail: "A restore is already running (demo lock)." } };
  }
  const guest = store.guests.find((g) => g.id === guestId);
  if (!guest) return { error: { status: 404, detail: "Guest not found" } };
  if (!guest.in_backup_job) {
    return {
      error: {
        status: 400,
        detail: `VMID ${guest.vmid} (${guest.name}) is not listed in any Proxmox backup job.`,
      },
    };
  }
  if (!guest.backup_snapshot_count) {
    return {
      error: {
        status: 400,
        detail: `No PBS backup exists yet for VMID ${guest.vmid} (${guest.name}).`,
      },
    };
  }
  const run: DemoRun = {
    id: store.nextRunId++,
    guest_id: guest.id,
    host_id: guest.host_id,
    source_vmid: guest.vmid,
    source_name: guest.name,
    guest_type: guest.guest_type,
    test_vmid: 9000 + (store.nextRunId % 50),
    backup_volid: `pbs:backup/${guest.guest_type === "lxc" ? "ct" : "vm"}/${guest.vmid}/${new Date().toISOString()}`,
    backup_count: 12,
    backup_used_index: 1,
    latest_backup_volid: "",
    used_fallback_backup: false,
    backups_attempted: 1,
    result_summary: "",
    status: "queued",
    trigger,
    progress_pct: 0,
    progress_label: "Queued",
    proxmox_upid: null,
    proxmox_node: guest.node,
    error_message: null,
    evidence_path: null,
    evidence_kind: "none",
    evidence_json: null,
    started_at: null,
    finished_at: null,
    created_at: new Date().toISOString(),
    log_text: `[demo] ${trigger === "retry" ? "Retry" : "Run now"} queued for ${guest.name}`,
  };
  run.latest_backup_volid = run.backup_volid;
  store.runs.unshift(run);
  store.activeRunId = run.id;
  store.lockHeld = true;
  store.lockHeldBy = `${guest.name} (${guest.vmid})`;
  return { run };
}

async function delay(ms = 80): Promise<void> {
  await new Promise((r) => setTimeout(r, ms));
}

export async function demoApiFetch(path: string, options: RequestInit = {}): Promise<Response> {
  await delay();
  tickActiveRun();

  const method = (options.method || "GET").toUpperCase();
  const clean = path.split("?")[0].replace(/\/$/, "") || "/";
  const query = parseQuery(path);
  const body = parseBody(options) as Record<string, unknown> | null;
  const store = getDemoStore();

  const json = (data: unknown, status = 200) =>
    new Response(JSON.stringify(data), {
      status,
      headers: { "Content-Type": "application/json" },
    });

  const err = (status: number, detail: string) => json({ detail }, status);

  // Health
  if (method === "GET" && (clean === "/health" || clean === "/api/health")) {
    return json({ status: "ok", version: `${APP_VERSION}-demo` });
  }

  // Auth
  if (method === "GET" && clean === "/auth/status") {
    return json({ setup_completed: true, user_count: store.users.length });
  }
  if (method === "GET" && clean === "/auth/me") {
    return json(store.users[0]);
  }
  if (method === "POST" && clean === "/auth/login") {
    return json({ access_token: "demo-token", token_type: "bearer" });
  }
  if (method === "POST" && clean === "/auth/totp/setup") {
    return json({
      secret: "DEMO2FASECRETBASE32XX",
      otpauth_uri:
        "otpauth://totp/RestoreProof:demo@restoreproof.example?secret=DEMO2FASECRETBASE32XX&issuer=RestoreProof",
    });
  }
  if (method === "POST" && clean === "/auth/totp/enable") {
    store.users[0].totp_enabled = true;
    return json({ ok: true });
  }

  // Setup wizard (idle / complete for demo)
  if (method === "GET" && clean === "/setup/progress") {
    return json({
      steps: [
        {
          id: "admin",
          title: "Admin account",
          body: "Demo admin ready.",
          done: true,
          current: false,
          to: "/users",
        },
        {
          id: "host",
          title: "Proxmox host",
          body: "Sample hosts loaded.",
          done: true,
          current: false,
          to: "/hosts",
        },
        {
          id: "smtp",
          title: "Email",
          body: "Sample SMTP configured.",
          done: true,
          current: false,
          to: "/notifications",
        },
        {
          id: "schedule",
          title: "Schedule",
          body: "Weekly fleet rotation enabled.",
          done: true,
          current: false,
          to: "/schedule",
        },
      ],
      completed_count: 4,
      total_count: 4,
      all_done: true,
      next_step_id: null,
      next_path: null,
      wizard_completed: store.wizardCompleted,
      secrets_need_attention: false,
      secrets_message: null,
      offer_wizard: !store.wizardCompleted,
    });
  }
  if (method === "POST" && clean === "/setup/wizard/complete") {
    store.wizardCompleted = true;
    return json({ ok: true });
  }
  if (method === "POST" && clean === "/setup/wizard/reopen") {
    store.wizardCompleted = false;
    return json({ ok: true });
  }

  // Dashboard / settings / schedule
  if (method === "GET" && clean === "/dashboard") {
    const raw = query.get("recent_limit");
    const limit = raw === null ? 10 : Math.max(0, Math.min(500, Number(raw) || 0));
    return json(buildDashboard(limit));
  }
  if (method === "GET" && clean === "/settings") {
    return json(store.settings);
  }
  if (method === "PUT" && clean === "/settings") {
    Object.assign(store.settings, body || {});
    return json(store.settings);
  }
  if (method === "POST" && clean === "/settings/email-templates/reset") {
    store.settings.email_success_subject =
      "✅ RestoreProof passed — {{guest_name}} (VMID {{vmid}})";
    store.settings.email_failure_subject =
      "❌ RestoreProof failed — {{guest_name}} (VMID {{vmid}})";
    store.settings.email_success_body =
      "<h1>Backup restore verified ✓</h1><p>{{guest_name}}</p>{{proof_section}}";
    store.settings.email_failure_body =
      "<h1>Restore test failed</h1><p>{{error_message}}</p>{{proof_section}}";
    return json(store.settings);
  }
  if (method === "POST" && clean === "/settings/purge-runs") {
    const before = body?.before ? new Date(String(body.before)).getTime() : NaN;
    if (Number.isNaN(before)) return err(400, "Invalid before date");
    const beforeCount = store.runs.length;
    store.runs = store.runs.filter((r) => new Date(r.created_at).getTime() >= before);
    return json({ deleted: beforeCount - store.runs.length, before: body?.before });
  }
  if (method === "POST" && clean === "/settings/purge-stale-runs") {
    const orphaned = body?.orphaned !== false;
    const notBackedUp = body?.not_backed_up !== false;
    let orphanedDeleted = 0;
    let notBackedDeleted = 0;
    const keep: typeof store.runs = [];
    const notBackedIds = new Set(
      store.guests.filter((g) => !g.in_backup_job).map((g) => g.id)
    );
    for (const r of store.runs) {
      if (orphaned && r.guest_id == null) {
        orphanedDeleted += 1;
        continue;
      }
      if (notBackedUp && r.guest_id != null && notBackedIds.has(r.guest_id)) {
        notBackedDeleted += 1;
        continue;
      }
      keep.push(r);
    }
    store.runs = keep;
    return json({
      deleted: orphanedDeleted + notBackedDeleted,
      orphaned_deleted: orphanedDeleted,
      not_backed_up_deleted: notBackedDeleted,
    });
  }
  if (method === "GET" && clean === "/schedule/plan") {
    return json(buildSchedulePlan());
  }
  if (method === "POST" && clean === "/guests/refresh-schedule") {
    return json({ ok: true });
  }

  // SMTP
  if (method === "GET" && clean === "/smtp/presets") {
    return json(DEMO_SMTP_PRESETS);
  }
  if (method === "GET" && clean === "/smtp") {
    return json(store.smtp);
  }
  if (method === "PUT" && clean === "/smtp") {
    const next = { ...(body || {}) } as Partial<DemoSmtp> & { password?: string };
    const { password, ...rest } = next;
    Object.assign(store.smtp, rest);
    if (password) store.smtp.password_set = true;
    store.smtp.smtp_ok_at = new Date().toISOString();
    return json(store.smtp);
  }
  if (method === "POST" && clean === "/smtp/test") {
    return json({ ok: true, detail: "Demo mode — no email was sent." });
  }

  // Push (ntfy)
  if (method === "GET" && clean === "/push") {
    return json(store.push);
  }
  if (method === "PUT" && clean === "/push") {
    const { token, ...rest } = { ...(body || {}) } as Partial<DemoPush> & { token?: string };
    Object.assign(store.push, rest);
    if (token) store.push.token_set = token.trim() !== "-";
    return json(store.push);
  }
  if (method === "POST" && clean === "/push/test") {
    store.push.push_ok_at = new Date().toISOString();
    return json({ ok: true, detail: "Demo mode — no push was sent." });
  }

  // Worker heartbeat
  if (method === "GET" && clean === "/heartbeat") {
    return json(store.heartbeat);
  }
  if (method === "PUT" && clean === "/heartbeat") {
    Object.assign(store.heartbeat, (body || {}) as Partial<DemoHeartbeat>);
    return json(store.heartbeat);
  }
  if (method === "POST" && clean === "/heartbeat/test") {
    store.heartbeat.last_ping_at = new Date().toISOString();
    store.heartbeat.last_error = "";
    return json({ ok: true, detail: "Demo mode — no ping was sent." });
  }

  // Users
  if (method === "GET" && clean === "/users") {
    return json(store.users);
  }
  if (method === "POST" && clean === "/users") {
    const email = String(body?.email || "");
    const user: DemoUser = {
      id: store.nextUserId++,
      email,
      is_active: true,
      is_admin: true,
      totp_enabled: false,
    };
    store.users.push(user);
    return json(user, 201);
  }

  // Guests
  if (method === "GET" && clean === "/guests") {
    return json(store.guests.map(guestWithLatest));
  }
  {
    const m = clean.match(/^\/guests\/(\d+)$/);
    if (m && method === "PATCH") {
      const id = Number(m[1]);
      const guest = store.guests.find((g) => g.id === id);
      if (!guest) return err(404, "Guest not found");
      Object.assign(guest, body || {});
      return json(guestWithLatest(guest));
    }
  }
  {
    const m = clean.match(/^\/guests\/(\d+)\/run$/);
    if (m && method === "POST") {
      const result = queueRunForGuest(Number(m[1]), "manual");
      if (result.error) return err(result.error.status, result.error.detail);
      return json(result.run, 201);
    }
  }

  // Hosts
  if (method === "GET" && clean === "/hosts") {
    return json(store.hosts.map(hostWithLatest));
  }
  if (method === "POST" && clean === "/hosts") {
    const host: DemoHost = {
      id: store.nextHostId++,
      name: String(body?.name || "New host"),
      api_url: String(body?.api_url || ""),
      token_id: String(body?.token_id || ""),
      verify_ssl: Boolean(body?.verify_ssl),
      ssh_host: String(body?.ssh_host || ""),
      ssh_port: Number(body?.ssh_port || 22),
      ssh_user: String(body?.ssh_user || "root"),
      ssh_private_key_path: `/data/ssh/host-${store.nextHostId}`,
      preferred_restore_storage: String(body?.preferred_restore_storage || ""),
      test_vmid_start: Number(body?.test_vmid_start || 9000),
      test_vmid_end: Number(body?.test_vmid_end || 9099),
      enabled: true,
      last_sync_at: null,
      api_ok_at: null,
      ssh_ok_at: null,
      last_error: null,
      has_token_secret: true,
      has_ssh_key: true,
    };
    store.hosts.push(host);
    return json(hostWithLatest(host), 201);
  }
  {
    const m = clean.match(/^\/hosts\/(\d+)$/);
    if (m && method === "DELETE") {
      const id = Number(m[1]);
      store.hosts = store.hosts.filter((h) => h.id !== id);
      store.guests = store.guests.filter((g) => g.host_id !== id);
      return json({ ok: true });
    }
  }
  {
    const m = clean.match(/^\/hosts\/(\d+)\/ssh-key$/);
    if (m && method === "GET") {
      const id = Number(m[1]);
      const host = store.hosts.find((h) => h.id === id);
      if (!host) return err(404, "Host not found");
      const pub =
        "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDemoRestoreProofPublicKeyOnlyXXXX restoreproof-demo";
      return json({
        public_key: pub,
        install_command: `ssh-copy-id -i /tmp/rp-demo.pub ${host.ssh_user}@${host.ssh_host || "proxmox-host"}`,
        instructions:
          "Demo mode — this is a sample SSH public key. On a real install, paste the install command onto your Proxmox nodes that need VGA screenshots.",
      });
    }
  }
  {
    const m = clean.match(/^\/hosts\/(\d+)\/test-api$/);
    if (m && method === "POST") {
      const id = Number(m[1]);
      const host = store.hosts.find((h) => h.id === id);
      if (!host) return err(404, "Host not found");
      host.api_ok_at = new Date().toISOString();
      host.last_error = null;
      return json({ ok: true, nodes: ["pve1", "pve2"] });
    }
  }
  {
    const m = clean.match(/^\/hosts\/(\d+)\/test-ssh$/);
    if (m && method === "POST") {
      const id = Number(m[1]);
      const host = store.hosts.find((h) => h.id === id);
      if (!host) return err(404, "Host not found");
      host.ssh_ok_at = new Date().toISOString();
      host.last_error = null;
      return json({ output: "uname -a → Linux pve 6.8.12-demo (demo)" });
    }
  }
  {
    const m = clean.match(/^\/hosts\/(\d+)\/sync$/);
    if (m && method === "POST") {
      const id = Number(m[1]);
      const host = store.hosts.find((h) => h.id === id);
      if (!host) return err(404, "Host not found");
      host.last_sync_at = new Date().toISOString();
      const count = store.guests.filter((g) => g.host_id === id).length;
      return json({ synced: count || 3 });
    }
  }

  // Runs (paginated list)
  if (method === "GET" && clean === "/runs") {
    const page = Math.max(1, Number(query.get("page") || 1));
    const pageSize = Math.min(100, Math.max(1, Number(query.get("page_size") || 20)));
    const sorted = withRemediation([...store.runs].sort((a, b) => b.id - a.id));
    const total = sorted.length;
    const start = (page - 1) * pageSize;
    const items = sorted.slice(start, start + pageSize);
    return json({ items, total, page, page_size: pageSize });
  }
  {
    const m = clean.match(/^\/runs\/(\d+)$/);
    if (m && method === "GET") {
      const run = store.runs.find((r) => r.id === Number(m[1]));
      if (!run) return err(404, "Run not found");
      return json(withRemediation([run])[0]);
    }
  }
  {
    const m = clean.match(/^\/runs\/(\d+)\/retry$/);
    if (m && method === "POST") {
      const prior = store.runs.find((r) => r.id === Number(m[1]));
      if (!prior || prior.guest_id == null) return err(404, "Run not found");
      const result = queueRunForGuest(prior.guest_id, "retry");
      if (result.error) return err(result.error.status, result.error.detail);
      return json(result.run, 201);
    }
  }
  {
    const m = clean.match(/^\/runs\/(\d+)\/resend-email$/);
    if (m && method === "POST") {
      return json({ ok: true, detail: "Demo mode — email not sent." });
    }
  }
  {
    const m = clean.match(/^\/runs\/(\d+)\/evidence$/);
    if (m && method === "GET") {
      const run = store.runs.find((r) => r.id === Number(m[1]));
      if (!run || run.evidence_kind !== "screenshot") {
        return new Response("Not found", { status: 404 });
      }
      const blob = buildDemoEvidenceBlob(run.source_name, run.source_vmid);
      return new Response(blob, {
        status: 200,
        headers: { "Content-Type": "image/svg+xml" },
      });
    }
  }

  // Config export / import
  if (method === "GET" && clean === "/config/export") {
    return json({
      filename: "restoreproof-demo-config.json",
      data: JSON.stringify(
        {
          demo: true,
          note: "Sample export from marketing demo — not a real configuration.",
          hosts: store.hosts.map((h) => ({ name: h.name, api_url: h.api_url })),
          settings: store.settings as DemoSettings,
        },
        null,
        2
      ),
    });
  }
  if (method === "POST" && clean.startsWith("/config/import")) {
    return json({
      mode: "merge",
      hosts_created: 0,
      hosts_updated: store.hosts.length,
      guest_overrides_applied: 3,
      guest_overrides_pending: 0,
      users_created: 0,
      users_skipped: 1,
    });
  }

  return err(404, `Demo API: unhandled ${method} ${clean}`);
}
