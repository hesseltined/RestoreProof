/**
 * Purpose: Guest inventory with exclude, schedule override, run now.
 * Author: Doug Hesseltine
 * Created: 2026-07-12
 * Modified: 2026-07-12
 * Version: 1.7.0
 */

import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import {
  cronToBuilder,
  describeBuilder,
  type TimeDisplay,
} from "../components/CronScheduleBuilder";

type Guest = {
  id: number;
  host_name: string;
  vmid: number;
  name: string;
  guest_type: string;
  node: string;
  status: string;
  cpu_cores: number | null;
  memory_bytes: number | null;
  disk_bytes: number | null;
  excluded: boolean;
  schedule_cron: string | null;
  schedule_enabled: boolean;
  last_tested_at: string | null;
  next_due_at: string | null;
};

/** Friendly presets → UTC cron. Empty string = use global fleet rotation. */
const SCHEDULE_PRESETS: { value: string; label: string; hint: string }[] = [
  { value: "", label: "Fleet default", hint: "Rotates with everyone else on Schedule" },
  { value: "0 2 * * *", label: "Daily at 2:00 UTC", hint: "Only due once per day" },
  { value: "0 3 * * 0", label: "Sundays at 3:00 UTC", hint: "Weekly restore drill" },
  { value: "0 4 1 * *", label: "1st of month, 4:00 UTC", hint: "Monthly restore drill" },
  { value: "__custom__", label: "Custom cron…", hint: "Advanced: five-field UTC cron" },
];

function guestStatusClass(status: string): string {
  const s = status.toLowerCase();
  if (s === "running") return "running";
  if (s === "stopped") return "stopped";
  return "other";
}

function formatDue(iso: string | null | undefined): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function formatBytes(n: number | null | undefined): string {
  if (n == null || n < 0 || Number.isNaN(n)) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = n;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  const digits = i <= 1 ? 0 : v >= 10 ? 0 : 1;
  return `${v.toFixed(digits)} ${units[i]}`;
}

function describeCron(cron: string, display: TimeDisplay = "utc"): string {
  const parsed = cronToBuilder(cron, display);
  if (parsed) return describeBuilder(parsed, display);
  return cron;
}

function presetValueForCron(cron: string | null): string {
  if (!cron) return "";
  const known = SCHEDULE_PRESETS.find((p) => p.value === cron);
  return known ? known.value : "__custom__";
}

function ScheduleOverrideCell({
  guest,
  onSave,
}: {
  guest: Guest;
  onSave: (cron: string | null) => void;
}) {
  const [mode, setMode] = useState(() => presetValueForCron(guest.schedule_cron));
  const [customCron, setCustomCron] = useState(guest.schedule_cron || "");

  useEffect(() => {
    setMode(presetValueForCron(guest.schedule_cron));
    setCustomCron(guest.schedule_cron || "");
  }, [guest.schedule_cron, guest.id]);

  const isCustom = mode === "__custom__";
  const activeCron = guest.schedule_cron;
  const preset = SCHEDULE_PRESETS.find((p) => p.value === mode);

  function applyMode(next: string) {
    setMode(next);
    if (next === "__custom__") {
      setCustomCron(guest.schedule_cron || "0 2 * * *");
      return;
    }
    onSave(next || null);
  }

  return (
    <div className="sched-override">
      {guest.excluded ? (
        <div className="sched-override-muted">Skipped (excluded)</div>
      ) : (
        <>
          <select
            className="sched-override-select"
            value={mode}
            aria-label={`Test schedule for ${guest.name}`}
            onChange={(e) => applyMode(e.target.value)}
          >
            {SCHEDULE_PRESETS.map((p) => (
              <option key={p.value || "fleet"} value={p.value}>
                {p.label}
              </option>
            ))}
          </select>

          {isCustom && (
            <input
              className="mono sched-override-cron"
              placeholder="min hour day month weekday"
              value={customCron}
              onChange={(e) => setCustomCron(e.target.value)}
              onBlur={() => {
                const v = customCron.trim();
                onSave(v || null);
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  (e.target as HTMLInputElement).blur();
                }
              }}
            />
          )}

          <div className="sched-override-hint">
            {activeCron ? (
              <>
                <span>{describeCron(activeCron)}</span>
                {guest.next_due_at ? (
                  <span className="sched-override-due"> · next {formatDue(guest.next_due_at)}</span>
                ) : null}
              </>
            ) : (
              <span>{preset?.hint || "Uses the Schedule page rotation"}</span>
            )}
          </div>
        </>
      )}
    </div>
  );
}

export function GuestsPage() {
  const [guests, setGuests] = useState<Guest[]>([]);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState<number | null>(null);
  const navigate = useNavigate();

  async function load() {
    setGuests(await api<Guest[]>("/guests"));
  }

  useEffect(() => {
    load().catch((e) => setError(e.message));
  }, []);

  async function patch(id: number, body: Partial<Guest>) {
    setError("");
    try {
      await api(`/guests/${id}`, { method: "PATCH", body: JSON.stringify(body) });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Update failed");
    }
  }

  async function runNow(id: number) {
    setError("");
    setBusyId(id);
    try {
      await api<{ id: number }>(`/guests/${id}/run`, { method: "POST" });
      navigate("/");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Run failed");
      setBusyId(null);
    }
  }

  return (
    <div>
      <h1 className="page-title">Guests</h1>
      <p className="page-sub">
        Inventory from your Proxmox hosts. Specs refresh when you{" "}
        <Link to="/hosts">sync a host</Link>. Nightly restore drills are configured on{" "}
        <Link to="/schedule">Schedule</Link> — use <strong>Test schedule</strong> only if one guest
        should run on a different cadence.
      </p>
      {error && <p className="error">{error}</p>}

      <div className="card table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th>VMID</th>
              <th>Name</th>
              <th>Type</th>
              <th>CPUs</th>
              <th>RAM</th>
              <th>Disk</th>
              <th>Host</th>
              <th>Exclude</th>
              <th>
                <span className="label-with-tip">
                  Test schedule
                  <span className="tip-wrap tip-wrap--end">
                    <button type="button" className="tip-btn" aria-label="About test schedule">
                      ?
                    </button>
                    <span className="tip-bubble tip-bubble--wide" role="tooltip">
                      <strong>When should this guest get a restore test?</strong>
                      <p>
                        Most guests should stay on <em>Fleet default</em>. RestoreProof then picks
                        the next overdue guest(s) each time the global schedule fires — see{" "}
                        <Link to="/schedule">Schedule</Link> for batch size and cadence.
                      </p>
                      <p>
                        Pick a preset (or custom cron) only if this guest must be eligible on its{" "}
                        <em>own</em> clock — for example, always Sunday mornings — instead of waiting
                        its turn in the rotation.
                      </p>
                      <ul>
                        <li>
                          <strong>Does nothing</strong> until Schedule is enabled.
                        </li>
                        <li>
                          <strong>Does not</strong> change Proxmox backups — only restore drills.
                        </li>
                        <li>
                          <strong>Run now</strong> always works, regardless of this setting.
                        </li>
                        <li>
                          <strong>Exclude</strong> removes the guest from auto-tests entirely.
                        </li>
                      </ul>
                    </span>
                  </span>
                </span>
              </th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {guests.map((g) => (
              <tr key={g.id} className={g.excluded ? "row-excluded" : undefined}>
                <td className="mono">{g.vmid}</td>
                <td>
                  {g.name}
                  {g.status ? (
                    <div className={`guest-status ${guestStatusClass(g.status)}`}>{g.status}</div>
                  ) : null}
                </td>
                <td>
                  <span className="badge">{g.guest_type}</span>
                </td>
                <td className="mono">{g.cpu_cores ?? "—"}</td>
                <td className="mono">{formatBytes(g.memory_bytes)}</td>
                <td className="mono">{formatBytes(g.disk_bytes)}</td>
                <td>
                  {g.host_name}
                  <div className="help">{g.node}</div>
                </td>
                <td>
                  <input
                    type="checkbox"
                    checked={g.excluded}
                    title="Exclude from automatic restore tests"
                    onChange={(e) => patch(g.id, { excluded: e.target.checked })}
                  />
                </td>
                <td>
                  <ScheduleOverrideCell
                    guest={g}
                    onSave={(cron) => patch(g.id, { schedule_cron: cron } as Partial<Guest>)}
                  />
                </td>
                <td className="row-actions">
                  <button
                    className="btn small"
                    type="button"
                    disabled={busyId === g.id}
                    onClick={() => runNow(g.id)}
                  >
                    {busyId === g.id ? "Starting…" : "Run now"}
                  </button>
                </td>
              </tr>
            ))}
            {!guests.length && (
              <tr>
                <td colSpan={10} className="help">
                  No guests yet. Add a host and sync inventory. <Link to="/hosts">Hosts</Link>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
