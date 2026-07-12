/**
 * Purpose: App settings — boot wait, retention, branding.
 * Author: Doug Hesseltine
 * Created: 2026-07-12
 * Version: 1.0.0
 */

import { FormEvent, useEffect, useState } from "react";
import { api } from "../api";

type Settings = {
  branding_title: string;
  boot_wait_seconds: number;
  retention_days: number;
  retention_max_runs: number;
};

export function SettingsPage() {
  const [form, setForm] = useState<Settings | null>(null);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

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
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    }
  }

  if (!form) return <p className="help">Loading…</p>;

  return (
    <div>
      <h1 className="page-title">Settings</h1>
      <p className="page-sub">Boot wait, evidence retention, and branding.</p>
      {msg && <p className="success">{msg}</p>}
      {error && <p className="error">{error}</p>}
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
