/**
 * Purpose: Friendly schedule builder that maps to 5-field UTC cron expressions,
 * with optional local-timezone display for wall-clock times.
 * Author: Doug Hesseltine
 * Created: 2026-07-12
 * Modified: 2026-07-12
 * Version: 1.1.0
 */

import { useEffect, useMemo, useState } from "react";

export type ScheduleMode = "hourly" | "every_n" | "daily" | "weekdays" | "weekly" | "monthly";
export type TimeDisplay = "utc" | "local";

type BuilderState = {
  mode: ScheduleMode;
  minute: number;
  hour: number;
  everyN: number;
  weekdays: number[]; // 0=Sun … 6=Sat (in the active display zone)
  dayOfMonth: number;
};

const WEEKDAY_OPTS = [
  { v: 0, label: "Sun" },
  { v: 1, label: "Mon" },
  { v: 2, label: "Tue" },
  { v: 3, label: "Wed" },
  { v: 4, label: "Thu" },
  { v: 5, label: "Fri" },
  { v: 6, label: "Sat" },
];

const HOUR_OPTS = Array.from({ length: 24 }, (_, h) => h);
const MINUTE_OPTS = [0, 5, 10, 15, 20, 30, 45];
const EVERY_N_OPTS = [2, 3, 4, 6, 8, 12];

function pad2(n: number): string {
  return String(n).padStart(2, "0");
}

export function localTimeZoneName(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "Local";
  } catch {
    return "Local";
  }
}

export function localTimeZoneAbbr(): string {
  try {
    const parts = new Intl.DateTimeFormat(undefined, {
      timeZoneName: "short",
    }).formatToParts(new Date());
    return parts.find((p) => p.type === "timeZoneName")?.value || "local";
  } catch {
    return "local";
  }
}

function zoneLabel(display: TimeDisplay): string {
  return display === "utc" ? "UTC" : localTimeZoneAbbr();
}

/** Map a UTC wall-clock (and optional Dow / Dom) into the browser local zone. */
function utcFieldsToLocal(
  utcHour: number,
  utcMinute: number,
  opts?: { utcDow?: number; utcDom?: number }
): { hour: number; minute: number; dow: number; dom: number } {
  const now = new Date();
  let y = now.getUTCFullYear();
  let mo = now.getUTCMonth();
  let day = opts?.utcDom ?? now.getUTCDate();
  const d = new Date(Date.UTC(y, mo, day, utcHour, utcMinute, 0));
  if (opts?.utcDow !== undefined) {
    const delta = (opts.utcDow - d.getUTCDay() + 7) % 7;
    d.setUTCDate(d.getUTCDate() + delta);
  }
  return {
    hour: d.getHours(),
    minute: d.getMinutes(),
    dow: d.getDay(),
    dom: d.getDate(),
  };
}

/** Map local wall-clock fields into UTC for cron storage. */
function localFieldsToUtc(
  localHour: number,
  localMinute: number,
  opts?: { localDow?: number; localDom?: number }
): { hour: number; minute: number; dow: number; dom: number } {
  const now = new Date();
  let y = now.getFullYear();
  let mo = now.getMonth();
  let day = opts?.localDom ?? now.getDate();
  const d = new Date(y, mo, day, localHour, localMinute, 0);
  if (opts?.localDow !== undefined) {
    const delta = (opts.localDow - d.getDay() + 7) % 7;
    d.setDate(d.getDate() + delta);
  }
  return {
    hour: d.getUTCHours(),
    minute: d.getUTCMinutes(),
    dow: d.getUTCDay(),
    dom: d.getUTCDate(),
  };
}

function timeLabel(hour: number, minute: number, display: TimeDisplay): string {
  return `${pad2(hour)}:${pad2(minute)} ${zoneLabel(display)}`;
}

/**
 * Parse a UTC cron into builder state expressed in `display` zone.
 */
export function cronToBuilder(cron: string, display: TimeDisplay = "utc"): BuilderState | null {
  const parts = cron.trim().split(/\s+/);
  if (parts.length !== 5) return null;
  const [minS, hourS, domS, monS, dowS] = parts;
  if (monS !== "*") return null;

  const utcMinute = Number(minS);
  if (!Number.isInteger(utcMinute) || utcMinute < 0 || utcMinute > 59) return null;

  const toDisplayHm = (utcH: number, utcM: number) => {
    if (display === "utc") return { hour: utcH, minute: utcM };
    const loc = utcFieldsToLocal(utcH, utcM);
    return { hour: loc.hour, minute: loc.minute };
  };

  // 0 * * * *
  if (hourS === "*" && domS === "*" && dowS === "*") {
    return {
      mode: "hourly",
      minute: utcMinute,
      hour: 2,
      everyN: 6,
      weekdays: [1],
      dayOfMonth: 1,
    };
  }

  // 0 */N * * *
  const everyMatch = /^(\*\/)(\d+)$/.exec(hourS);
  if (everyMatch && domS === "*" && dowS === "*") {
    const everyN = Number(everyMatch[2]);
    if (EVERY_N_OPTS.includes(everyN)) {
      return {
        mode: "every_n",
        minute: utcMinute,
        hour: 2,
        everyN,
        weekdays: [1],
        dayOfMonth: 1,
      };
    }
  }

  const utcHour = Number(hourS);
  if (!Number.isInteger(utcHour) || utcHour < 0 || utcHour > 23) return null;

  // M H * * *
  if (domS === "*" && dowS === "*") {
    const hm = toDisplayHm(utcHour, utcMinute);
    return { mode: "daily", minute: hm.minute, hour: hm.hour, everyN: 6, weekdays: [1], dayOfMonth: 1 };
  }

  // M H * * 1-5
  if (domS === "*" && dowS === "1-5") {
    if (display === "utc") {
      return {
        mode: "weekdays",
        minute: utcMinute,
        hour: utcHour,
        everyN: 6,
        weekdays: [1, 2, 3, 4, 5],
        dayOfMonth: 1,
      };
    }
    // Convert each UTC weekday → local; if they remain Mon–Fri keep weekdays mode.
    const localDays: number[] = [];
    let localHour = utcHour;
    let localMinute = utcMinute;
    for (const utcDow of [1, 2, 3, 4, 5]) {
      const loc = utcFieldsToLocal(utcHour, utcMinute, { utcDow });
      localDays.push(loc.dow);
      localHour = loc.hour;
      localMinute = loc.minute;
    }
    const uniq = [...new Set(localDays)].sort((a, b) => a - b);
    const isWeekdays = uniq.length === 5 && uniq.every((d, i) => d === i + 1);
    return {
      mode: isWeekdays ? "weekdays" : "weekly",
      minute: localMinute,
      hour: localHour,
      everyN: 6,
      weekdays: isWeekdays ? [1, 2, 3, 4, 5] : uniq,
      dayOfMonth: 1,
    };
  }

  // M H * * 0,2,4 or single day
  if (domS === "*" && /^\d+(,\d+)*$/.test(dowS)) {
    const utcWeekdays = dowS.split(",").map(Number);
    if (utcWeekdays.every((d) => d >= 0 && d <= 6)) {
      if (display === "utc") {
        return {
          mode: "weekly",
          minute: utcMinute,
          hour: utcHour,
          everyN: 6,
          weekdays: utcWeekdays,
          dayOfMonth: 1,
        };
      }
      const localDays: number[] = [];
      let localHour = utcHour;
      let localMinute = utcMinute;
      for (const utcDow of utcWeekdays) {
        const loc = utcFieldsToLocal(utcHour, utcMinute, { utcDow });
        localDays.push(loc.dow);
        localHour = loc.hour;
        localMinute = loc.minute;
      }
      return {
        mode: "weekly",
        minute: localMinute,
        hour: localHour,
        everyN: 6,
        weekdays: [...new Set(localDays)].sort((a, b) => a - b),
        dayOfMonth: 1,
      };
    }
  }

  // M H D * *
  if (dowS === "*" && /^\d+$/.test(domS)) {
    const utcDom = Number(domS);
    if (utcDom >= 1 && utcDom <= 28) {
      if (display === "utc") {
        return {
          mode: "monthly",
          minute: utcMinute,
          hour: utcHour,
          everyN: 6,
          weekdays: [1],
          dayOfMonth: utcDom,
        };
      }
      const loc = utcFieldsToLocal(utcHour, utcMinute, { utcDom });
      const dayOfMonth = Math.min(28, Math.max(1, loc.dom));
      return {
        mode: "monthly",
        minute: loc.minute,
        hour: loc.hour,
        everyN: 6,
        weekdays: [1],
        dayOfMonth,
      };
    }
  }

  return null;
}

/**
 * Emit UTC cron from builder state expressed in `display` zone.
 */
export function builderToCron(state: BuilderState, display: TimeDisplay = "utc"): string {
  const toUtcHm = (hour: number, minute: number) => {
    if (display === "utc") return { hour, minute };
    const u = localFieldsToUtc(hour, minute);
    return { hour: u.hour, minute: u.minute };
  };

  switch (state.mode) {
    case "hourly":
      return `${state.minute} * * * *`;
    case "every_n":
      return `${state.minute} */${state.everyN} * * *`;
    case "daily": {
      const { hour, minute } = toUtcHm(state.hour, state.minute);
      return `${minute} ${hour} * * *`;
    }
    case "weekdays": {
      if (display === "utc") {
        return `${state.minute} ${state.hour} * * 1-5`;
      }
      // Expand Mon–Fri local → UTC days (may leave weekdays mode).
      const utcDays: number[] = [];
      let utcHour = state.hour;
      let utcMinute = state.minute;
      for (const localDow of [1, 2, 3, 4, 5]) {
        const u = localFieldsToUtc(state.hour, state.minute, { localDow });
        utcDays.push(u.dow);
        utcHour = u.hour;
        utcMinute = u.minute;
      }
      const uniq = [...new Set(utcDays)].sort((a, b) => a - b);
      if (uniq.length === 5 && uniq.every((d, i) => d === i + 1)) {
        return `${utcMinute} ${utcHour} * * 1-5`;
      }
      return `${utcMinute} ${utcHour} * * ${uniq.join(",")}`;
    }
    case "weekly": {
      if (display === "utc") {
        const days = [...state.weekdays].sort((a, b) => a - b);
        const dow = days.length ? days.join(",") : "1";
        return `${state.minute} ${state.hour} * * ${dow}`;
      }
      const utcDays: number[] = [];
      let utcHour = state.hour;
      let utcMinute = state.minute;
      for (const localDow of state.weekdays) {
        const u = localFieldsToUtc(state.hour, state.minute, { localDow });
        utcDays.push(u.dow);
        utcHour = u.hour;
        utcMinute = u.minute;
      }
      const uniq = [...new Set(utcDays)].sort((a, b) => a - b);
      const dow = uniq.length ? uniq.join(",") : "1";
      return `${utcMinute} ${utcHour} * * ${dow}`;
    }
    case "monthly": {
      if (display === "utc") {
        return `${state.minute} ${state.hour} ${state.dayOfMonth} * *`;
      }
      const u = localFieldsToUtc(state.hour, state.minute, { localDom: state.dayOfMonth });
      const dom = Math.min(28, Math.max(1, u.dom));
      return `${u.minute} ${u.hour} ${dom} * *`;
    }
    default: {
      const _exhaustive: never = state.mode;
      return _exhaustive;
    }
  }
}

export function describeBuilder(state: BuilderState, display: TimeDisplay = "utc"): string {
  switch (state.mode) {
    case "hourly":
      return `Every hour at minute ${pad2(state.minute)} (UTC clock)`;
    case "every_n":
      return `Every ${state.everyN} hours at minute ${pad2(state.minute)} (UTC clock)`;
    case "daily":
      return `Every day at ${timeLabel(state.hour, state.minute, display)}`;
    case "weekdays":
      return `Monday–Friday at ${timeLabel(state.hour, state.minute, display)}`;
    case "weekly": {
      const labels = WEEKDAY_OPTS.filter((d) => state.weekdays.includes(d.v)).map((d) => d.label);
      return `${labels.join(", ") || "No days"} at ${timeLabel(state.hour, state.minute, display)}`;
    }
    case "monthly":
      return `Day ${state.dayOfMonth} of each month at ${timeLabel(state.hour, state.minute, display)}`;
    default: {
      const _exhaustive: never = state.mode;
      return _exhaustive;
    }
  }
}

const DEFAULT_BUILDER: BuilderState = {
  mode: "daily",
  minute: 0,
  hour: 2,
  everyN: 6,
  weekdays: [1],
  dayOfMonth: 1,
};

type Props = {
  value: string;
  onChange: (cron: string) => void;
  timeDisplay?: TimeDisplay;
};

export function CronScheduleBuilder({ value, onChange, timeDisplay = "utc" }: Props) {
  const parsed = useMemo(() => cronToBuilder(value, timeDisplay), [value, timeDisplay]);
  const [useGui, setUseGui] = useState(true);
  const [builder, setBuilder] = useState<BuilderState>(() => parsed || DEFAULT_BUILDER);
  const [advancedNote, setAdvancedNote] = useState("");

  useEffect(() => {
    const next = cronToBuilder(value, timeDisplay);
    if (next) {
      setBuilder(next);
      setAdvancedNote("");
    } else if (useGui) {
      setAdvancedNote(
        "This cron expression is too custom for the simple builder. Switch to Advanced to edit it, or pick a simple pattern below (that will replace it)."
      );
    }
  }, [value, useGui, timeDisplay]);

  function applyBuilder(next: BuilderState) {
    setBuilder(next);
    setAdvancedNote("");
    onChange(builderToCron(next, timeDisplay));
  }

  function toggleWeekday(day: number) {
    const has = builder.weekdays.includes(day);
    const weekdays = has
      ? builder.weekdays.filter((d) => d !== day)
      : [...builder.weekdays, day];
    applyBuilder({ ...builder, mode: "weekly", weekdays: weekdays.length ? weekdays : [day] });
  }

  const summary = describeBuilder(builder, timeDisplay);
  const hourLabel = timeDisplay === "utc" ? "Hour (UTC)" : `Hour (${localTimeZoneAbbr()})`;
  const tzName = localTimeZoneName();

  return (
    <div className="cron-builder">
      <div className="row-actions" style={{ marginBottom: "0.75rem" }}>
        <button
          type="button"
          className={`btn small ${!useGui ? "" : "secondary"}`}
          onClick={() => setUseGui(false)}
        >
          Cron expression
        </button>
        <button
          type="button"
          className={`btn small ${useGui ? "" : "secondary"}`}
          onClick={() => {
            setUseGui(true);
            const next = cronToBuilder(value, timeDisplay);
            if (next) {
              setBuilder(next);
              setAdvancedNote("");
            } else {
              setAdvancedNote(
                "Current cron is custom. Choosing a simple pattern below will replace it."
              );
            }
          }}
        >
          Simple schedule builder
        </button>
      </div>

      {useGui ? (
        <>
          {advancedNote && <p className="help">{advancedNote}</p>}
          <div className="field">
            <label>How often?</label>
            <div className="cron-mode-grid">
              {(
                [
                  ["hourly", "Every hour"],
                  ["every_n", "Every N hours"],
                  ["daily", "Every day"],
                  ["weekdays", "Weekdays"],
                  ["weekly", "Selected days"],
                  ["monthly", "Monthly"],
                ] as const
              ).map(([mode, label]) => (
                <button
                  key={mode}
                  type="button"
                  className={`radio-card cron-mode-btn ${builder.mode === mode ? "active" : ""}`}
                  onClick={() => applyBuilder({ ...builder, mode })}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          {(builder.mode === "daily" ||
            builder.mode === "weekdays" ||
            builder.mode === "weekly" ||
            builder.mode === "monthly") && (
            <div className="grid-2">
              <div className="field">
                <label>{hourLabel}</label>
                <select
                  value={builder.hour}
                  onChange={(e) => applyBuilder({ ...builder, hour: Number(e.target.value) })}
                >
                  {HOUR_OPTS.map((h) => (
                    <option key={h} value={h}>
                      {pad2(h)}:xx
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label>Minute</label>
                <select
                  value={MINUTE_OPTS.includes(builder.minute) ? builder.minute : builder.minute}
                  onChange={(e) => applyBuilder({ ...builder, minute: Number(e.target.value) })}
                >
                  {!MINUTE_OPTS.includes(builder.minute) && (
                    <option value={builder.minute}>{pad2(builder.minute)}</option>
                  )}
                  {MINUTE_OPTS.map((m) => (
                    <option key={m} value={m}>
                      {pad2(m)}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          )}

          {(builder.mode === "hourly" || builder.mode === "every_n") && (
            <div className="field">
              <label>At minute</label>
              <select
                value={MINUTE_OPTS.includes(builder.minute) ? builder.minute : builder.minute}
                onChange={(e) => applyBuilder({ ...builder, minute: Number(e.target.value) })}
              >
                {!MINUTE_OPTS.includes(builder.minute) && (
                  <option value={builder.minute}>{pad2(builder.minute)}</option>
                )}
                {MINUTE_OPTS.map((m) => (
                  <option key={m} value={m}>
                    :{pad2(m)}
                  </option>
                ))}
              </select>
              <p className="help">Interval schedules align to the UTC clock.</p>
            </div>
          )}

          {builder.mode === "every_n" && (
            <div className="field">
              <label>Every how many hours?</label>
              <select
                value={builder.everyN}
                onChange={(e) => applyBuilder({ ...builder, everyN: Number(e.target.value) })}
              >
                {EVERY_N_OPTS.map((n) => (
                  <option key={n} value={n}>
                    Every {n} hours
                  </option>
                ))}
              </select>
            </div>
          )}

          {builder.mode === "weekly" && (
            <div className="field">
              <label>Days of the week{timeDisplay === "local" ? ` (${localTimeZoneAbbr()})` : ""}</label>
              <div className="weekday-pills">
                {WEEKDAY_OPTS.map((d) => (
                  <button
                    key={d.v}
                    type="button"
                    className={`weekday-pill ${builder.weekdays.includes(d.v) ? "active" : ""}`}
                    onClick={() => toggleWeekday(d.v)}
                  >
                    {d.label}
                  </button>
                ))}
              </div>
            </div>
          )}

          {builder.mode === "monthly" && (
            <div className="field">
              <label>Day of month</label>
              <select
                value={builder.dayOfMonth}
                onChange={(e) => applyBuilder({ ...builder, dayOfMonth: Number(e.target.value) })}
              >
                {Array.from({ length: 28 }, (_, i) => i + 1).map((d) => (
                  <option key={d} value={d}>
                    {d}
                  </option>
                ))}
              </select>
            </div>
          )}

          <div className="cron-summary">
            <strong>{summary}</strong>
            <div className="help mono">Cron (UTC): {builderToCron(builder, timeDisplay)}</div>
            {timeDisplay === "local" && (
              <div className="help">Times shown in {tzName}. Stored schedule remains UTC.</div>
            )}
          </div>
        </>
      ) : (
        <div className="field">
          <label>Global cron (UTC)</label>
          <input
            className="mono"
            value={value}
            onChange={(e) => onChange(e.target.value)}
            placeholder="0 2 * * *"
          />
          <p className="help">
            Standard 5-field cron: minute hour day-of-month month day-of-week. Example:{" "}
            <code>0 2 * * *</code> = daily at 02:00 UTC.
          </p>
          {parsed && (
            <p className="help">
              Matches simple builder: <em>{describeBuilder(parsed, timeDisplay)}</em>
            </p>
          )}
        </div>
      )}
    </div>
  );
}
