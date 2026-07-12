/**
 * Purpose: Proxmox host connections, API/SSH tests, sync, latest restore evidence.
 * Author: Doug Hesseltine
 * Created: 2026-07-12
 * Modified: 2026-07-12
 * Version: 1.4.0
 */

import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { AuthenticatedImage } from "../components/AuthenticatedImage";
import { SetupSteps } from "../components/SetupSteps";

type LatestRun = {
  id: number;
  status: string;
  source_name: string;
  source_vmid: number;
  guest_type: string;
  evidence_kind: string;
  error_message: string | null;
  finished_at: string | null;
  started_at: string | null;
};

type Host = {
  id: number;
  name: string;
  api_url: string;
  token_id: string;
  ssh_host: string;
  ssh_port: number;
  ssh_user: string;
  preferred_restore_storage: string;
  test_vmid_start: number;
  test_vmid_end: number;
  enabled: boolean;
  last_sync_at: string | null;
  api_ok_at: string | null;
  ssh_ok_at: string | null;
  last_error: string | null;
  has_ssh_key: boolean;
  latest_run: LatestRun | null;
};

type SshPanel = {
  hostId: number;
  public_key: string;
  install_command: string;
  instructions: string;
};

const emptyForm = {
  name: "",
  api_url: "",
  token_id: "",
  token_secret: "",
  verify_ssl: false,
  ssh_host: "",
  ssh_port: 22,
  ssh_user: "root",
  preferred_restore_storage: "",
  test_vmid_start: 9000,
  test_vmid_end: 9099,
};

async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

function LatestEvidence({ run }: { run: LatestRun | null }) {
  if (!run) {
    return (
      <div className="host-evidence empty">
        <p className="help">No restore tests yet</p>
      </div>
    );
  }

  if (run.status === "failed") {
    return (
      <div className="host-evidence failed">
        <span className="badge fail">Failed</span>
        <div className="host-evidence-meta">
          <strong>{run.source_name}</strong>
          <div className="help mono">VMID {run.source_vmid} · run #{run.id}</div>
          <p className="error host-evidence-error">
            {run.error_message || "Restore test failed"}
          </p>
          <Link className="btn secondary small" to={`/runs/${run.id}`}>
            View run
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="host-evidence ok">
      <span className="badge ok">Success</span>
      <div className="host-evidence-meta">
        <strong>{run.source_name}</strong>
        <div className="help mono">VMID {run.source_vmid} · run #{run.id}</div>
        {run.evidence_kind === "screenshot" && (
          <AuthenticatedImage
            path={`/runs/${run.id}/evidence`}
            alt={`Latest restore screenshot for ${run.source_name}`}
            className="host-evidence-img"
          />
        )}
        {run.evidence_kind === "container_proof" && (
          <p className="help">Container proof captured (LXC — no VGA screenshot).</p>
        )}
        {run.evidence_kind === "none" && <p className="help">No screenshot on this run.</p>}
        <Link className="btn secondary small" to={`/runs/${run.id}`}>
          View run
        </Link>
      </div>
    </div>
  );
}

export function HostsPage() {
  const [hosts, setHosts] = useState<Host[]>([]);
  const [form, setForm] = useState(emptyForm);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [sshPanel, setSshPanel] = useState<SshPanel | null>(null);
  const [copied, setCopied] = useState("");
  const [busyId, setBusyId] = useState<number | null>(null);

  async function load() {
    setHosts(await api<Host[]>("/hosts"));
  }

  useEffect(() => {
    load().catch((e) => setError(e.message));
  }, []);

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      const host = await api<Host>("/hosts", { method: "POST", body: JSON.stringify(form) });
      setForm(emptyForm);
      await load();
      setInfo("Host added. Next: Test API, then install the SSH key and Test SSH.");
      await showKey(host.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Create failed");
    }
  }

  async function showKey(id: number) {
    const res = await api<{
      public_key: string;
      install_command: string;
      instructions: string;
    }>(`/hosts/${id}/ssh-key`);
    setSshPanel({
      hostId: id,
      public_key: res.public_key,
      install_command: res.install_command,
      instructions: res.instructions,
    });
  }

  async function testApi(id: number) {
    setInfo("");
    setError("");
    setBusyId(id);
    try {
      const res = await api<{ ok: boolean; nodes: string[] }>(`/hosts/${id}/test-api`, {
        method: "POST",
      });
      setInfo(`API OK — nodes: ${res.nodes.join(", ")}`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "API test failed");
      await load();
    } finally {
      setBusyId(null);
    }
  }

  async function testSsh(id: number) {
    setInfo("");
    setError("");
    setBusyId(id);
    try {
      const res = await api<{ output: string }>(`/hosts/${id}/test-ssh`, { method: "POST" });
      setInfo(`SSH OK — ${res.output}`);
      await load();
      await showKey(id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "SSH test failed");
      await load();
      await showKey(id);
    } finally {
      setBusyId(null);
    }
  }

  async function sync(id: number) {
    setInfo("");
    setError("");
    setBusyId(id);
    try {
      const res = await api<{ synced: number }>(`/hosts/${id}/sync`, { method: "POST" });
      setInfo(`Synced ${res.synced} guests`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sync failed");
      await load();
    } finally {
      setBusyId(null);
    }
  }

  async function remove(id: number) {
    if (!confirm("Delete this host connection?")) return;
    await api(`/hosts/${id}`, { method: "DELETE" });
    if (sshPanel?.hostId === id) setSshPanel(null);
    await load();
  }

  async function onCopy(label: string, text: string) {
    const ok = await copyText(text);
    setCopied(ok ? label : "");
    if (ok) setTimeout(() => setCopied(""), 2000);
  }

  return (
    <div>
      <h1 className="page-title">Hosts</h1>
      <p className="page-sub">
        Connect Proxmox API endpoints (standalone or cluster). SSH is used for VM console screenshots.
      </p>
      {error && <p className="error">{error}</p>}
      {info && <p className="success">{info}</p>}

      <div className="card">
        <h3 style={{ marginTop: 0 }}>Add host</h3>
        <form onSubmit={onCreate} className="grid-2">
          <div className="field">
            <label>Name</label>
            <input
              required
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
            />
          </div>
          <div className="field">
            <label>API URL</label>
            <input
              required
              placeholder="https://10.250.0.11:8006"
              value={form.api_url}
              onChange={(e) => setForm({ ...form, api_url: e.target.value })}
            />
          </div>
          <div className="field">
            <label className="label-with-tip">
              API token ID
              <span className="tip-wrap">
                <button type="button" className="tip-btn" aria-label="How to create an API token">
                  ?
                </button>
                <span className="tip-bubble" role="tooltip">
                  <strong>Create a Proxmox API token</strong>
                  <ol>
                    <li>Open the Proxmox UI → <em>Datacenter → Permissions → API Tokens</em>.</li>
                    <li>Click <em>Add</em>. User: <code>root@pam</code> (or a dedicated user).</li>
                    <li>Token ID: e.g. <code>restoreproof</code> (short name only).</li>
                    <li>Leave Privilege Separation unchecked for a simple start.</li>
                    <li>Copy the secret immediately — Proxmox shows it only once.</li>
                  </ol>
                  Paste Token ID as <code>user@realm!tokenid</code>, e.g.{" "}
                  <code>root@pam!restoreproof</code>.
                </span>
              </span>
            </label>
            <input
              required
              placeholder="root@pam!restoreproof"
              value={form.token_id}
              onChange={(e) => setForm({ ...form, token_id: e.target.value })}
            />
          </div>
          <div className="field">
            <label>API token secret</label>
            <input
              required
              type="password"
              value={form.token_secret}
              onChange={(e) => setForm({ ...form, token_secret: e.target.value })}
            />
          </div>
          <div className="field">
            <label>SSH host</label>
            <input
              value={form.ssh_host}
              onChange={(e) => setForm({ ...form, ssh_host: e.target.value })}
            />
          </div>
          <div className="field">
            <label>Preferred restore storage</label>
            <input
              placeholder="optional — e.g. restore-test"
              value={form.preferred_restore_storage}
              onChange={(e) =>
                setForm({ ...form, preferred_restore_storage: e.target.value })
              }
            />
          </div>
          <div className="field">
            <label>Test VMID start</label>
            <input
              type="number"
              value={form.test_vmid_start}
              onChange={(e) =>
                setForm({ ...form, test_vmid_start: Number(e.target.value) })
              }
            />
          </div>
          <div className="field">
            <label>Test VMID end</label>
            <input
              type="number"
              value={form.test_vmid_end}
              onChange={(e) => setForm({ ...form, test_vmid_end: Number(e.target.value) })}
            />
          </div>
          <div>
            <button className="btn" type="submit">
              Add host
            </button>
          </div>
        </form>
      </div>

      {hosts.map((h) => {
        const apiOk = Boolean(h.api_ok_at);
        const sshOk = Boolean(h.ssh_ok_at);
        const syncOk = Boolean(h.last_sync_at);
        const nextStep = !apiOk ? 1 : !sshOk ? 2 : !syncOk ? 3 : 0;
        const readyToSync = apiOk && sshOk && !syncOk;

        return (
          <div className={`card host-card ${syncOk ? "host-complete" : ""}`} key={h.id}>
            <div className="host-card-main">
              <LatestEvidence run={h.latest_run} />
              <div className="host-card-body">
                <div className="row-actions" style={{ justifyContent: "space-between" }}>
                  <div>
                    <strong>{h.name}</strong>
                    <div className="help mono">
                      {h.api_url} · pool {h.test_vmid_start}-{h.test_vmid_end}
                    </div>
                    <SetupSteps
                      steps={[
                        { n: 1, label: "API", ok: apiOk, active: nextStep === 1 },
                        { n: 2, label: "SSH", ok: sshOk, active: nextStep === 2 },
                        { n: 3, label: "Sync", ok: syncOk, active: nextStep === 3 },
                      ]}
                    />
                    {h.last_error && <div className="error">{h.last_error}</div>}
                    {readyToSync && (
                      <p className="success" style={{ marginTop: "0.5rem" }}>
                        API and SSH look good — click <strong>Sync guests</strong>.
                      </p>
                    )}
                    {syncOk && (
                      <p className="success" style={{ marginTop: "0.5rem" }}>
                        Guests synced.
                      </p>
                    )}
                  </div>
                  <div className="row-actions">
                    <button
                      className={`btn small ${apiOk ? "secondary" : ""}`}
                      type="button"
                      disabled={busyId === h.id}
                      onClick={() => testApi(h.id)}
                    >
                      {apiOk ? "Retest API" : "1 · Test API"}
                    </button>
                    <button
                      className="btn secondary small"
                      type="button"
                      onClick={() => showKey(h.id)}
                    >
                      SSH key
                    </button>
                    <button
                      className={`btn small ${sshOk ? "secondary" : apiOk ? "" : "secondary"}`}
                      type="button"
                      disabled={busyId === h.id}
                      onClick={() => testSsh(h.id)}
                    >
                      {sshOk ? "Retest SSH" : "2 · Test SSH"}
                    </button>
                    <button
                      className={`btn small ${readyToSync || syncOk ? "" : "secondary"}`}
                      type="button"
                      disabled={busyId === h.id || !apiOk || !sshOk}
                      onClick={() => sync(h.id)}
                      title={!apiOk || !sshOk ? "Complete Test API and Test SSH first" : undefined}
                    >
                      3 · Sync guests
                    </button>
                    <button className="btn danger small" type="button" onClick={() => remove(h.id)}>
                      Delete
                    </button>
                  </div>
                </div>

                {sshPanel?.hostId === h.id && (
                  <div className="ssh-panel">
                    <h4 style={{ margin: "1rem 0 0.35rem" }}>SSH public key install</h4>
                    <p className="help">{sshPanel.instructions}</p>
                    <label className="help">Run this from your admin machine (Mac/PC):</label>
                    <div className="copy-cmd">
                      <code className="mono">{sshPanel.install_command}</code>
                      <button
                        className="btn secondary small"
                        type="button"
                        onClick={() => onCopy("cmd", sshPanel.install_command)}
                      >
                        {copied === "cmd" ? "Copied" : "Copy"}
                      </button>
                    </div>
                    <details className="ssh-key-details">
                      <summary>Show public key only</summary>
                      <div className="copy-cmd">
                        <code className="mono">{sshPanel.public_key}</code>
                        <button
                          className="btn secondary small"
                          type="button"
                          onClick={() => onCopy("key", sshPanel.public_key)}
                        >
                          {copied === "key" ? "Copied" : "Copy"}
                        </button>
                      </div>
                    </details>
                  </div>
                )}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
