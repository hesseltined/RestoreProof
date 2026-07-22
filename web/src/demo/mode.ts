/**
 * Purpose: Detect RestoreProof marketing demo mode (/demo path).
 * Author: Doug Hesseltine
 * Created: 2026-07-13
 * Modified: 2026-07-22
 * Version: 1.0.1
 */

/** True when the SPA is served under /demo (public marketing walkthrough). */
export function isDemoMode(): boolean {
  if (typeof window === "undefined") return false;
  const path = window.location.pathname;
  return path === "/demo" || path.startsWith("/demo/");
}

/** React Router basename when in demo mode. */
export function demoBasename(): string | undefined {
  return isDemoMode() ? "/demo" : undefined;
}
