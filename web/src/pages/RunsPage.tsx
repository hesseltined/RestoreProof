/**
 * Purpose: Restore run history and evidence viewer.
 * Author: Doug Hesseltine
 * Created: 2026-07-12
 * Modified: 2026-07-12
 * Version: 1.1.0
 */

import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { AuthenticatedImage } from "../components/AuthenticatedImage";

type Run = {
  id: number;
  source_name: string;
  source_vmid: number;
  test_vmid: number | null;
  guest_type: string;
  backup_volid: string;
  backup_count?: number | null;
  backup_used_index?: number | null;
  latest_backup_volid?: string;
  used_fallback_backup?: boolean;
  backups_attempted?: number;
  result_summary?: string;
  status: string;
  trigger: string;
  error_message: string | null;
  evidence_kind: string;
  evidence_json: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  log_text?: string;
};

function statusBadgeClass(status: string, usedFallback?: boolean): string {
  if (status === "failed") return "fail";
  if (status === "success" && usedFallback) return "warn";
  if (status === "success") return "ok";
  return "run";
}

function statusLabel(status: string, usedFallback?: boolean): string {
  if (status === "success" && usedFallback) return "success (older backup)";
  return status;
}

export function RunsPage() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    api<Run[]>("/runs")
      .then(setRuns)
      .catch((e) => setError(e.message));
  }, []);

  return (
    <div>
      <h1 className="page-title">Runs</h1>
      <p className="page-sub">History of restore drills with console evidence.</p>
      {error && <p className="error">{error}</p>}
      <div className="card table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th>ID</th>
              <th>Guest</th>
              <th>Test ID</th>
              <th>Status</th>
              <th>Backup</th>
              <th>Trigger</th>
              <th>Created</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.id}>
                <td>
                  <Link to={`/runs/${r.id}`}>#{r.id}</Link>
                </td>
                <td>
                  {r.source_name} <span className="mono">({r.source_vmid})</span>
                </td>
                <td className="mono">{r.test_vmid ?? "—"}</td>
                <td>
                  <span className={`badge ${statusBadgeClass(r.status, r.used_fallback_backup)}`}>
                    {statusLabel(r.status, r.used_fallback_backup)}
                  </span>
                </td>
                <td className="help">
                  {r.backup_count != null ? (
                    <>
                      {r.backup_used_index ?? "—"}/{r.backup_count}
                      {r.used_fallback_backup ? " · not latest" : ""}
                    </>
                  ) : (
                    "—"
                  )}
                </td>
                <td>{r.trigger}</td>
                <td>{new Date(r.created_at).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function RunDetailPage() {
  const { id } = useParams();
  const [run, setRun] = useState<Run | null>(null);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  useEffect(() => {
    api<Run>(`/runs/${id}`)
      .then(setRun)
      .catch((e) => setError(e.message));
  }, [id]);

  async function resend() {
    try {
      await api(`/runs/${id}/resend-email`, { method: "POST" });
      setMsg("Email resent (if SMTP + recipients configured).");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Resend failed");
    }
  }

  if (error && !run) return <p className="error">{error}</p>;
  if (!run) return <p className="help">Loading…</p>;

  const evidenceUrl = `/api/runs/${run.id}/evidence`;

  return (
    <div>
      <p>
        <Link to="/runs">← Runs</Link>
      </p>
      <h1 className="page-title">
        Run #{run.id}{" "}
        <span className={`badge ${statusBadgeClass(run.status, run.used_fallback_backup)}`}>
          {statusLabel(run.status, run.used_fallback_backup)}
        </span>
      </h1>
      <p className="page-sub">
        {run.source_name} ({run.source_vmid}) → test {run.test_vmid ?? "—"} · {run.guest_type}
        {run.backup_count != null
          ? ` · ${run.backup_count} PBS backup${run.backup_count === 1 ? "" : "s"} available`
          : ""}
      </p>
      {msg && <p className="success">{msg}</p>}
      {error && <p className="error">{error}</p>}

      {run.used_fallback_backup && run.status === "success" && (
        <div className="card callout-warn">
          <strong>Not the latest backup</strong>
          <p style={{ marginBottom: 0 }}>
            This run succeeded using backup{" "}
            <span className="mono">
              #{run.backup_used_index} of {run.backup_count}
            </span>{" "}
            because newer snapshot(s) failed. Latest was{" "}
            <span className="mono">{run.latest_backup_volid || "unknown"}</span>.
          </p>
        </div>
      )}

      {run.result_summary && (
        <div className={`card ${run.status === "failed" ? "callout-fail" : run.used_fallback_backup ? "callout-warn" : ""}`}>
          <h3 style={{ marginTop: 0 }}>Diagnostics</h3>
          <pre className="mono result-summary">{run.result_summary}</pre>
        </div>
      )}

      <div className="grid-2">
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Details</h3>
          <p className="mono">{run.backup_volid || "No backup volid"}</p>
          {run.backup_count != null && (
            <p className="help">
              Used backup {run.backup_used_index ?? "—"} of {run.backup_count} available
              {run.used_fallback_backup ? " (fallback — not latest)" : " (latest)"}
              {run.backups_attempted ? ` · attempted ${run.backups_attempted}` : ""}
            </p>
          )}
          {run.latest_backup_volid && run.latest_backup_volid !== run.backup_volid && (
            <p className="help mono">Latest available: {run.latest_backup_volid}</p>
          )}
          {run.error_message && <p className="error">{run.error_message}</p>}
          <button className="btn secondary small" type="button" onClick={resend}>
            Resend email
          </button>
        </div>
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Evidence</h3>
          {run.evidence_kind === "screenshot" && (
            <AuthenticatedImage path={`/runs/${run.id}/evidence`} />
          )}
          {run.evidence_kind === "container_proof" && (
            <pre className="mono">{run.evidence_json}</pre>
          )}
          {run.evidence_kind === "none" && <p className="help">No evidence captured.</p>}
        </div>
      </div>
      <div className="card">
        <h3 style={{ marginTop: 0 }}>Log</h3>
        <pre className="mono" style={{ whiteSpace: "pre-wrap", maxHeight: 400, overflow: "auto" }}>
          {run.log_text || "—"}
        </pre>
      </div>
      <span style={{ display: "none" }}>{evidenceUrl}</span>
    </div>
  );
}
