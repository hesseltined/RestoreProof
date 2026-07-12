/**
 * Purpose: App shell with collapsible sidebar nav on every page.
 * Author: Doug Hesseltine
 * Created: 2026-07-12
 * Modified: 2026-07-12
 * Version: 1.1.0
 */

import { useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "./auth";

const NAV = [
  { to: "/", label: "Dashboard", icon: "◉" },
  { to: "/guests", label: "Guests", icon: "▣" },
  { to: "/runs", label: "Runs", icon: "▤" },
  { to: "/hosts", label: "Hosts", icon: "⬡" },
  { to: "/schedule", label: "Schedule", icon: "◷" },
  { to: "/notifications", label: "Notifications", icon: "✉" },
  { to: "/users", label: "Users", icon: "☺" },
  { to: "/settings", label: "Settings", icon: "⚙" },
];

export function Layout() {
  const { user, logout, toggleTheme, theme } = useAuth();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileHidden, setMobileHidden] = useState(true);
  const navigate = useNavigate();

  return (
    <div className="app-shell">
      <aside
        className={`sidebar ${collapsed ? "collapsed" : ""} ${
          mobileHidden ? "mobile-hidden" : ""
        }`}
      >
        <div className="brand">
          <div className="brand-mark">RP</div>
          <div className="brand-text">RestoreProof</div>
        </div>
        <nav className="nav">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              onClick={() => setMobileHidden(true)}
            >
              <span className="nav-icon">{item.icon}</span>
              <span className="nav-label">{item.label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          <button className="btn ghost" type="button" onClick={() => setCollapsed((c) => !c)}>
            {collapsed ? "»" : "« Collapse"}
          </button>
          <button className="btn ghost" type="button" onClick={toggleTheme}>
            {theme === "light" ? "Dark" : "Light"} mode
          </button>
          <button
            className="btn ghost"
            type="button"
            onClick={() => {
              logout();
              navigate("/login");
            }}
          >
            <span>Sign out</span>
          </button>
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <div className="row-actions">
            <button
              className="btn secondary small hamburger"
              type="button"
              onClick={() => setMobileHidden((v) => !v)}
            >
              Menu
            </button>
            <strong>RestoreProof</strong>
          </div>
          <div className="row-actions">
            <span className="help">{user?.email}</span>
          </div>
        </header>
        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
