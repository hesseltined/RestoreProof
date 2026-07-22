/**
 * Purpose: RestoreProof API client helpers (real API + /demo mock).
 * Author: Doug Hesseltine
 * Created: 2026-07-12
 * Modified: 2026-07-22
 * Version: 1.2.0
 */

import { isDemoMode } from "./demo/mode";
import { demoApiFetch } from "./demo/mockApi";

const TOKEN_KEY = "rp_token";

export function getToken(): string | null {
  if (isDemoMode()) return "demo-token";
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null) {
  if (isDemoMode()) return;
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export async function api<T = unknown>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  if (isDemoMode()) {
    const res = await demoApiFetch(path, options);
    const text = await res.text();
    let data: unknown = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      data = text;
    }
    if (!res.ok) {
      const detail =
        typeof data === "object" && data && "detail" in data
          ? String((data as { detail: unknown }).detail)
          : res.statusText;
      throw new Error(detail || `HTTP ${res.status}`);
    }
    return data as T;
  }

  const headers = new Headers(options.headers || {});
  if (!headers.has("Content-Type") && options.body) {
    headers.set("Content-Type", "application/json");
  }
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const res = await fetch(`/api${path}`, { ...options, headers });
  if (res.status === 401) {
    setToken(null);
  }
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) {
    const detail =
      typeof data === "object" && data && "detail" in data
        ? String((data as { detail: unknown }).detail)
        : res.statusText;
    throw new Error(detail || `HTTP ${res.status}`);
  }
  return data as T;
}

export async function downloadConfigExport(includeUsers: boolean): Promise<void> {
  const res = await api<{
    filename: string;
    data: string;
  }>(`/config/export?include_users=${includeUsers ? "true" : "false"}`);
  const blob = new Blob([res.data], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = res.filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export async function uploadConfigImport(
  file: File,
  mode: "merge" | "replace",
  importUsers: boolean
): Promise<{
  mode: string;
  hosts_created: number;
  hosts_updated: number;
  guest_overrides_applied: number;
  guest_overrides_pending: number;
  users_created: number;
  users_skipped: number;
}> {
  if (isDemoMode()) {
    return api(`/config/import/file?mode=${mode}&import_users=${importUsers}`, {
      method: "POST",
      body: JSON.stringify({ filename: file.name }),
    });
  }

  const token = getToken();
  const form = new FormData();
  form.append("file", file);
  const params = new URLSearchParams({
    mode,
    import_users: importUsers ? "true" : "false",
  });
  const res = await fetch(`/api/config/import/file?${params.toString()}`, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  });
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) {
    const detail =
      typeof data === "object" && data && "detail" in data
        ? String((data as { detail: unknown }).detail)
        : res.statusText;
    throw new Error(detail || `HTTP ${res.status}`);
  }
  return data as {
    mode: string;
    hosts_created: number;
    hosts_updated: number;
    guest_overrides_applied: number;
    guest_overrides_pending: number;
    users_created: number;
    users_skipped: number;
  };
}
