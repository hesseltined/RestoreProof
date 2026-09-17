/**
 * Purpose: SMTP presets, push (ntfy) delivery, and notification templates.
 * Author: Doug Hesseltine
 * Created: 2026-07-12
 * Modified: 2026-09-17
 * Version: 1.10.0
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
  public_base_url: string;
  gap_alert_enabled: boolean;
  gap_alert_hours: number;
  gap_alert_last_sent_at?: string | null;
  email_success_subject: string;
  email_failure_subject: string;
  email_success_body: string;
  email_failure_body: string;
};

type Push = {
  enabled: boolean;
  provider: string;
  url: string;
  verify_ssl: boolean;
  on_success: boolean;
  on_failure: boolean;
  token_set: boolean;
  push_ok_at?: string | null;
};

type Heartbeat = {
  enabled: boolean;
  url: string;
  interval_seconds: number;
  verify_ssl: boolean;
  last_ping_at?: string | null;
  last_error: string;
};

/** Random topic name so an unauthenticated public ntfy topic stays private. */
function suggestTopic(): string {
  const rand = Math.random().toString(36).slice(2, 10);
  return `https://ntfy.sh/restoreproof-${rand}`;
}

type Note = { tone: "ok" | "err"; text: string } | null;

function CardNote({ note }: { note: Note }) {
  if (!note) return null;
  return (
    <p className={note.tone === "ok" ? "test-flash" : "test-flash err"} role="status">
      {note.text}
    </p>
  );
}

function formatWhen(iso: string | null | undefined): string {
  if (!iso) return "never";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

export function NotificationsPage() {
  const [presets, setPresets] = useState<Preset[]>([]);
  const [smtp, setSmtp] = useState<Smtp | null>(null);
  const [password, setPassword] = useState("");
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [push, setPush] = useState<Push | null>(null);
  const [pushToken, setPushToken] = useState("");
  const [beat, setBeat] = useState<Heartbeat | null>(null);
  // Card-scoped feedback: a message at the top of the page is off-screen while
  // you are working in a card further down.
  const [smtpNote, setSmtpNote] = useState<Note>(null);
  const [pushNote, setPushNote] = useState<Note>(null);
  const [beatNote, setBeatNote] = useState<Note>(null);
  const [smtpBusy, setSmtpBusy] = useState(false);
  const [pushBusy, setPushBusy] = useState(false);
  const [beatBusy, setBeatBusy] = useState(false);
  const [testTo, setTestTo] = useState("");
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([
      api<Preset[]>("/smtp/presets"),
      api<Smtp>("/smtp"),
      api<AppSettings>("/settings"),
      api<Push>("/push"),
      api<Heartbeat>("/heartbeat"),
    ])
      .then(([p, s, a, pu, hb]) => {
        setPresets(p);
        setSmtp(s);
        setSettings(a);
        setPush(pu);
        setBeat(hb);
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
    setSmtpNote(null);
    setSmtpBusy(true);
    try {
      await api("/smtp/test", { method: "POST", body: JSON.stringify({ to_email: testTo }) });
      const updated = await api<Smtp>("/smtp");
      setSmtp(updated);
      setSmtpNote({
        tone: "ok",
        text: `Test email sent to ${testTo}. Check that inbox.`,
      });
    } catch (err) {
      setSmtpNote({
        tone: "err",
        text: err instanceof Error ? err.message : "Test failed",
      });
    } finally {
      setSmtpBusy(false);
    }
  }

  /** Persist the form. The test endpoints read saved settings, so tests save first. */
  async function persistPush(current: Push): Promise<Push> {
    const body = { ...current, token: pushToken || undefined };
    const updated = await api<Push>("/push", { method: "PUT", body: JSON.stringify(body) });
    setPush(updated);
    setPushToken("");
    return updated;
  }

  async function savePush(e: FormEvent) {
    e.preventDefault();
    if (!push) return;
    setPushNote(null);
    try {
      const updated = await persistPush(push);
      setPushNote({
        tone: "ok",
        text:
          updated.enabled && !updated.url.trim()
            ? "Saved. Add a topic URL to start receiving pushes."
            : "Push settings saved.",
      });
    } catch (err) {
      setPushNote({ tone: "err", text: err instanceof Error ? err.message : "Save failed" });
    }
  }

  async function sendPushTest() {
    if (!push) return;
    setPushNote(null);
    setPushBusy(true);
    try {
      await persistPush(push);
      await api("/push/test", { method: "POST" });
      setPush((p) => (p ? { ...p, push_ok_at: new Date().toISOString() } : p));
      setPushNote({ tone: "ok", text: "Test push sent. Check the ntfy app." });
    } catch (err) {
      setPushNote({
        tone: "err",
        text: err instanceof Error ? err.message : "Push test failed",
      });
    } finally {
      setPushBusy(false);
    }
  }

  async function persistBeat(current: Heartbeat): Promise<Heartbeat> {
    const updated = await api<Heartbeat>("/heartbeat", {
      method: "PUT",
      body: JSON.stringify(current),
    });
    setBeat(updated);
    return updated;
  }

  async function saveBeat(e: FormEvent) {
    e.preventDefault();
    if (!beat) return;
    setBeatNote(null);
    try {
      const updated = await persistBeat(beat);
      setBeatNote({
        tone: "ok",
        text:
          updated.enabled && !updated.url.trim()
            ? "Saved. Add a ping URL to start sending heartbeats."
            : "Heartbeat settings saved.",
      });
    } catch (err) {
      setBeatNote({ tone: "err", text: err instanceof Error ? err.message : "Save failed" });
    }
  }

  async function sendBeatTest() {
    if (!beat) return;
    setBeatNote(null);
    setBeatBusy(true);
    try {
      await persistBeat(beat);
      await api("/heartbeat/test", { method: "POST" });
      setBeat(await api<Heartbeat>("/heartbeat"));
      setBeatNote({
        tone: "ok",
        text: "Ping sent. Your monitor should show a heartbeat.",
      });
    } catch (err) {
      setBeatNote({ tone: "err", text: err instanceof Error ? err.message : "Ping failed" });
      try {
        setBeat(await api<Heartbeat>("/heartbeat"));
      } catch {
        /* keep the existing view if the refresh also fails */
      }
    } finally {
      setBeatBusy(false);
    }
  }

  if (!smtp || !settings || !push || !beat) return <p className="help">Loading…</p>;

  return (
    <div>
      <h1 className="page-title">Notifications</h1>
      <p className="page-sub">
        SMTP and ntfy for restore results. A scheduled night sends one report with passed and
        failed restores color-coded. A gap alert fires if the schedule is on and nothing finishes.
      </p>
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
              className={`btn ${smtpNote?.tone === "ok" && !smtpBusy ? "sent" : "secondary"}`}
              type="button"
              disabled={!testTo || smtpBusy}
              onClick={sendTest}
            >
              {smtpBusy ? "Sending…" : smtpNote?.tone === "ok" ? "Sent" : "Send test"}
            </button>
          </div>
          <CardNote note={smtpNote} />
          {smtp.smtp_ok_at && !smtpNote ? (
            <p className="help">Last test email: {formatWhen(smtp.smtp_ok_at)}</p>
          ) : null}
        </form>
      </div>

      <form className="card" onSubmit={savePush}>
        <h3 style={{ marginTop: 0 }}>Phone push notifications (ntfy)</h3>
        <p className="help" style={{ marginTop: 0 }}>
          Free alternative to SMS. Install the{" "}
          <a href="https://ntfy.sh/app" target="_blank" rel="noreferrer">
            ntfy app
          </a>{" "}
          on your phone, subscribe to the topic below, and restore results arrive as push
          notifications that open straight to the run. Anyone who knows a public topic name can
          read it, so keep the random suffix or self-host with an access token.
        </p>
        <label>
          <input
            type="checkbox"
            checked={push.enabled}
            onChange={(e) => setPush({ ...push, enabled: e.target.checked })}
          />{" "}
          Send push notifications
        </label>
        <div className="field" style={{ marginTop: "1rem" }}>
          <label>Topic URL</label>
          <div className="row-actions">
            <input
              placeholder="https://ntfy.sh/restoreproof-4f2b9c"
              value={push.url}
              onChange={(e) => setPush({ ...push, url: e.target.value })}
              style={{ flex: 1, minWidth: "260px" }}
            />
            <button
              className="btn small secondary"
              type="button"
              onClick={() => setPush({ ...push, url: suggestTopic() })}
            >
              Generate
            </button>
          </div>
          <p className="help">
            {push.url ? (
              <>
                Subscribe to this topic in the ntfy app, then save and send a test.{" "}
                {push.push_ok_at ? "Last test delivered successfully." : "Not tested yet."}
              </>
            ) : (
              <>Click Generate for a private random topic, or paste your own ntfy topic URL.</>
            )}
          </p>
        </div>
        <div className="field">
          <label>
            Access token {push.token_set ? "(set — blank keeps it, “-” clears it)" : "(optional)"}
          </label>
          <input
            type="password"
            placeholder="tk_… for protected or self-hosted topics"
            value={pushToken}
            onChange={(e) => setPushToken(e.target.value)}
          />
        </div>
        <div className="row-actions" style={{ marginBottom: "1rem" }}>
          <label>
            <input
              type="checkbox"
              checked={push.on_failure}
              onChange={(e) => setPush({ ...push, on_failure: e.target.checked })}
            />{" "}
            Push on failure
          </label>
          <label>
            <input
              type="checkbox"
              checked={push.on_success}
              onChange={(e) => setPush({ ...push, on_success: e.target.checked })}
            />{" "}
            Push on success
          </label>
          <label>
            <input
              type="checkbox"
              checked={push.verify_ssl}
              onChange={(e) => setPush({ ...push, verify_ssl: e.target.checked })}
            />{" "}
            Verify TLS
          </label>
        </div>
        <div className="row-actions">
          <button className="btn" type="submit">
            Save push settings
          </button>
          <button
            className={`btn ${pushNote?.tone === "ok" && !pushBusy ? "sent" : "secondary"}`}
            type="button"
            disabled={!push.url.trim() || pushBusy}
            title={
              push.url.trim()
                ? "Publish a test notification to the topic"
                : "Add a topic URL first"
            }
            onClick={sendPushTest}
          >
            {pushBusy ? "Sending…" : pushNote?.tone === "ok" ? "Sent" : "Send test push"}
          </button>
        </div>
        <CardNote note={pushNote} />
        {!push.url.trim() && (
          <p className="help">Add a topic URL to enable testing. Sending a test also saves.</p>
        )}
      </form>

      <form className="card" onSubmit={saveBeat}>
        <h3 style={{ marginTop: 0 }}>Worker heartbeat (dead-man's switch)</h3>
        <p className="help" style={{ marginTop: 0 }}>
          Alerts above only fire while RestoreProof is running — a stopped worker looks exactly
          like “no failures”. The worker pings this URL after every healthy loop; your monitor
          raises the alarm when the pings stop. Works with an Uptime Kuma <strong>Push</strong>
          {" "}monitor, Healthchecks.io, or Cronitor. Set the monitor's expected interval a little
          longer than the value below.
        </p>
        <label>
          <input
            type="checkbox"
            checked={beat.enabled}
            onChange={(e) => setBeat({ ...beat, enabled: e.target.checked })}
          />{" "}
          Send heartbeat pings
        </label>
        <div className="field" style={{ marginTop: "1rem" }}>
          <label>Ping URL</label>
          <input
            placeholder="http://192.168.1.10:3001/api/push/AbC123"
            value={beat.url}
            onChange={(e) => setBeat({ ...beat, url: e.target.value })}
          />
          <p className="help">
            In Uptime Kuma: add a monitor, set type to <strong>Push</strong>, then copy its push
            URL. Use the monitor's host address and port — a container name only resolves if it
            shares a Docker network with RestoreProof, which separate stacks do not.
          </p>
        </div>
        <div className="field">
          <label>Ping every (seconds)</label>
          <input
            type="number"
            min={30}
            max={86400}
            value={beat.interval_seconds}
            onChange={(e) =>
              setBeat({ ...beat, interval_seconds: Number(e.target.value) || 300 })
            }
          />
        </div>
        <div className="row-actions" style={{ marginBottom: "1rem" }}>
          <label>
            <input
              type="checkbox"
              checked={beat.verify_ssl}
              onChange={(e) => setBeat({ ...beat, verify_ssl: e.target.checked })}
            />{" "}
            Verify TLS
          </label>
        </div>
        <p className="help">
          Last successful ping: <strong>{formatWhen(beat.last_ping_at)}</strong>
          {beat.last_error ? (
            <>
              {" "}
              · last error: <span className="error">{beat.last_error}</span>
            </>
          ) : null}
        </p>
        <div className="row-actions">
          <button className="btn" type="submit">
            Save heartbeat settings
          </button>
          <button
            className={`btn ${beatNote?.tone === "ok" && !beatBusy ? "sent" : "secondary"}`}
            type="button"
            disabled={!beat.url.trim() || beatBusy}
            title={beat.url.trim() ? "Ping the monitor now" : "Add a ping URL first"}
            onClick={sendBeatTest}
          >
            {beatBusy ? "Sending…" : beatNote?.tone === "ok" ? "Sent" : "Ping now"}
          </button>
        </div>
        <CardNote note={beatNote} />
        {!beat.url.trim() && (
          <p className="help">Add a ping URL to enable testing. “Ping now” also saves.</p>
        )}
      </form>

      <form className="card" onSubmit={saveNotify}>
        <h3 style={{ marginTop: 0 }}>Restore gap alert</h3>
        <p className="help" style={{ marginTop: 0 }}>
          The heartbeat above only proves the worker process is running. This email and push fire
          when the schedule is on and no restore test has finished for the hours below. 26 hours
          catches a missed nightly tick.
        </p>
        <label>
          <input
            type="checkbox"
            checked={settings.gap_alert_enabled !== false}
            onChange={(e) =>
              setSettings({ ...settings, gap_alert_enabled: e.target.checked })
            }
          />{" "}
          Alert when scheduled restores go silent
        </label>
        <div className="field" style={{ marginTop: "1rem" }}>
          <label>Hours without a restore</label>
          <input
            type="number"
            min={1}
            max={168}
            value={settings.gap_alert_hours ?? 26}
            onChange={(e) =>
              setSettings({
                ...settings,
                gap_alert_hours: Math.max(1, Number(e.target.value) || 26),
              })
            }
          />
        </div>
        <p className="help">
          Last gap alert: <strong>{formatWhen(settings.gap_alert_last_sent_at)}</strong>
        </p>
        <div className="row-actions">
          <button className="btn" type="submit">
            Save gap alert
          </button>
        </div>
      </form>

      <form className="card" onSubmit={saveNotify}>
        <h3 style={{ marginTop: 0 }}>Email templates</h3>
        <p className="help" style={{ marginTop: 0 }}>
          HTML templates with inline styles. Use <code>{"{{proof_section}}"}</code> to embed VM
          console screenshots (QEMU) or container status proof (LXC). Proof is generated
          automatically. Scheduled restores wait until that tick finishes, then send one report
          with passed and failed rows color-coded. Run now still mails immediately.
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
          <label>Public URL for email links</label>
          <input
            placeholder="https://restoreproof.technologist.services"
            value={settings.public_base_url || ""}
            onChange={(e) => setSettings({ ...settings, public_base_url: e.target.value })}
          />
          <p className="help">
            Used for Open links in restore emails. Must be the live HTTPS URL, not localhost.
            Leave blank to use the server <code>APP_BASE_URL</code> environment variable.
          </p>
        </div>
        <div className="field">
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
