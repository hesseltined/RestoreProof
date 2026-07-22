/**
 * Purpose: Auth + theme context for RestoreProof UI (includes /demo auto-login).
 * Author: Doug Hesseltine
 * Created: 2026-07-12
 * Modified: 2026-07-22
 * Version: 1.2.0
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api, getToken, setToken } from "./api";
import { isDemoMode } from "./demo/mode";

export type User = {
  id: number;
  email: string;
  is_active: boolean;
  is_admin: boolean;
  totp_enabled: boolean;
};

type AuthState = {
  user: User | null;
  loading: boolean;
  setupRequired: boolean;
  theme: "light" | "dark";
  demo: boolean;
  login: (email: string, password: string, totp?: string) => Promise<{ requires_2fa?: boolean }>;
  logout: () => void;
  refreshMe: () => Promise<void>;
  toggleTheme: () => void;
  completeSetup: (email: string, password: string) => Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);

const DEMO_USER: User = {
  id: 1,
  email: "demo@restoreproof.example",
  is_active: true,
  is_admin: true,
  totp_enabled: true,
};

export function AuthProvider({ children }: { children: ReactNode }) {
  const demo = isDemoMode();
  const [user, setUser] = useState<User | null>(demo ? DEMO_USER : null);
  const [loading, setLoading] = useState(!demo);
  const [setupRequired, setSetupRequired] = useState(false);
  const [theme, setTheme] = useState<"light" | "dark">(() => {
    const saved = localStorage.getItem("rp_theme");
    return saved === "dark" ? "dark" : "light";
  });

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("rp_theme", theme);
  }, [theme]);

  const refreshMe = useCallback(async () => {
    if (isDemoMode()) {
      setSetupRequired(false);
      setUser(DEMO_USER);
      return;
    }
    const status = await api<{ setup_completed: boolean; user_count: number }>("/auth/status");
    if (!status.setup_completed || status.user_count === 0) {
      setSetupRequired(true);
      setUser(null);
      return;
    }
    setSetupRequired(false);
    if (!getToken()) {
      setUser(null);
      return;
    }
    try {
      const me = await api<User>("/auth/me");
      setUser(me);
    } catch {
      setToken(null);
      setUser(null);
    }
  }, []);

  useEffect(() => {
    if (demo) {
      setLoading(false);
      return;
    }
    refreshMe().finally(() => setLoading(false));
  }, [demo, refreshMe]);

  const login = useCallback(
    async (email: string, password: string, totp?: string) => {
      if (isDemoMode()) {
        setUser(DEMO_USER);
        return {};
      }
      const res = await api<{
        access_token: string;
        requires_2fa?: boolean;
        setup_required?: boolean;
      }>("/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password, totp_code: totp || null }),
      });
      if (res.setup_required) {
        setSetupRequired(true);
        return {};
      }
      if (res.requires_2fa) return { requires_2fa: true };
      setToken(res.access_token);
      await refreshMe();
      return {};
    },
    [refreshMe]
  );

  const completeSetup = useCallback(
    async (email: string, password: string) => {
      if (isDemoMode()) {
        setUser(DEMO_USER);
        setSetupRequired(false);
        return;
      }
      const res = await api<{ access_token: string }>("/auth/setup", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      setToken(res.access_token);
      setSetupRequired(false);
      await refreshMe();
    },
    [refreshMe]
  );

  const logout = useCallback(() => {
    if (isDemoMode()) return;
    setToken(null);
    setUser(null);
  }, []);

  const toggleTheme = useCallback(() => {
    setTheme((t) => (t === "light" ? "dark" : "light"));
  }, []);

  const value = useMemo(
    () => ({
      user,
      loading,
      setupRequired,
      theme,
      demo,
      login,
      logout,
      refreshMe,
      toggleTheme,
      completeSetup,
    }),
    [user, loading, setupRequired, theme, demo, login, logout, refreshMe, toggleTheme, completeSetup]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside provider");
  return ctx;
}
