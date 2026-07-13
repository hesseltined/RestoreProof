/**
 * Purpose: App settings — boot wait, retention, branding, config export/import.
 * Author: Doug Hesseltine
 * Created: 2026-07-12
 * Modified: 2026-07-12
 * Version: 1.1.0
 */

import { FormEvent, useEffect, useRef, useState } from "react";
import { api, downloadConfigExport, uploadConfigImport } from "../api";

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

  if (!form) return <p className="help">Loading…</p>;

  return (
    <div>
      <h1 className="page-title">Settings</h1>
      <p className="page-sub">Boot wait, evidence retention, branding, and migration.</p>
      {msg && <p className="success">{msg}</p>}
      {error && <p className="error">{error}</p>}

      <section className="card config-transfer-card">
        <h2 className="section-title">Export / Import configuration</h2>
        <p className="help">
          Save or restore app settings, SMTP, Proxmox hosts, guest schedule overrides, and SSH
          keys when rebuilding or moving RestoreProof to a new VM. Run history and evidence files
          are not included — back up the <code className="mono">rp_data</code> Docker volume for
          those.
        </p>
        <p className="help">
          Encrypted secrets (API tokens, SMTP password) require the same{" "}
          <code className="mono">SECRET_KEY</code> or <code className="mono">ENCRYPTION_KEY</code>{" "}
          in <code className="mono">.env</code> on the target VM.
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
    </div>
  );
}
