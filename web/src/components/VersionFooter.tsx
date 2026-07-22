/**
 * Purpose: Small-print RestoreProof version (UI + API health when reachable).
 * Author: Doug Hesseltine
 * Created: 2026-07-12
 * Modified: 2026-07-22
 * Version: 1.3.0
 *
 * TODO: Remove VersionFooter from login/layout when troubleshooting is done
 *       (keep /api/health version only if desired).
 */

import { useEffect, useState } from "react";
import { isDemoMode } from "../demo/mode";
import { demoApiFetch } from "../demo/mockApi";
import { APP_VERSION } from "../version";

type ApiHealth = {
  status?: string;
  version?: string;
};

type Variant = "auth" | "app";

export function VersionFooter({ variant = "app" }: { variant?: Variant }) {
  const [apiVersion, setApiVersion] = useState<string | null>(null);
  const [apiOk, setApiOk] = useState<boolean | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = isDemoMode()
      ? demoApiFetch("/health").then(async (res) => {
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          return (await res.json()) as ApiHealth;
        })
      : fetch("/api/health").then(async (res) => {
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          return (await res.json()) as ApiHealth;
        });

    load
      .then((data) => {
        if (cancelled) return;
        setApiOk(true);
        setApiVersion(data.version || "unknown");
      })
      .catch(() => {
        if (cancelled) return;
        setApiOk(false);
        setApiVersion(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const apiLabel =
    apiOk === null
      ? "API …"
      : apiOk
        ? `API v${apiVersion}`
        : "API unreachable";

  return (
    <p className={`version-footer version-footer--${variant}`} aria-label="Application version">
      <strong>v{APP_VERSION}</strong>
      <span className="version-footer-sep" aria-hidden="true">
        ·
      </span>
      UI
      <span className="version-footer-sep" aria-hidden="true">
        ·
      </span>
      <span className={apiOk === false ? "version-footer-warn" : undefined}>{apiLabel}</span>
      {isDemoMode() && (
        <>
          <span className="version-footer-sep" aria-hidden="true">
            ·
          </span>
          <span>demo</span>
        </>
      )}
    </p>
  );
}
