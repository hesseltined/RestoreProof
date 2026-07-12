/**
 * Purpose: Restore run history and evidence viewer.
 * Author: Doug Hesseltine
 * Created: 2026-07-12
 * Version: 1.0.0
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
                  <span
                    className={`badge ${
                      r.status === "success" ? "ok" : r.status === "failed" ? "fail" : "run"
                    }`}
                  >
                    {r.status}
                  </span>
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
        <span
          className={`badge ${
            run.status === "success" ? "ok" : run.status === "failed" ? "fail" : "run"
          }`}
        >
          {run.status}
        </span>
      </h1>
      <p className="page-sub">
        {run.source_name} ({run.source_vmid}) → test {run.test_vmid ?? "—"} · {run.guest_type}
      </p>
      {msg && <p className="success">{msg}</p>}
      {error && <p className="error">{error}</p>}
      <div className="grid-2">
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Details</h3>
          <p className="mono">{run.backup_volid || "No backup volid"}</p>
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

