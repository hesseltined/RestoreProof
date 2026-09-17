/**
 * Purpose: Banner when GitHub or Docker Hub has a newer RestoreProof than this install.
 * Author: Doug Hesseltine
 * Created: 2026-09-17
 * Modified: 2026-09-17
 * Version: 1.0.0
 */

import { useEffect, useState } from "react";
import { api } from "../api";
import { isDemoMode } from "../demo/mode";

export type UpdateStatus = {
  current_version: string;
  latest_version: string | null;
  update_available: boolean;
  dismissed: boolean;
  release_url: string | null;
  notes: string;
  source: string | null;
  last_checked_at: string | null;
  check_enabled: boolean;
  upgrade: {
    portainer: string;
    compose: string;
    git: string;
  };
  error?: string | null;
};

export function fetchUpdates(refresh = false) {
  const q = refresh ? "?refresh=true" : "";
  return api<UpdateStatus>(`/updates${q}`);
}

export function UpdateBanner() {
  const [info, setInfo] = useState<UpdateStatus | null>(null);
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (isDemoMode()) return;
    let cancelled = false;
    fetchUpdates()
      .then((data) => {
        if (!cancelled) setInfo(data);
      })
      .catch(() => {
        /* GitHub/Hub down — stay quiet */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!info || !info.update_available || info.dismissed || !info.check_enabled) {
    return null;
  }

  async function later() {
    try {
      const next = await api<UpdateStatus>("/updates/dismiss", {
        method: "POST",
        body: JSON.stringify({ version: info?.latest_version || "" }),
      });
      setInfo(next);
      setOpen(false);
    } catch {
      setInfo((prev) => (prev ? { ...prev, dismissed: true } : prev));
    }
  }

  async function copyCompose() {
    const text = info?.upgrade.compose || "";
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="update-banner" role="status">
      <div className="update-banner-row">
        <p className="update-banner-text">
          RestoreProof <strong>{info.latest_version}</strong> is out. You are on{" "}
          {info.current_version}.
        </p>
        <div className="row-actions">
          <button className="btn small" type="button" onClick={() => setOpen((v) => !v)}>
            {open ? "Hide steps" : "Upgrade"}
          </button>
          {info.release_url && (
            <a className="btn secondary small" href={info.release_url} target="_blank" rel="noreferrer">
              Notes
            </a>
          )}
          <button className="btn ghost small" type="button" onClick={later}>
            Later
          </button>
        </div>
      </div>
      {open && (
        <div className="update-banner-steps">
          <p>Do not pull images while a restore is running.</p>
          <p>
            <strong>Portainer:</strong> {info.upgrade.portainer}
          </p>
          <p>
            <strong>Compose:</strong>
          </p>
          <pre className="update-banner-code">{info.upgrade.compose}</pre>
          <div className="row-actions">
            <button className="btn secondary small" type="button" onClick={copyCompose}>
              {copied ? "Copied" : "Copy compose commands"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
