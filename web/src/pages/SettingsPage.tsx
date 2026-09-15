/**
 * Purpose: App settings — boot wait, retention, branding, config export/import, setup wizard.
 * Author: Doug Hesseltine
 * Created: 2026-07-12
 * Modified: 2026-07-30
 * Version: 1.4.0
 */

import { FormEvent, useEffect, useRef, useState } from "react";
import { api, downloadConfigExport, uploadConfigImport } from "../api";
import { SetupWizardPanel } from "../components/SetupWizardPanel";

type Settings = {
  branding_title: string;
  boot_wait_seconds: number;
  retention_days: number;
  retention_max_runs: number;
};

type ImportSummary = {
  mode: string;
  hosts_created: number;
  hosts_updated: number;
  guest_overrides_applied: number;
  guest_overrides_pending: number;
  users_created: number;
  users_skipped: number;
};

/** Local date input → ISO midnight UTC for that calendar day (purge before start of day). */
function localDateToUtcIso(dateStr: string): string {
  const [y, m, d] = dateStr.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d, 0, 0, 0)).toISOString();
}

function defaultPurgeDate(): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() - 30);
  return d.toISOString().slice(0, 10);
}

export function SettingsPage() {
  const [form, setForm] = useState<Settings | null>(null);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const [exportUsers, setExportUsers] = useState(false);
  const [exportBusy, setExportBusy] = useState(false);
  const [importMode, setImportMode] = useState<"merge" | "replace">("merge");
  const [importUsers, setImportUsers] = useState(false);
  const [importBusy, setImportBusy] = useState(false);
  const [importSummary, setImportSummary] = useState<ImportSummary | null>(null);
  const [purgeBefore, setPurgeBefore] = useState(defaultPurgeDate);
  const [purgeBusy, setPurgeBusy] = useState(false);
  const [staleBusy, setStaleBusy] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api<Settings>("/settings")
      .then(setForm)
      .catch((e) => setError(e.message));
  }, []);

  async function onSave(e: FormEvent) {
    e.preventDefault();
    if (!form) return;
    try {
      await api("/settings", { method: "PUT", body: JSON.stringify(form) });
      setMsg("Settings saved.");
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    }
  }

  async function onExport() {
    setExportBusy(true);
    setError("");
    setMsg("");
    try {
      await downloadConfigExport(exportUsers);
      setMsg("Configuration exported.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Export failed");
    } finally {
      setExportBusy(false);
    }
  }

  async function onImportFile(e: FormEvent) {
    e.preventDefault();
    const file = fileInputRef.current?.files?.[0];
    if (!file) {
      setError("Choose a RestoreProof export JSON file first.");
      return;
    }
    if (
      importMode === "replace" &&
      !window.confirm(
        "Replace mode deletes all hosts, guests, and run history before import. Continue?"
      )
    ) {
      return;
    }
    setImportBusy(true);
    setError("");
    setMsg("");
    setImportSummary(null);
    try {
      const summary = await uploadConfigImport(file, importMode, importUsers);
      setImportSummary(summary);
      setMsg("Configuration imported.");
      if (fileInputRef.current) fileInputRef.current.value = "";
    } catch (err) {
      setError(err instanceof Error ? err.message : "Import failed");
    } finally {
      setImportBusy(false);
    }
  }

  async function onPurgeRuns() {
    if (!purgeBefore) {
      setError("Choose a cutoff date first.");
      return;
    }
    const label = new Date(localDateToUtcIso(purgeBefore)).toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
      timeZone: "UTC",
    });
    if (
      !window.confirm(
        `Permanently delete all restore runs (and evidence files) created before ${label} UTC?\n\nThis cannot be undone.`
      )
    ) {
      return;
    }
    setPurgeBusy(true);
    setError("");
    setMsg("");
    try {
      const res = await api<{ deleted: number; before: string }>("/settings/purge-runs", {
        method: "POST",
        body: JSON.stringify({ before: localDateToUtcIso(purgeBefore) }),
      });
      setMsg(
        res.deleted === 0
          ? "No runs matched that cutoff — nothing deleted."
          : `Purged ${res.deleted} run${res.deleted === 1 ? "" : "s"} older than ${label} UTC.`
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Purge failed");
    } finally {
      setPurgeBusy(false);
    }
  }

  async function onPurgeStale() {
    if (
      !window.confirm(
        "Delete restore runs for guests that are no longer on Proxmox (orphaned) and guests not listed in any Proxmox backup job?\n\nThis cannot be undone. Sync hosts first so backup-job membership is current."
      )
    ) {
      return;
    }
    setStaleBusy(true);
    setError("");
    setMsg("");
    try {
      const res = await api<{
        deleted: number;
        orphaned_deleted: number;
        not_backed_up_deleted: number;
      }>("/settings/purge-stale-runs", {
        method: "POST",
        body: JSON.stringify({ orphaned: true, not_backed_up: true }),
      });
      if (res.deleted === 0) {
        setMsg("No stale runs found — nothing deleted.");
      } else {
        setMsg(
          `Purged ${res.deleted} stale run${res.deleted === 1 ? "" : "s"} ` +
            `(${res.orphaned_deleted} orphaned, ${res.not_backed_up_deleted} not in backup job).`
        );
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Stale purge failed");
    } finally {
      setStaleBusy(false);
    }
  }

  if (!form) return <p className="help">Loading…</p>;

  return (
    <div>
      <h1 className="page-title">Settings</h1>
      <p className="page-sub">Boot wait, evidence retention, branding, and migration.</p>
      {msg && <p className="success">{msg}</p>}
      {error && <p className="error">{error}</p>}

      <SetupWizardPanel alwaysShowShell />

      <section className="card config-transfer-card">
        <h2 className="section-title">Export / Import configuration</h2>
        <p className="help">
          Save or restore app settings, SMTP, Proxmox hosts, guest schedule overrides, and SSH
          keys when rebuilding or moving RestoreProof to a new VM. Run history and evidence files
          are not included — back up the <code className="mono">rp_data</code> Docker volume for
          those.
        </p>
        <p className="help">
          Encrypted secrets (API tokens, SMTP password) require the{" "}
          <strong>same</strong> <code className="mono">SECRET_KEY</code> on the target
          (Portainer: <code className="mono">API_SECRET_KEY</code> /{" "}
          <code className="mono">WORKER_SECRET_KEY</code>, identical values). If you rotate the
          key on a new server, re-enter every Proxmox token secret and SMTP password after
          import — otherwise Test API fails with a decrypt error.
        </p>

        <div className="config-transfer-grid">
          <div className="config-transfer-panel">
            <h3>Export</h3>
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={exportUsers}
                onChange={(e) => setExportUsers(e.target.checked)}
              />
              Include admin users (password hashes and 2FA secrets)
            </label>
            <button
              className="btn"
              type="button"
              disabled={exportBusy}
              onClick={onExport}
            >
              {exportBusy ? "Exporting…" : "Download configuration"}
            </button>
          </div>

          <form className="config-transfer-panel" onSubmit={onImportFile}>
            <h3>Import</h3>
            <div className="field">
              <label>Mode</label>
              <select
                value={importMode}
                onChange={(e) => setImportMode(e.target.value as "merge" | "replace")}
              >
                <option value="merge">Merge — update matching hosts by name</option>
                <option value="replace">
                  Replace — remove all hosts, guests, and runs first
                </option>
              </select>
            </div>
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={importUsers}
                onChange={(e) => setImportUsers(e.target.checked)}
              />
              Import users (skip emails that already exist)
            </label>
            <div className="field">
              <label>Configuration file</label>
              <input ref={fileInputRef} type="file" accept=".json,application/json" />
            </div>
            <button className="btn" type="submit" disabled={importBusy}>
              {importBusy ? "Importing…" : "Import configuration"}
            </button>
          </form>
        </div>

        {importSummary && (
          <div className="import-summary">
            <p>
              Hosts: {importSummary.hosts_created} created, {importSummary.hosts_updated}{" "}
              updated. Guest overrides: {importSummary.guest_overrides_applied} applied
              {importSummary.guest_overrides_pending > 0
                ? `, ${importSummary.guest_overrides_pending} pending (sync guests on Hosts page)`
                : ""}
              .
              {importSummary.users_created + importSummary.users_skipped > 0
                ? ` Users: ${importSummary.users_created} created, ${importSummary.users_skipped} skipped.`
                : ""}
            </p>
          </div>
        )}
      </section>

      <form className="card" onSubmit={onSave}>
        <div className="field">
          <label>Branding title</label>
          <input
            value={form.branding_title}
            onChange={(e) => setForm({ ...form, branding_title: e.target.value })}
          />
        </div>
        <div className="field">
          <label>Boot wait before screenshot (seconds)</label>
          <input
            type="number"
            min={10}
            value={form.boot_wait_seconds}
            onChange={(e) =>
              setForm({ ...form, boot_wait_seconds: Number(e.target.value) })
            }
          />
        </div>
        <div className="field">
          <label>Retention days</label>
          <input
            type="number"
            min={1}
            value={form.retention_days}
            onChange={(e) => setForm({ ...form, retention_days: Number(e.target.value) })}
          />
        </div>
        <div className="field">
          <label>Max runs kept</label>
          <input
            type="number"
            min={10}
            value={form.retention_max_runs}
            onChange={(e) =>
              setForm({ ...form, retention_max_runs: Number(e.target.value) })
            }
          />
          <p className="help">Latest run per guest is always retained.</p>
        </div>
        <button className="btn" type="submit">
          Save
        </button>
      </form>

      <section className="card purge-runs-card">
        <h2 className="section-title">Purge run history</h2>
        <p className="help">
          Permanently delete restore drill results and evidence files older than a cutoff date.
          Automatic retention (above) still runs on its own schedule — this is a one-shot admin
          cleanup.
        </p>
        <div className="purge-runs-row">
          <div className="field">
            <label>Delete runs created before (UTC date)</label>
            <input
              type="date"
              value={purgeBefore}
              max={new Date().toISOString().slice(0, 10)}
              onChange={(e) => setPurgeBefore(e.target.value)}
            />
          </div>
          <button
            className="btn danger"
            type="button"
            disabled={purgeBusy || !purgeBefore}
            onClick={onPurgeRuns}
          >
            {purgeBusy ? "Purging…" : "Purge older runs"}
          </button>
        </div>
      </section>

      <section className="card purge-runs-card">
        <h2 className="section-title">Purge stale restore results</h2>
        <p className="help">
          Remove drill history for guests that are gone from Proxmox (orphaned after inventory sync)
          or not listed in any Proxmox backup job. Sync hosts first so membership is up to date.
          Does not delete Proxmox/PBS backups — only RestoreProof run history and evidence files.
        </p>
        <button
          className="btn danger"
          type="button"
          disabled={staleBusy}
          onClick={onPurgeStale}
        >
          {staleBusy ? "Purging…" : "Purge orphaned & not-backed-up runs"}
        </button>
      </section>
    </div>
  );
}
