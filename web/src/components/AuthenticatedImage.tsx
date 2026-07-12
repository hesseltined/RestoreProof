/**
 * Purpose: Fetch authenticated evidence/image blobs for display.
 * Author: Doug Hesseltine
 * Created: 2026-07-12
 * Version: 1.0.0
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

  useEffect(() => {
    let objectUrl = "";
    let cancelled = false;
    (async () => {
      const res = await fetch(`/api${path}`, {
        headers: { Authorization: `Bearer ${getToken()}` },
      });
      if (!res.ok || cancelled) return;
      const blob = await res.blob();
      objectUrl = URL.createObjectURL(blob);
      if (!cancelled) setSrc(objectUrl);
    })();
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [path]);

  if (!src) return <p className="help">Loading…</p>;
  return <img className={className} src={src} alt={alt} />;
}
