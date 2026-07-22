/**
 * Purpose: Optional guided setup checklist; re-offers when SECRET_KEY decrypt fails.
 * Author: Doug Hesseltine
 * Created: 2026-07-13
 * Modified: 2026-07-22
 * Version: 1.1.0
 */

import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";

type SetupStep = {
  id: string;
  title: string;
  body: string;
  done: boolean;
  current: boolean;
  to: string;
};

type SetupProgress = {
  steps: SetupStep[];
  completed_count: number;
  total_count: number;
  all_done: boolean;
  next_step_id: string | null;
  next_path: string | null;
  wizard_completed: boolean;
  secrets_need_attention: boolean;
  secrets_message: string | null;
  offer_wizard: boolean;
};

export function SetupWizardPanel({
  alwaysShowShell = false,
}: {
  /**
   * Settings: keep a collapsed card when setup is idle; expand automatically
   * when the wizard needs attention. Dashboard leaves this false (hide when idle).
   */
  alwaysShowShell?: boolean;
}) {
  const [progress, setProgress] = useState<SetupProgress | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [dismissedLocally, setDismissedLocally] = useState(false);
  const [expanded, setExpanded] = useState(false);

  const load = useCallback(async () => {
    const p = await api<SetupProgress>("/setup/progress");
    setProgress(p);
    return p;
  }, []);

  useEffect(() => {
    load().catch((e) => setError(e instanceof Error ? e.message : "Setup progress failed"));
  }, [load]);

  const needsAttention = Boolean(
    progress && (progress.offer_wizard || progress.secrets_need_attention)
  );

  useEffect(() => {
    if (needsAttention) {
      setExpanded(true);
      setDismissedLocally(false);
    } else if (alwaysShowShell) {
      setExpanded(false);
    }
  }, [needsAttention, alwaysShowShell]);

  if (error) {
    return <p className="error">{error}</p>;
  }
  if (!progress) {
    return null;
  }

  const showOnDashboard = needsAttention && !dismissedLocally;
  if (!alwaysShowShell && !showOnDashboard) {
    return null;
  }

  const showBody = alwaysShowShell ? expanded || needsAttention : true;

  async function markComplete() {
    setBusy(true);
    try {
      await api("/setup/wizard/complete", { method: "POST" });
      setDismissedLocally(true);
      setExpanded(false);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not mark complete");
    } finally {
      setBusy(false);
    }
  }

  async function reopen() {
    setBusy(true);
    setDismissedLocally(false);
    setExpanded(true);
    try {
      await api("/setup/wizard/reopen", { method: "POST" });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not reopen wizard");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      className={`card setup-wizard-card ${
        progress.secrets_need_attention ? "setup-wizard-alert" : ""
      } ${!showBody ? "setup-wizard-collapsed" : ""}`}
    >
      <div className="setup-wizard-head">
        <div>
          <h2 className="section-title" style={{ marginBottom: "0.25rem" }}>
            Setup wizard
          </h2>
          <p className="help" style={{ margin: 0 }}>
            {progress.completed_count} of {progress.total_count} steps done
            {progress.wizard_completed ? " · marked complete" : ""}
            {alwaysShowShell && !showBody ? " · collapsed" : ""}
          </p>
        </div>
        <div className="row-actions">
          {alwaysShowShell && (
            <button
              className="btn secondary small"
              type="button"
              disabled={busy}
              onClick={() => setExpanded((v) => !v)}
            >
              {showBody ? "Collapse" : "Expand"}
            </button>
          )}
          {!alwaysShowShell && !progress.secrets_need_attention && (
            <button
              className="btn ghost small"
              type="button"
              disabled={busy}
              onClick={() => setDismissedLocally(true)}
            >
              Hide for now
            </button>
          )}
          {showBody &&
            (progress.wizard_completed && !progress.secrets_need_attention ? (
              <button
                className="btn secondary small"
                type="button"
                disabled={busy}
                onClick={reopen}
              >
                Show again
              </button>
            ) : (
              <button
                className="btn secondary small"
                type="button"
                disabled={busy || !!progress.secrets_need_attention}
                onClick={markComplete}
                title={
                  progress.secrets_need_attention
                    ? "Fix broken secrets before marking complete"
                    : undefined
                }
              >
                Mark setup complete
              </button>
            ))}
        </div>
      </div>

      {showBody && (
        <>
          {progress.secrets_need_attention && progress.secrets_message && (
            <p className="error" style={{ marginTop: "0.75rem" }}>
              {progress.secrets_message}
            </p>
          )}

          <ol className="setup-wizard-list">
            {progress.steps.map((step) => (
              <li
                key={step.id}
                className={`setup-wizard-step ${step.done ? "done" : ""} ${
                  step.current ? "current" : ""
                }`}
              >
                <span className={`setup-wizard-check ${step.done ? "ok" : ""}`} aria-hidden>
                  {step.done ? "✓" : "○"}
                </span>
                <div>
                  <Link to={step.to}>{step.title}</Link>
                  <p className="help" style={{ margin: "0.15rem 0 0" }}>
                    {step.body}
                  </p>
                </div>
              </li>
            ))}
          </ol>
        </>
      )}
    </section>
  );
}
