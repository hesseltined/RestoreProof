/**
 * Purpose: Admin users and TOTP enrollment.
 * Author: Doug Hesseltine
 * Created: 2026-07-12
 * Modified: 2026-07-12
 * Version: 1.5.0
 */

import { FormEvent, useEffect, useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import { api } from "../api";
import { useAuth } from "../auth";

type UserRow = {
  id: number;
  email: string;
  totp_enabled: boolean;
  is_admin: boolean;
};

export function UsersPage() {
  const { user, refreshMe } = useAuth();
  const [users, setUsers] = useState<UserRow[]>([]);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [totpUri, setTotpUri] = useState("");
  const [totpSecret, setTotpSecret] = useState("");
  const [code, setCode] = useState("");
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const [enforce, setEnforce] = useState(false);

  async function load() {
    setUsers(await api<UserRow[]>("/users"));
    const s = await api<{ enforce_2fa: boolean }>("/settings");
    setEnforce(s.enforce_2fa);
  }

  useEffect(() => {
    load().catch((e) => setError(e.message));
  }, []);

  const totpOk =
    Boolean(user?.totp_enabled) || users.some((u) => u.id === user?.id && u.totp_enabled);

  async function createUser(e: FormEvent) {
    e.preventDefault();
    await api("/users", { method: "POST", body: JSON.stringify({ email, password }) });
    setEmail("");
    setPassword("");
    setMsg("User created.");
    await load();
  }

  async function setupTotp() {
    setError("");
    const res = await api<{ secret: string; otpauth_uri: string }>("/auth/totp/setup", {
      method: "POST",
    });
    setTotpSecret(res.secret);
    setTotpUri(res.otpauth_uri);
  }

  async function enableTotp(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      await api("/auth/totp/enable", { method: "POST", body: JSON.stringify({ code }) });
      setTotpSecret("");
      setTotpUri("");
      setCode("");
      setMsg("2FA enabled.");
      await refreshMe();
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not enable 2FA");
    }
  }

  async function saveEnforce() {
    await api("/settings", { method: "PUT", body: JSON.stringify({ enforce_2fa: enforce }) });
    setMsg("2FA policy saved.");
  }

  return (
    <div>
      <h1 className="page-title">Users</h1>
      <p className="page-sub">Administrators, password reset via email, and TOTP 2FA.</p>
      {msg && <p className="success">{msg}</p>}
      {error && <p className="error">{error}</p>}

      <div className="card table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th>Email</th>
              <th>2FA</th>
              <th>Admin</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id}>
                <td>
                  {u.email}
                  {user?.id === u.id ? " (you)" : ""}
                </td>
                <td>{u.totp_enabled ? <span className="badge ok">On</span> : "Off"}</td>
                <td>{u.is_admin ? "Yes" : "No"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <form className="card" onSubmit={createUser}>
        <h3 style={{ marginTop: 0 }}>Add admin</h3>
        <div className="grid-2">
          <div className="field">
            <label>Email</label>
            <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div className="field">
            <label>Temporary password</label>
            <input
              type="password"
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
        </div>
        <button className="btn" type="submit">
          Create user
        </button>
      </form>

      <div className={`card ${totpOk ? "host-complete" : ""}`}>
        <div className="setup-step-head">
          <h3 style={{ marginTop: 0, marginBottom: 0 }}>Your 2FA</h3>
          <span className={`badge ${totpOk ? "ok" : ""}`}>{totpOk ? "Enabled" : "Off"}</span>
        </div>

        {totpOk ? (
          <p className="success" style={{ marginTop: "0.75rem" }}>
            2FA is enabled. Authenticator apps will prompt for a code at sign-in.
          </p>
        ) : (
          <>
            <div className="row-actions">
              <button className="btn secondary" type="button" onClick={setupTotp}>
                {totpSecret ? "Regenerate TOTP secret" : "Generate TOTP secret"}
              </button>
            </div>
            {totpSecret && totpUri && (
              <>
                <div className="totp-setup">
                  <div className="totp-qr">
                    <QRCodeSVG value={totpUri} size={192} level="M" includeMargin />
                    <p className="help" style={{ marginTop: "0.5rem", textAlign: "center" }}>
                      Scan with Authy, Google Authenticator, 1Password, etc.
                    </p>
                  </div>
                  <div className="totp-manual">
                    <p className="help" style={{ marginTop: 0 }}>
                      Or enter this secret manually:
                    </p>
                    <p className="mono totp-secret">{totpSecret}</p>
                  </div>
                </div>
                <form onSubmit={enableTotp}>
                  <div className="field">
                    <label>Confirm code from your authenticator</label>
                    <input
                      value={code}
                      onChange={(e) => setCode(e.target.value)}
                      required
                      inputMode="numeric"
                      autoComplete="one-time-code"
                      placeholder="123456"
                    />
                  </div>
                  <button className="btn" type="submit">
                    Enable 2FA
                  </button>
                </form>
              </>
            )}
          </>
        )}
      </div>

      <div className="card">
        <h3 style={{ marginTop: 0 }}>Policy</h3>
        <label>
          <input
            type="checkbox"
            checked={enforce}
            onChange={(e) => setEnforce(e.target.checked)}
          />{" "}
          Enforce 2FA for administrators
        </label>
        <div className="row-actions" style={{ marginTop: "0.75rem" }}>
          <button className="btn secondary" type="button" onClick={saveEnforce}>
            Save policy
          </button>
        </div>
      </div>
    </div>
  );
}
