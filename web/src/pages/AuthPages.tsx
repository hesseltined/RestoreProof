/**
 * Purpose: Login, setup, and password-reset screens.
 * Author: Doug Hesseltine
 * Created: 2026-07-12
 * Version: 1.0.0
 */

import { FormEvent, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";

export function LoginPage() {
  const { login, setupRequired, completeSetup, toggleTheme, theme } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [totp, setTotp] = useState("");
  const [need2fa, setNeed2fa] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (setupRequired) {
        await completeSetup(email, password);
        navigate("/");
        return;
      }
      const res = await login(email, password, totp || undefined);
      if (res.requires_2fa) {
        setNeed2fa(true);
        return;
      }
      navigate("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-page">
      <div className="card auth-card">
        <div className="brand" style={{ padding: 0, border: "none", marginBottom: "1rem" }}>
          <div className="brand-mark">RP</div>
          <div>
            <h1 style={{ margin: 0 }}>RestoreProof</h1>
            <p className="help" style={{ margin: 0 }}>
              {setupRequired ? "Create the first admin account" : "Sign in to continue"}
            </p>
          </div>
        </div>
        <form onSubmit={onSubmit}>
          <div className="field">
            <label>Email</label>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="username"
            />
          </div>
          <div className="field">
            <label>Password</label>
            <input
              type="password"
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete={setupRequired ? "new-password" : "current-password"}
            />
          </div>
          {need2fa && (
            <div className="field">
              <label>2FA code</label>
              <input
                value={totp}
                onChange={(e) => setTotp(e.target.value)}
                placeholder="123456"
                autoFocus
              />
            </div>
          )}
          {error && <p className="error">{error}</p>}
          <div className="row-actions" style={{ marginTop: "1rem" }}>
            <button className="btn" type="submit" disabled={busy}>
              {setupRequired ? "Create admin" : "Sign in"}
            </button>
            <button className="btn secondary" type="button" onClick={toggleTheme}>
              {theme === "light" ? "Dark" : "Light"}
            </button>
          </div>
        </form>
        {!setupRequired && (
          <p className="help" style={{ marginTop: "1rem" }}>
            <Link to="/forgot-password">Forgot password?</Link>
          </p>
        )}
      </div>
    </div>
  );
}

export function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setMsg("");
    try {
      const res = await api<{ ok: boolean; dev_reset_url?: string }>("/auth/password-reset/request", {
        method: "POST",
        body: JSON.stringify({ email }),
      });
      setMsg(
        res.dev_reset_url
          ? `If SMTP is not configured, use: ${res.dev_reset_url}`
          : "If that account exists, a reset link was sent."
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    }
  }

  return (
    <div className="auth-page">
      <div className="card auth-card">
        <h1>Reset password</h1>
        <form onSubmit={onSubmit}>
          <div className="field">
            <label>Email</label>
            <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          {error && <p className="error">{error}</p>}
          {msg && <p className="success">{msg}</p>}
          <div className="row-actions">
            <button className="btn" type="submit">
              Send reset link
            </button>
            <Link className="btn secondary" to="/login">
              Back
            </Link>
          </div>
        </form>
      </div>
    </div>
  );
}

export function ResetPasswordPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const token = params.get("token") || "";
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    try {
      await api("/auth/password-reset/confirm", {
        method: "POST",
        body: JSON.stringify({ token, new_password: password }),
      });
      navigate("/login");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Reset failed");
    }
  }

  return (
    <div className="auth-page">
      <div className="card auth-card">
        <h1>Choose a new password</h1>
        <form onSubmit={onSubmit}>
          <div className="field">
            <label>New password</label>
            <input
              type="password"
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          {error && <p className="error">{error}</p>}
          <button className="btn" type="submit">
            Update password
          </button>
        </form>
      </div>
    </div>
  );
}
