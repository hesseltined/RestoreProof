/**
 * Purpose: Dashboard overview with live restore progress and optional setup wizard.
 * Author: Doug Hesseltine
 * Created: 2026-07-12
 * Modified: 2026-07-22
 * Version: 1.4.0
 */

import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { SetupWizardPanel } from "../components/SetupWizardPanel";

type Run = {
  id: number;
  guest_id?: number | null;
  source_name: string;
  source_vmid: number;
  status: string;
  created_at: string;
  progress_pct?: number | null;
  progress_label?: string | null;
  remediated?: boolean;
  remediated_by_run_id?: number | null;
};

type ActiveRun = {
  id: number;
  status: string;
  source_name: string;
  source_vmid: number;
  guest_type: string;
  test_vmid: number | null;
  progress_pct: number | null;
  progress_label: string | null;
  started_at: string | null;
  created_at: string | null;
};

type Dashboard = {
  schedule_enabled: boolean;
  global_cron: string;
  lock_held: boolean;
  lock_held_by: string | null;
  recent_runs: Run[];
  guest_count: number;
  excluded_count: number;
  host_count: number;
  next_due: { name: string; vmid: number } | null;
  active_run: ActiveRun | null;
};

export function DashboardPage() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState("");
  const [retryBusyId, setRetryBusyId] = useState<number | null>(null);
  const navigate = useNavigate();

  const load = useCallback(async () => {
    const d = await api<Dashboard>("/dashboard");
    setData(d);
    return d;
  }, []);

  useEffect(() => {
    load().catch((e) => setError(e.message));
  }, [load]);

  async function retry(runId: number) {
    setError("");
    setRetryBusyId(runId);
    try {
      const created = await api<{ id: number }>(`/runs/${runId}/retry`, { method: "POST" });
      await load();
      navigate(`/runs/${created.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Retry failed");
      setRetryBusyId(null);
    }
  }
  // Poll while a restore is queued or running
  useEffect(() => {
    if (!data?.active_run) return;
    const id = window.setInterval(() => {
      load().catch(() => {
        /* keep last good snapshot */
      });
    }, 2500);
    return () => window.clearInterval(id);
  }, [data?.active_run?.id, data?.active_run?.status, load]);

  if (error) return <p className="error">{error}</p>;
  if (!data) return <p className="help">Loading dashboard…</p>;

  const active = data.active_run;
  const pct =
    active?.progress_pct != null
      ? Math.max(0, Math.min(100, Math.round(active.progress_pct)))
      : active
        ? active.status === "queued"
          ? 0
          : null
        : null;

  return (
    <div>
      <h1 className="page-title">Dashboard</h1>
      <p className="page-sub">Restore drill status across connected Proxmox hosts.</p>

      <SetupWizardPanel />

      {active && (
        <div className="card restore-progress-card">
          <div className="restore-progress-head">
            <div>
              <div className="label">Restore in progress</div>
              <h3 style={{ margin: "0.15rem 0 0" }}>
                {active.source_name}{" "}
                <span className="mono help">VMID {active.source_vmid}</span>
              </h3>
              <p className="help" style={{ marginBottom: 0 }}>
                {active.progress_label || (active.status === "queued" ? "Queued" : "Working…")}
                {active.test_vmid != null ? ` · test VMID ${active.test_vmid}` : ""}
                {" · "}
                <Link to={`/runs/${active.id}`}>run #{active.id}</Link>
              </p>
            </div>
            <div className="restore-progress-pct">
              {pct != null ? (
                <>
                  <span className="value">{pct}%</span>
                  <span className="badge run">{active.status}</span>
                </>
              ) : (
                <span className="badge run">{active.status}</span>
              )}
            </div>
          </div>
          <div
            className="restore-progress-bar"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={pct ?? undefined}
            aria-label="Restore progress"
          >
            <div
              className={`restore-progress-fill ${pct == null ? "indeterminate" : ""}`}
              style={pct != null ? { width: `${pct}%` } : undefined}
            />
          </div>
        </div>
      )}

      <div className="grid-3">
        <div className="card stat">
          <div className="label">Hosts</div>
          <div className="value">{data.host_count}</div>
        </div>
        <div className="card stat">
          <div className="label">Guests</div>
          <div className="value">{data.guest_count}</div>
        </div>
        <div className="card stat">
          <div className="label">Excluded</div>
          <div className="value">{data.excluded_count}</div>
        </div>
      </div>
      <div className="grid-2">
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Scheduler</h3>
          <p>
            {data.schedule_enabled ? (
              <span className="badge ok">Enabled</span>
            ) : (
              <span className="badge">Disabled</span>
            )}{" "}
            <span className="mono">{data.global_cron}</span>
          </p>
          <p className="help">
            Next due:{" "}
            {data.next_due
              ? `${data.next_due.name} (${data.next_due.vmid})`
              : "None overdue"}
          </p>
          <Link className="btn secondary small" to="/schedule">
            Manage schedule
          </Link>
        </div>
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Global lock</h3>
          <p>
            {data.lock_held ? (
              <span className="badge run">Busy — {data.lock_held_by}</span>
            ) : (
              <span className="badge ok">Idle</span>
            )}
          </p>
          <p className="help">Only one restore test runs at a time.</p>
        </div>
      </div>
      <div className="card">
        <h3 style={{ marginTop: 0 }}>Recent runs</h3>
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>ID</th>
                <th>Guest</th>
                <th>Status</th>
                <th>When</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {data.recent_runs.map((r) => (
                <tr key={r.id}>
                  <td>
                    <Link to={`/runs/${r.id}`}>#{r.id}</Link>
                  </td>
                  <td>
                    {r.source_name} <span className="mono">({r.source_vmid})</span>
                  </td>
                  <td>
                    <span className="run-status-cell">
                      <span
                        className={`badge ${
                          r.status === "success"
                            ? "ok"
                            : r.status === "failed"
                              ? "fail"
                              : "run"
                        }`}
                      >
                        {r.status}
                        {r.status === "running" && r.progress_pct != null
                          ? ` · ${Math.round(r.progress_pct)}%`
                          : ""}
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
              {!data.recent_runs.length && (
                <tr>
                  <td colSpan={5} className="help">
                    No runs yet. Sync a host and use Run now on a guest.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <p className="help" style={{ marginBottom: 0, marginTop: "0.75rem" }}>
          Green ↑ on a recent failure means that guest passed a restore again within a week
          of that failure — the failure is kept for history. Use Retry on open failures to
          re-queue a drill.
        </p>
      </div>
    </div>
  );
}
