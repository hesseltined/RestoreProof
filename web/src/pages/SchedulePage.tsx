/**
 * Purpose: Global schedule settings — cadence, batch size, coverage planning.
 * Author: Doug Hesseltine
 * Created: 2026-07-12
 * Modified: 2026-07-31
 * Version: 1.9.0
 */

import { FormEvent, useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import {
  CronScheduleBuilder,
  describeBuilder,
  cronToBuilder,
  localTimeZoneAbbr,
  localTimeZoneName,
  type TimeDisplay,
} from "../components/CronScheduleBuilder";

const TZ_PREF_KEY = "rp_schedule_time_display";
const PANEL_PREF_KEY = "rp_schedule_active_panel";

type SchedulePanel = "timing" | "fleet";

function loadTimeDisplay(): TimeDisplay {
  try {
    const v = localStorage.getItem(TZ_PREF_KEY);
    if (v === "local" || v === "utc") return v;
  } catch {
    /* ignore */
  }
  return "local";
}

function loadActivePanel(): SchedulePanel {
  try {
    const v = localStorage.getItem(PANEL_PREF_KEY);
    if (v === "timing" || v === "fleet") return v;
  } catch {
    /* ignore */
  }
  return "timing";
}

type Settings = {
  global_cron: string;
  schedule_enabled: boolean;
  schedule_batch_size: number;
  schedule_coverage_goal: string;
};

type Plan = {
  total_guests: number;
  excluded_count: number;
  not_backed_up_count?: number;
  no_snapshot_count?: number;
  eligible_count: number;
  schedule_batch_size: number;
  schedule_coverage_goal: string;
  global_cron: string;
  ticks_per_week: number;
  ticks_per_month: number;
  suggested_batch_weekly: number;
  suggested_batch_monthly: number;
  ticks_to_cover_all: number;
  days_to_cover_all_estimate: number;
  cover_weekly_ok: boolean;
  cover_monthly_ok: boolean;
  enqueued_this_window: number;
  window_remaining: number;
  summary: string;
};

type CoverageGoal = "weekly" | "monthly" | "custom";

function timingSummary(cron: string, timeDisplay: TimeDisplay): string {
  const parsed = cronToBuilder(cron, timeDisplay);
  if (parsed) return describeBuilder(parsed, timeDisplay);
  return `Custom cron · ${cron}`;
}

function fleetSummary(form: Settings, plan: Plan | null): string {
  const goal =
    form.schedule_coverage_goal === "weekly"
      ? "cover weekly"
      : form.schedule_coverage_goal === "monthly"
        ? "cover monthly"
        : "custom batch";
  const eligible = plan?.eligible_count;
  const cycle =
    plan && plan.eligible_count > 0
      ? ` · full cycle ~${plan.ticks_to_cover_all} tick${plan.ticks_to_cover_all === 1 ? "" : "s"}`
      : "";
  const fleet =
    eligible !== undefined ? ` · ${eligible} eligible VM${eligible === 1 ? "" : "s"}` : "";
  return `${form.schedule_batch_size}/tick (${goal})${fleet}${cycle}`;
}

export function SchedulePage() {
  const [form, setForm] = useState<Settings>({
    global_cron: "0 2 * * *",
    schedule_enabled: false,
    schedule_batch_size: 1,
    schedule_coverage_goal: "monthly",
  });
  const [plan, setPlan] = useState<Plan | null>(null);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const [timeDisplay, setTimeDisplay] = useState<TimeDisplay>(() => loadTimeDisplay());
  const [activePanel, setActivePanel] = useState<SchedulePanel>(() => loadActivePanel());

  function changeTimeDisplay(next: TimeDisplay) {
    setTimeDisplay(next);
    try {
      localStorage.setItem(TZ_PREF_KEY, next);
    } catch {
      /* ignore */
    }
  }

  function openPanel(panel: SchedulePanel) {
    setActivePanel(panel);
    try {
      localStorage.setItem(PANEL_PREF_KEY, panel);
    } catch {
      /* ignore */
    }
  }

  const loadPlan = useCallback(async () => {
    setPlan(await api<Plan>("/schedule/plan"));
  }, []);

  useEffect(() => {
    Promise.all([api<Settings>("/settings"), api<Plan>("/schedule/plan")])
      .then(([s, p]) => {
        setForm({
          global_cron: s.global_cron,
          schedule_enabled: s.schedule_enabled,
          schedule_batch_size: s.schedule_batch_size ?? 1,
          schedule_coverage_goal: (s.schedule_coverage_goal as CoverageGoal) || "monthly",
        });
        setPlan(p);
      })
      .catch((e) => setError(e.message));
  }, []);

  function applyGoal(goal: CoverageGoal) {
    let batch = form.schedule_batch_size;
    if (goal === "weekly" && plan) batch = plan.suggested_batch_weekly;
    if (goal === "monthly" && plan) batch = plan.suggested_batch_monthly;
    if (goal === "custom" && batch < 1) batch = 1;
    const next = { ...form, schedule_coverage_goal: goal, schedule_batch_size: batch };
    setForm(next);
    previewLocalPlan(next);
  }

  function previewLocalPlan(next: Settings) {
    if (!plan) return;
    const eligible = plan.eligible_count;
    const batch = Math.max(1, next.schedule_batch_size);
    const ticksWeek = plan.ticks_per_week || 7;
    const ticksMonth = plan.ticks_per_month || 30;
    const ticksPerDay = ticksWeek / 7 || 1;
    const ticksToCover = eligible ? Math.ceil(eligible / batch) : 0;
    setPlan({
      ...plan,
      schedule_batch_size: batch,
      schedule_coverage_goal: next.schedule_coverage_goal,
      global_cron: next.global_cron,
      ticks_to_cover_all: ticksToCover,
      days_to_cover_all_estimate: Math.round((ticksToCover / ticksPerDay) * 10) / 10,
      cover_weekly_ok: batch * ticksWeek >= eligible,
      cover_monthly_ok: batch * ticksMonth >= eligible,
      summary:
        eligible === 0
          ? plan.summary
          : `${batch} restore(s) per tick · ${eligible} eligible · ~${ticksToCover} ticks (~${Math.round(
              ticksToCover / ticksPerDay
            )} days) for a full cycle.`,
    });
  }

  async function onSave(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      await api("/settings", {
        method: "PUT",
        body: JSON.stringify({
          global_cron: form.global_cron,
          schedule_enabled: form.schedule_enabled,
          schedule_batch_size: form.schedule_batch_size,
          schedule_coverage_goal: form.schedule_coverage_goal,
        }),
      });
      await api("/guests/refresh-schedule", { method: "POST" });
      await loadPlan();
      setMsg("Schedule saved.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    }
  }

  const timingOpen = activePanel === "timing";
  const fleetOpen = activePanel === "fleet";

  return (
    <div>
      <h1 className="page-title">Schedule</h1>
      <p className="page-sub">
        Pick when restore ticks fire, and how many guests to test each tick so your fleet rotates on
        the timeline you want. Excluded guests are left out of the counts.
      </p>
      {msg && <p className="success">{msg}</p>}
      {error && <p className="error">{error}</p>}

      <form className="card" onSubmit={onSave}>
        <div className="field">
          <label>
            <input
              type="checkbox"
              checked={form.schedule_enabled}
              onChange={(e) => setForm({ ...form, schedule_enabled: e.target.checked })}
            />{" "}
            Enable scheduled restore tests
          </label>
        </div>

        <div className="schedule-panels">
          {/* Panel 1 — basic timing / cron */}
          <section className={`schedule-panel ${timingOpen ? "open" : "collapsed"}`}>
            <button
              type="button"
              className="schedule-panel-head"
              aria-expanded={timingOpen}
              onClick={() => openPanel("timing")}
            >
              <div className="schedule-panel-titles">
                <span className="schedule-panel-kicker">Option 1</span>
                <strong>When batches start</strong>
                <span className="help">
                  Basic schedule — daily, weekdays, or a cron expression
                </span>
              </div>
              <div className="schedule-panel-meta">
                {!timingOpen && (
                  <span className="schedule-panel-preview mono">
                    {timingSummary(form.global_cron, timeDisplay)}
                  </span>
                )}
                <span className="schedule-panel-chevron" aria-hidden>
                  {timingOpen ? "▾" : "▸"}
                </span>
              </div>
            </button>

            {timingOpen && (
              <div className="schedule-panel-body">
                <div className="schedule-tz-row">
                  <label className="help" style={{ marginBottom: 0 }}>
                    Cadence
                  </label>
                  <div className="schedule-tz-toggle" role="group" aria-label="Time display zone">
                    <button
                      type="button"
                      className={`btn small ${timeDisplay === "local" ? "" : "secondary"}`}
                      onClick={() => changeTimeDisplay("local")}
                      title={localTimeZoneName()}
                    >
                      Local ({localTimeZoneAbbr()})
                    </button>
                    <button
                      type="button"
                      className={`btn small ${timeDisplay === "utc" ? "" : "secondary"}`}
                      onClick={() => changeTimeDisplay("utc")}
                    >
                      UTC
                    </button>
                  </div>
                </div>
                <CronScheduleBuilder
                  value={form.global_cron}
                  timeDisplay={timeDisplay}
                  onChange={(global_cron) => {
                    const next = { ...form, global_cron };
                    setForm(next);
                    previewLocalPlan(next);
                  }}
                />
              </div>
            )}
          </section>

          {/* Panel 2 — size batch to fleet */}
          <section className={`schedule-panel ${fleetOpen ? "open" : "collapsed"}`}>
            <button
              type="button"
              className="schedule-panel-head"
              aria-expanded={fleetOpen}
              onClick={() => openPanel("fleet")}
            >
              <div className="schedule-panel-titles">
                <span className="schedule-panel-kicker">Option 2</span>
                <strong>Size each tick to your fleet</strong>
                <span className="help">
                  How many VMs per run — cover all guests weekly, monthly, or set a custom batch
                </span>
              </div>
              <div className="schedule-panel-meta">
                {!fleetOpen && (
                  <span className="schedule-panel-preview">{fleetSummary(form, plan)}</span>
                )}
                <span className="schedule-panel-chevron" aria-hidden>
                  {fleetOpen ? "▾" : "▸"}
                </span>
              </div>
            </button>

            {fleetOpen && (
              <div className="schedule-panel-body">
                {plan && (
                  <div className="schedule-plan-card embedded">
                    <div className="setup-step-head">
                      <h3 style={{ marginTop: 0, marginBottom: 0 }}>Fleet snapshot</h3>
                      <Link className="btn secondary small" to="/guests">
                        Manage excludes
                      </Link>
                    </div>
                    <div className="schedule-plan-grid">
                      <div className="stat">
                        <div className="label">Total guests</div>
                        <div className="value">{plan.total_guests}</div>
                      </div>
                      <div className="stat">
                        <div className="label">Excluded</div>
                        <div className="value">{plan.excluded_count}</div>
                      </div>
                      <div className="stat">
                        <div className="label">Not in backup job</div>
                        <div className="value">{plan.not_backed_up_count ?? 0}</div>
                      </div>
                      <div className="stat">
                        <div className="label">No backup yet</div>
                        <div className="value">{plan.no_snapshot_count ?? 0}</div>
                      </div>
                      <div className="stat">
                        <div className="label">Eligible to test</div>
                        <div className="value">{plan.eligible_count}</div>
                      </div>
                      <div className="stat">
                        <div className="label">Suggested / week</div>
                        <div className="value">{plan.suggested_batch_weekly}/tick</div>
                      </div>
                      <div className="stat">
                        <div className="label">Suggested / month</div>
                        <div className="value">{plan.suggested_batch_monthly}/tick</div>
                      </div>
                      <div className="stat">
                        <div className="label">This tick used</div>
                        <div className="value">
                          {plan.enqueued_this_window}/{plan.schedule_batch_size}
                        </div>
                      </div>
                    </div>
                    <p className="help" style={{ marginTop: "0.75rem" }}>
                      {plan.summary}
                    </p>
                  </div>
                )}

                <label className="help" style={{ display: "block", marginBottom: "0.5rem" }}>
                  Restores per schedule tick
                </label>
                <div className="cron-mode-grid" style={{ marginBottom: "0.75rem" }}>
                  <button
                    type="button"
                    className={`radio-card cron-mode-btn ${
                      form.schedule_coverage_goal === "weekly" ? "active" : ""
                    }`}
                    onClick={() => applyGoal("weekly")}
                  >
                    Cover all weekly
                    <div className="help">≈ {plan?.suggested_batch_weekly ?? "—"} per tick</div>
                  </button>
                  <button
                    type="button"
                    className={`radio-card cron-mode-btn ${
                      form.schedule_coverage_goal === "monthly" ? "active" : ""
                    }`}
                    onClick={() => applyGoal("monthly")}
                  >
                    Cover all monthly
                    <div className="help">≈ {plan?.suggested_batch_monthly ?? "—"} per tick</div>
                  </button>
                  <button
                    type="button"
                    className={`radio-card cron-mode-btn ${
                      form.schedule_coverage_goal === "custom" ? "active" : ""
                    }`}
                    onClick={() => applyGoal("custom")}
                  >
                    Custom batch size
                    <div className="help">Pick any X yourself</div>
                  </button>
                </div>

                <div className="field">
                  <label>Restores per tick (X)</label>
                  <input
                    type="number"
                    min={1}
                    max={500}
                    value={form.schedule_batch_size}
                    onChange={(e) => {
                      const schedule_batch_size = Math.max(1, Number(e.target.value) || 1);
                      const next = {
                        ...form,
                        schedule_batch_size,
                        schedule_coverage_goal: "custom" as CoverageGoal,
                      };
                      setForm(next);
                      previewLocalPlan(next);
                    }}
                  />
                </div>

                {plan && plan.eligible_count > 0 && (
                  <div className="cron-summary">
                    <strong>
                      At {form.schedule_batch_size}/tick → full cycle in ~{plan.ticks_to_cover_all}{" "}
                      tick
                      {plan.ticks_to_cover_all === 1 ? "" : "s"}
                      {plan.days_to_cover_all_estimate
                        ? ` (~${plan.days_to_cover_all_estimate} days)`
                        : ""}
                    </strong>
                    <div className="help">
                      Weekly coverage:{" "}
                      {plan.cover_weekly_ok ? (
                        <span className="badge ok">Yes</span>
                      ) : (
                        <span className="badge fail">No</span>
                      )}{" "}
                      · Monthly coverage:{" "}
                      {plan.cover_monthly_ok ? (
                        <span className="badge ok">Yes</span>
                      ) : (
                        <span className="badge fail">No</span>
                      )}
                    </div>
                  </div>
                )}
              </div>
            )}
          </section>
        </div>

        <div className="row-actions" style={{ marginTop: "1rem" }}>
          <button className="btn" type="submit">
            Save schedule
          </button>
        </div>
      </form>
    </div>
  );
}
