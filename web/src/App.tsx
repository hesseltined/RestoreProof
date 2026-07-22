/**
 * Purpose: RestoreProof React router entry.
 * Author: Doug Hesseltine
 * Created: 2026-07-12
 * Modified: 2026-07-22
 * Version: 1.3.0
 */

import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth";
import { Layout } from "./Layout";
import {
  ForgotPasswordPage,
  LoginPage,
  ResetPasswordPage,
} from "./pages/AuthPages";
import { DashboardPage } from "./pages/DashboardPage";
import { GuestsPage } from "./pages/GuestsPage";
import { HostsPage } from "./pages/HostsPage";
import { NotificationsPage } from "./pages/NotificationsPage";
import { RunDetailPage, RunsPage } from "./pages/RunsPage";
import { SchedulePage } from "./pages/SchedulePage";
import { SettingsPage } from "./pages/SettingsPage";
import { UsersPage } from "./pages/UsersPage";

function Private({ children }: { children: React.ReactNode }) {
  const { user, loading, setupRequired, demo } = useAuth();
  if (demo) return <>{children}</>;
  if (loading) return <p className="help" style={{ padding: "2rem" }}>Loading…</p>;
  if (setupRequired || !user) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export default function App() {
  const { demo } = useAuth();

  return (
    <Routes>
      {!demo && (
        <>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/forgot-password" element={<ForgotPasswordPage />} />
          <Route path="/reset-password" element={<ResetPasswordPage />} />
        </>
      )}
      <Route
        path="/"
        element={
          <Private>
            <Layout />
          </Private>
        }
      >
        <Route index element={<DashboardPage />} />
        <Route path="guests" element={<GuestsPage />} />
        <Route path="runs" element={<RunsPage />} />
        <Route path="runs/:id" element={<RunDetailPage />} />
        <Route path="hosts" element={<HostsPage />} />
        <Route path="schedule" element={<SchedulePage />} />
        <Route path="notifications" element={<NotificationsPage />} />
        <Route path="users" element={<UsersPage />} />
        <Route path="settings" element={<SettingsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
