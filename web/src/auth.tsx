/**
 * Purpose: Auth + theme context for RestoreProof UI.
 * Author: Doug Hesseltine
 * Created: 2026-07-12
 * Version: 1.0.0
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
  login: (email: string, password: string, totp?: string) => Promise<{ requires_2fa?: boolean }>;
  logout: () => void;
  refreshMe: () => Promise<void>;
  toggleTheme: () => void;
  completeSetup: (email: string, password: string) => Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
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
    refreshMe().finally(() => setLoading(false));
  }, [refreshMe]);

  const login = useCallback(
    async (email: string, password: string, totp?: string) => {
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
      login,
      logout,
      refreshMe,
      toggleTheme,
      completeSetup,
    }),
    [user, loading, setupRequired, theme, login, logout, refreshMe, toggleTheme, completeSetup]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside provider");
  return ctx;
}
