/**
 * Purpose: Restore run history and evidence viewer.
 * Author: Doug Hesseltine
 * Created: 2026-07-12
 * Modified: 2026-07-31
 * Version: 1.4.0
 */

import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { AuthenticatedImage } from "../components/AuthenticatedImage";

type Run = {
  id: number;
  guest_id?: number | null;
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
  remediated?: boolean;
  remediated_by_run_id?: number | null;
};

type RunPage = {
  items: Run[];
  total: number;
  page: number;
  page_size: number;
};

const PAGE_SIZES = [10, 20, 50, 100] as const;

function statusBadgeClass(status: string, usedFallback?: boolean): string {
  if (status === "failed") return "fail";
  if (status === "skipped") return "muted";
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
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [error, setError] = useState("");
  const [retryBusyId, setRetryBusyId] = useState<number | null>(null);
  const navigate = useNavigate();

  const load = useCallback(async () => {
    const data = await api<RunPage>(`/runs?page=${page}&page_size=${pageSize}`);
    setRuns(data.items);
    setTotal(data.total);
  }, [page, pageSize]);

  useEffect(() => {
    load().catch((e) => setError(e.message));
  }, [load]);

  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(total, page * pageSize);

  async function retry(runId: number) {
    setError("");
    setRetryBusyId(runId);
    try {
      const created = await api<Run>(`/runs/${runId}/retry`, { method: "POST" });
      navigate(`/runs/${created.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Retry failed");
      setRetryBusyId(null);
    }
  }

  function changePageSize(next: number) {
    setPageSize(next);
    setPage(1);
  }

  return (
    <div>
      <h1 className="page-title">Runs</h1>
      <p className="page-sub">History of restore drills with console evidence.</p>
      {error && <p className="error">{error}</p>}

      <div className="pager-bar">
        <label className="pager-size">
          Show
          <select
            value={pageSize}
            onChange={(e) => changePageSize(Number(e.target.value))}
            aria-label="Items per page"
          >
            {PAGE_SIZES.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
          per page
        </label>
        <div className="pager-meta help">
          {total === 0 ? "No runs" : `${from}–${to} of ${total}`}
        </div>
        <div className="pager-nav">
          <button
            className="btn secondary small"
            type="button"
            disabled={page <= 1}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
          >
            ← Prev
          </button>
          <span className="pager-page mono">
            {page} / {totalPages}
          </span>
          <button
            className="btn secondary small"
            type="button"
            disabled={page >= totalPages}
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
          >
            Next →
          </button>
        </div>
      </div>

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
              <th></th>
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
                  <span className="run-status-cell">
                    <span className={`badge ${statusBadgeClass(r.status, r.used_fallback_backup)}`}>
                      {statusLabel(r.status, r.used_fallback_backup)}
                    </span>
                    {r.status === "failed" && r.remediated && (
                      <Link
                        to={
                          r.remediated_by_run_id
                            ? `/runs/${r.remediated_by_run_id}`
                            : `/runs/${r.id}`
                        }
                        className="remediated-mark"
                        title={
                          r.remediated_by_run_id
                            ? `Remediated — this guest passed on run #${r.remediated_by_run_id}`
                            : "Remediated — later restore succeeded"
                        }
                        aria-label={
                          r.remediated_by_run_id
                            ? `Remediated by run ${r.remediated_by_run_id}`
                            : "Remediated"
                        }
                      >
                        <span aria-hidden>↑</span>
                      </Link>
                    )}
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
                <td className="row-actions">
                  {r.status === "failed" && !r.remediated && (
                    <button
                      className="btn small"
                      type="button"
                      disabled={retryBusyId === r.id || !r.guest_id}
                      title={
                        r.guest_id
                          ? "Queue another restore drill for this guest"
                          : "Guest no longer in inventory"
                      }
                      onClick={() => retry(r.id)}
                    >
                      {retryBusyId === r.id ? "Retrying…" : "Retry"}
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {!runs.length && (
              <tr>
                <td colSpan={8} className="help">
                  No restore runs yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {totalPages > 1 && (
        <div className="pager-bar pager-bar--bottom">
          <div className="pager-nav">
            <button
              className="btn secondary small"
              type="button"
              disabled={page <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
            >
              ← Prev
            </button>
            <span className="pager-page mono">
              {page} / {totalPages}
            </span>
            <button
              className="btn secondary small"
              type="button"
              disabled={page >= totalPages}
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            >
              Next →
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export function RunDetailPage() {
  const { id } = useParams();
  const [run, setRun] = useState<Run | null>(null);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [retryBusy, setRetryBusy] = useState(false);
  const navigate = useNavigate();

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

  async function retry() {
    if (!run) return;
    setRetryBusy(true);
    setError("");
    try {
      const created = await api<Run>(`/runs/${run.id}/retry`, { method: "POST" });
      navigate(`/runs/${created.id}`);
      // Worker will pick up the queued run; dashboard also shows active progress.
    } catch (e) {
      setError(e instanceof Error ? e.message : "Retry failed");
      setRetryBusy(false);
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
          <div className="run-detail-actions">
            {run.status === "failed" && (
              <button
                className="btn small"
                type="button"
                disabled={retryBusy || !run.guest_id}
                title={
                  run.guest_id
                    ? "Queue another restore drill for this guest"
                    : "Guest no longer in inventory"
                }
                onClick={retry}
              >
                {retryBusy ? "Retrying…" : "Retry restore"}
              </button>
            )}
            <button className="btn secondary small" type="button" onClick={resend}>
              Resend email
            </button>
          </div>
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
