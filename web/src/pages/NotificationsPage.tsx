/**
 * Purpose: SMTP presets + notification templates.
 * Author: Doug Hesseltine
 * Created: 2026-07-12
 * Modified: 2026-07-12
 * Version: 1.4.0
 */

import { FormEvent, useEffect, useMemo, useState } from "react";
import { api } from "../api";

type Preset = {
  id: string;
  label: string;
  host: string;
  port: number;
  use_tls: boolean;
  use_ssl: boolean;
  fields: string[];
  help: string;
  username?: string;
};

type Smtp = {
  provider: string;
  host: string;
  port: number;
  use_tls: boolean;
  use_ssl: boolean;
  username: string;
  from_email: string;
  from_name: string;
  password_set: boolean;
  smtp_ok_at?: string | null;
};

type AppSettings = {
  notify_on_success: boolean;
  notify_on_failure: boolean;
  notify_to: string;
  notify_cc: string;
  email_success_subject: string;
  email_failure_subject: string;
  email_success_body: string;
  email_failure_body: string;
};

export function NotificationsPage() {
  const [presets, setPresets] = useState<Preset[]>([]);
  const [smtp, setSmtp] = useState<Smtp | null>(null);
  const [password, setPassword] = useState("");
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [testTo, setTestTo] = useState("");
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([
      api<Preset[]>("/smtp/presets"),
      api<Smtp>("/smtp"),
      api<AppSettings>("/settings"),
    ])
      .then(([p, s, a]) => {
        setPresets(p);
        setSmtp(s);
        setSettings(a);
        setTestTo(a.notify_to.split(",")[0] || "");
      })
      .catch((e) => setError(e.message));
  }, []);

  const activePreset = useMemo(
    () => presets.find((p) => p.id === smtp?.provider) || presets[0],
    [presets, smtp]
  );

  function selectProvider(id: string) {
    if (!smtp) return;
    const preset = presets.find((p) => p.id === id);
    if (!preset) return;
    setSmtp({
      ...smtp,
      provider: id,
      host: preset.host || smtp.host,
      port: preset.port,
      use_tls: preset.use_tls,
      use_ssl: preset.use_ssl,
      username: preset.username || smtp.username,
    });
  }

  function show(field: string) {
    return !activePreset || activePreset.fields.includes(field);
  }

  async function saveSmtp(e: FormEvent) {
    e.preventDefault();
    if (!smtp) return;
    setError("");
    try {
      const body = { ...smtp, password: password || undefined };
      const updated = await api<Smtp>("/smtp", { method: "PUT", body: JSON.stringify(body) });
      setSmtp(updated);
      setPassword("");
      setMsg("SMTP settings saved.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    }
  }

  async function saveNotify(e: FormEvent) {
    e.preventDefault();
    if (!settings) return;
    await api("/settings", { method: "PUT", body: JSON.stringify(settings) });
    setMsg("Notification preferences saved.");
  }

  async function resetTemplates() {
    if (!settings) return;
    setError("");
    try {
      const updated = await api<AppSettings>("/settings/email-templates/reset", {
        method: "POST",
      });
      setSettings(updated);
      setMsg("Applied colorful default email templates.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Reset failed");
    }
  }

  async function sendTest() {
    setError("");
    try {
      await api("/smtp/test", { method: "POST", body: JSON.stringify({ to_email: testTo }) });
      setMsg("Test email sent.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Test failed");
    }
  }

  if (!smtp || !settings) return <p className="help">Loading…</p>;

  return (
    <div>
      <h1 className="page-title">Notifications</h1>
      <p className="page-sub">SMTP delivery with provider presets. Webhooks coming later.</p>
      {msg && <p className="success">{msg}</p>}
      {error && <p className="error">{error}</p>}

      <div className="card">
        <h3 style={{ marginTop: 0 }}>SMTP provider</h3>
        <div className="radio-grid">
          {presets.map((p) => (
            <label
              key={p.id}
              className={`radio-card ${smtp.provider === p.id ? "active" : ""}`}
            >
              <input
                type="radio"
                name="provider"
                checked={smtp.provider === p.id}
                onChange={() => selectProvider(p.id)}
              />{" "}
              {p.label}
            </label>
          ))}
        </div>
        <p className="help">{activePreset?.help}</p>
        <form onSubmit={saveSmtp}>
          {show("host") && (
            <div className="field">
              <label>Host</label>
              <input
                value={smtp.host}
                onChange={(e) => setSmtp({ ...smtp, host: e.target.value })}
              />
            </div>
          )}
          {show("port") && (
            <div className="field">
              <label>Port</label>
              <input
                type="number"
                value={smtp.port}
                onChange={(e) => setSmtp({ ...smtp, port: Number(e.target.value) })}
              />
            </div>
          )}
          {show("username") && (
            <div className="field">
              <label>Username</label>
              <input
                value={smtp.username}
                onChange={(e) => setSmtp({ ...smtp, username: e.target.value })}
              />
            </div>
          )}
          {show("password") && (
            <div className="field">
              <label>Password {smtp.password_set ? "(set — leave blank to keep)" : ""}</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>
          )}
          {show("from_email") && (
            <div className="field">
              <label>From email</label>
              <input
                value={smtp.from_email}
                onChange={(e) => setSmtp({ ...smtp, from_email: e.target.value })}
              />
            </div>
          )}
          {show("from_name") && (
            <div className="field">
              <label>From name</label>
              <input
                value={smtp.from_name}
                onChange={(e) => setSmtp({ ...smtp, from_name: e.target.value })}
              />
            </div>
          )}
          {(show("use_tls") || show("use_ssl")) && (
            <div className="row-actions" style={{ marginBottom: "1rem" }}>
              {show("use_tls") && (
                <label>
                  <input
                    type="checkbox"
                    checked={smtp.use_tls}
                    onChange={(e) => setSmtp({ ...smtp, use_tls: e.target.checked })}
                  />{" "}
                  STARTTLS
                </label>
              )}
              {show("use_ssl") && (
                <label>
                  <input
                    type="checkbox"
                    checked={smtp.use_ssl}
                    onChange={(e) => setSmtp({ ...smtp, use_ssl: e.target.checked })}
                  />{" "}
                  SSL
                </label>
              )}
            </div>
          )}
          <div className="row-actions">
            <button className="btn" type="submit">
              Save SMTP
            </button>
            <input
              placeholder="test recipient"
              value={testTo}
              onChange={(e) => setTestTo(e.target.value)}
              style={{ minWidth: "220px" }}
            />
            <button
              className="btn secondary"
              type="button"
              disabled={!testTo}
              onClick={sendTest}
            >
              Send test
            </button>
          </div>
        </form>
      </div>

      <form className="card" onSubmit={saveNotify}>
        <h3 style={{ marginTop: 0 }}>Email templates</h3>
        <p className="help" style={{ marginTop: 0 }}>
          HTML templates with inline styles. Use <code>{"{{proof_section}}"}</code> to embed VM
          console screenshots (QEMU) or container status proof (LXC). Proof is generated
          automatically — you do not need different templates per guest type.
        </p>
        <h3 style={{ marginTop: "1.25rem" }}>When to notify</h3>
        <label>
          <input
            type="checkbox"
            checked={settings.notify_on_success}
            onChange={(e) => setSettings({ ...settings, notify_on_success: e.target.checked })}
          />{" "}
          Success
        </label>
        <br />
        <label>
          <input
            type="checkbox"
            checked={settings.notify_on_failure}
            onChange={(e) => setSettings({ ...settings, notify_on_failure: e.target.checked })}
          />{" "}
          Failure
        </label>
        <div className="field" style={{ marginTop: "1rem" }}>
          <label>To (comma-separated)</label>
          <input
            value={settings.notify_to}
            onChange={(e) => setSettings({ ...settings, notify_to: e.target.value })}
          />
        </div>
        <div className="field">
          <label>CC</label>
          <input
            value={settings.notify_cc}
            onChange={(e) => setSettings({ ...settings, notify_cc: e.target.value })}
          />
        </div>
        <div className="field">
          <label>Success subject</label>
          <input
            value={settings.email_success_subject}
            onChange={(e) =>
              setSettings({ ...settings, email_success_subject: e.target.value })
            }
          />
        </div>
        <div className="field">
          <label>Success body (HTML)</label>
          <textarea
            rows={14}
            value={settings.email_success_body}
            onChange={(e) => setSettings({ ...settings, email_success_body: e.target.value })}
          />
        </div>
        <div className="field">
          <label>Failure subject</label>
          <input
            value={settings.email_failure_subject}
            onChange={(e) =>
              setSettings({ ...settings, email_failure_subject: e.target.value })
            }
          />
        </div>
        <div className="field">
          <label>Failure body (HTML)</label>
          <textarea
            rows={14}
            value={settings.email_failure_body}
            onChange={(e) => setSettings({ ...settings, email_failure_body: e.target.value })}
          />
        </div>
        <p className="help">
          Variables: guest_name, vmid, guest_type, guest_type_label, test_vmid, backup_volid,
          backup_count, backup_used_index, latest_backup_volid, used_fallback_backup,
          result_summary, error_message, started_at, finished_at, run_url, status, evidence_kind,
          proof_section
        </p>
        <div className="row-actions">
          <button className="btn" type="submit">
            Save notification settings
          </button>
          <button className="btn secondary" type="button" onClick={resetTemplates}>
            Reset to colorful defaults
          </button>
        </div>
      </form>
    </div>
  );
}
