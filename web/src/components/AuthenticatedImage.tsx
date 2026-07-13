/**
 * Purpose: Fetch authenticated evidence/image blobs for display.
 * Author: Doug Hesseltine
 * Created: 2026-07-12
 * Modified: 2026-07-12
 * Version: 1.1.0
 */

import { useEffect, useState } from "react";
import { getToken } from "../api";

export function AuthenticatedImage({
  path,
  alt = "Evidence",
  className = "evidence-img",
}: {
  path: string;
  alt?: string;
  className?: string;
}) {
  const [src, setSrc] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let objectUrl = "";
    let cancelled = false;
    setSrc("");
    setError("");
    (async () => {
      try {
        const res = await fetch(`/api${path}`, {
          headers: { Authorization: `Bearer ${getToken()}` },
        });
        if (cancelled) return;
        if (!res.ok) {
          setError(res.status === 404 ? "Evidence file missing" : `Failed to load (${res.status})`);
          return;
        }
        const blob = await res.blob();
        if (!blob.type.startsWith("image/") && blob.type !== "application/octet-stream") {
          setError(`Unexpected evidence type: ${blob.type || "unknown"}`);
          return;
        }
        objectUrl = URL.createObjectURL(blob);
        if (!cancelled) setSrc(objectUrl);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load evidence");
      }
    })();
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [path]);

  if (error) return <p className="error">{error}</p>;
  if (!src) return <p className="help">Loading…</p>;
  return (
    <img
      className={className}
      src={src}
      alt={alt}
      onError={() => setError("Image is not a valid PNG (capture may need redeploy)")}
    />
  );
}
