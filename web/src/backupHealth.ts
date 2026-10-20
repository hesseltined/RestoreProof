/**
 * Purpose: Decide if a guest backup is current, matching backend backup_health.py.
 * Author: Doug Hesseltine
 * Created: 2026-10-19
 * Modified: 2026-10-19
 * Version: 1.0.0
 *
 * A guest is current only when its backup job is enabled and the newest snapshot
 * is inside that job's schedule. A disabled job is reported even if the last
 * snapshot is still young.
 */

const WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;
const DAY_MS = 86400_000;
const HOUR_MS = 3600_000;

export type BackupStatus = "current" | "disabled" | "stale" | "missing" | "unprotected";

export type BackupGuest = {
  vmid: number;
  name: string;
  excluded?: boolean;
  in_backup_job: boolean;
  backup_job_enabled: boolean;
  backup_job_summary?: string;
  backup_schedule?: string;
  backup_snapshot_count: number;
  last_backup_at: string | null;
};

export type BackupHealthGuest = {
  vmid: number;
  name: string;
  last_backup_at: string | null;
  detail: string;
};

export type BackupHealth = {
  ok: boolean;
  headline: string;
  current_count: number;
  disabled_count: number;
  stale_count: number;
  missing_count: number;
  disabled_jobs: { label: string; guest_count: number; oldest_backup_at: string | null }[];
  stale_guests: BackupHealthGuest[];
  missing_guests: BackupHealthGuest[];
};

export function scheduleMaxGapMs(schedule: string): number | null {
  const raw = schedule.trim().toLowerCase();
  if (!raw) return null;
  if (raw === "minutely") return 60_000;
  if (raw === "hourly") return HOUR_MS;
  if (raw === "daily") return DAY_MS;
  if (raw === "weekly") return 7 * DAY_MS;
  if (raw === "monthly") return 31 * DAY_MS;

  const timeMatch = raw.match(/\b\d{1,2}:\d{2}(?::\d{2})?\s*$/);
  const body = timeMatch ? raw.slice(0, timeMatch.index).trim() : raw;
  if (!body) return DAY_MS;
  if (body === "hourly") return HOUR_MS;
  if (body === "daily" || body === "*" || body === "*-*-*" || body.startsWith("*-*-*")) {
    return DAY_MS;
  }

  const days = expandWeekdays(body);
  if (!days || days.size === 0) return null;
  return maxWeekdayGap(days) * DAY_MS;
}

export function freshnessLimitMs(schedule: string): number | null {
  const gap = scheduleMaxGapMs(schedule);
  if (gap == null) return null;
  const grace = Math.min(36 * HOUR_MS, Math.max(2 * HOUR_MS, gap * 0.25));
  return gap + grace;
}

function guestSchedule(g: BackupGuest): string {
  const stored = (g.backup_schedule || "").trim();
  if (stored) return stored;
  const match = (g.backup_job_summary || "").match(/\(([^)]+)\)/);
  return match ? match[1].trim() : "";
}

export function assessBackup(g: BackupGuest, now = Date.now()): { status: BackupStatus; detail: string } {
  if (!g.in_backup_job) {
    return {
      status: "unprotected",
      detail: "Not listed in any Proxmox backup job (Datacenter → Backup).",
    };
  }
  const schedule = guestSchedule(g);
  const recognized = schedule ? freshnessLimitMs(schedule) != null : false;
  const limit = recognized ? freshnessLimitMs(schedule) : freshnessLimitMs("sun 01:00");
  const lastMs = g.last_backup_at ? Date.parse(g.last_backup_at) : NaN;
  const hasLast = Number.isFinite(lastMs);
  const age = hasLast ? now - lastMs : null;
  const scheduleLabel = schedule || "unrecognized schedule";

  if (!g.backup_job_enabled) {
    if (!hasLast) {
      return {
        status: "disabled",
        detail: `Backup job is disabled (${scheduleLabel}). No PBS snapshot exists.`,
      };
    }
    return {
      status: "disabled",
      detail: `Backup job is disabled (${scheduleLabel}). Last snapshot ${formatWhen(lastMs)} (${agePhrase(age)} ago).`,
    };
  }
  if (!hasLast || !g.backup_snapshot_count) {
    const shown = schedule || "its backup job";
    return {
      status: "missing",
      detail: `No PBS backup exists yet. It is scheduled by ${shown} but has not produced a snapshot — run that backup job first.`,
    };
  }
  if (limit != null && age != null && age > limit) {
    const why = recognized
      ? `The job schedule is ${schedule}.`
      : "The schedule was not recognized, so the weekly limit is used.";
    return {
      status: "stale",
      detail: `Newest snapshot is ${formatWhen(lastMs)} (${agePhrase(age)} ago). ${why} A current backup has to be newer than ${agePhrase(limit)}.`,
    };
  }
  return {
    status: "current",
    detail: `Newest snapshot ${formatWhen(lastMs)} is inside the ${scheduleLabel} window.`,
  };
}

export function fleetBackupHealth(guests: BackupGuest[], now = Date.now()): BackupHealth {
  const disabled: (BackupHealthGuest & { job_label: string })[] = [];
  const stale: BackupHealthGuest[] = [];
  const missing: BackupHealthGuest[] = [];
  let current = 0;
  for (const guest of guests) {
    if (guest.excluded) continue;
    const assessed = assessBackup(guest, now);
    if (assessed.status === "current") {
      current += 1;
      continue;
    }
    if (assessed.status === "unprotected") continue;
    const row = {
      vmid: guest.vmid,
      name: guest.name,
      last_backup_at: guest.last_backup_at,
      detail: assessed.detail,
      job_label: guest.backup_job_summary || "Backup job",
    };
    if (assessed.status === "disabled") disabled.push(row);
    else if (assessed.status === "stale") stale.push(row);
    else if (assessed.status === "missing") missing.push(row);
  }

  const groups = new Map<string, typeof disabled>();
  for (const row of disabled) {
    const list = groups.get(row.job_label) || [];
    list.push(row);
    groups.set(row.job_label, list);
  }
  const disabledJobs = [...groups.entries()]
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([label, rows]) => {
      const dates = rows
        .map((row) => row.last_backup_at)
        .filter((value): value is string => Boolean(value))
        .sort();
      return {
        label,
        guest_count: rows.length,
        oldest_backup_at: dates[0] || null,
      };
    });

  const staleSorted = [...stale].sort((a, b) =>
    String(a.last_backup_at || "").localeCompare(String(b.last_backup_at || ""))
  );
  const missingSorted = [...missing].sort((a, b) => a.name.localeCompare(b.name) || a.vmid - b.vmid);
  const disabledCount = disabled.length;
  const staleCount = stale.length;
  const missingCount = missing.length;
  return {
    ok: disabledCount + staleCount + missingCount === 0,
    headline: headline(disabledJobs, staleCount, missingCount),
    current_count: current,
    disabled_count: disabledCount,
    stale_count: staleCount,
    missing_count: missingCount,
    disabled_jobs: disabledJobs,
    stale_guests: staleSorted.slice(0, 12),
    missing_guests: missingSorted.slice(0, 12),
  };
}

function headline(
  disabledJobs: BackupHealth["disabled_jobs"],
  stale: number,
  missing: number
): string {
  if (disabledJobs.length) {
    const labels = disabledJobs
      .slice(0, 3)
      .map((job) => job.label)
      .join(", ");
    const guests = disabledJobs.reduce((sum, job) => sum + job.guest_count, 0);
    const noun = guests === 1 ? "guest is" : "guests are";
    return `${guests} ${noun} on a disabled backup job: ${labels}.`;
  }
  if (stale) {
    const noun = stale === 1 ? "guest has" : "guests have";
    return `${stale} ${noun} a backup older than the job schedule.`;
  }
  if (missing) {
    const noun = missing === 1 ? "guest is" : "guests are";
    return `${missing} ${noun} in a backup job with no PBS snapshot yet.`;
  }
  return "Backups are current.";
}

function expandWeekdays(body: string): Set<number> | null {
  const days = new Set<number>();
  for (const part of body.trim().split(/[\s,]+/)) {
    if (!part) continue;
    if (part.includes("..")) {
      const [start, end] = part.split("..");
      const ia = WEEKDAYS.indexOf(start as (typeof WEEKDAYS)[number]);
      const ib = WEEKDAYS.indexOf(end as (typeof WEEKDAYS)[number]);
      if (ia < 0 || ib < 0) return null;
      if (ia <= ib) {
        for (let i = ia; i <= ib; i += 1) days.add(i);
      } else {
        for (let i = ia; i < 7; i += 1) days.add(i);
        for (let i = 0; i <= ib; i += 1) days.add(i);
      }
      continue;
    }
    const index = WEEKDAYS.indexOf(part as (typeof WEEKDAYS)[number]);
    if (index < 0) return null;
    days.add(index);
  }
  return days;
}

function maxWeekdayGap(days: Set<number>): number {
  if (days.size >= 7) return 1;
  const ordered = [...days].sort((a, b) => a - b);
  let max = 1;
  for (let i = 0; i < ordered.length; i += 1) {
    const nxt = ordered[(i + 1) % ordered.length];
    let gap = (nxt - ordered[i] + 7) % 7;
    if (gap === 0) gap = 7;
    if (gap > max) max = gap;
  }
  return max;
}

function agePhrase(ms: number | null): string {
  if (ms == null || ms < 0) return "an unknown time";
  const days = Math.floor(ms / DAY_MS);
  const hours = Math.floor((ms % DAY_MS) / HOUR_MS);
  if (days >= 2) return `${days} days`;
  if (days === 1) return "1 day";
  if (hours >= 2) return `${hours} hours`;
  return `${Math.max(1, Math.floor(ms / 60000))} minutes`;
}

function formatWhen(ms: number): string {
  return new Date(ms).toISOString().replace("T", " ").slice(0, 16) + " UTC";
}
