/**
 * Purpose: Shared status step lights (API/SSH/Sync chips).
 * Author: Doug Hesseltine
 * Created: 2026-07-12
 * Modified: 2026-07-12
 * Version: 1.1.0
 */

export type SetupStepItem = {
  n: number;
  label: string;
  ok: boolean;
  active?: boolean;
};

export function SetupStepLight({ n, label, ok, active }: SetupStepItem) {
  return (
    <div className={`host-step ${ok ? "ok" : ""} ${active && !ok ? "active" : ""}`}>
      <span className={`step-light ${ok ? "green" : "red"}`} aria-hidden />
      <span className="step-num">{n}</span>
      <span className="step-label">{label}</span>
    </div>
  );
}

export function SetupSteps({
  steps,
  label = "Status",
}: {
  steps: SetupStepItem[];
  label?: string;
}) {
  return (
    <div className="host-steps" aria-label={label}>
      {steps.map((s) => (
        <SetupStepLight key={s.n} {...s} />
      ))}
    </div>
  );
}
