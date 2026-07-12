/**
 * Purpose: Guest inventory with exclude, schedule override, run now.
 * Author: Doug Hesseltine
 * Created: 2026-07-12
 * Modified: 2026-07-12
 * Version: 1.4.0
 */

import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";

type Guest = {
  id: number;
  host_name: string;
  vmid: number;
  name: string;
  guest_type: string;
  node: string;
  status: string;
  excluded: boolean;
  schedule_cron: string | null;
  schedule_enabled: boolean;
  last_tested_at: string | null;
};

export function GuestsPage() {
  const [guests, setGuests] = useState<Guest[]>([]);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState<number | null>(null);
  const navigate = useNavigate();

  async function load() {
    setGuests(await api<Guest[]>("/guests"));
  }

  useEffect(() => {
    load().catch((e) => setError(e.message));
  }, []);

  async function patch(id: number, body: Partial<Guest>) {
    setError("");
    try {
      await api(`/guests/${id}`, { method: "PATCH", body: JSON.stringify(body) });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Update failed");
    }
  }

  async function runNow(id: number) {
    setError("");
    setBusyId(id);
    try {
      await api<{ id: number }>(`/guests/${id}/run`, { method: "POST" });
      navigate("/");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Run failed");
      setBusyId(null);
    }
  }

  return (
    <div>
      <h1 className="page-title">Guests</h1>
      <p className="page-sub">VMs and containers discovered from connected hosts.</p>
      {error && <p className="error">{error}</p>}

      <div className="card table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th>VMID</th>
              <th>Name</th>
              <th>Type</th>
              <th>Host</th>
              <th>Exclude</th>
              <th>Schedule override</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {guests.map((g) => (
              <tr key={g.id}>
                <td className="mono">{g.vmid}</td>
                <td>{g.name}</td>
                <td>
                  <span className="badge">{g.guest_type}</span>
                </td>
                <td>
                  {g.host_name}
                  <div className="help">{g.node}</div>
                </td>
                <td>
                  <input
                    type="checkbox"
                    checked={g.excluded}
                    onChange={(e) => patch(g.id, { excluded: e.target.checked })}
                  />
                </td>
                <td>
                  <input
                    className="mono"
                    style={{ width: "140px" }}
                    placeholder="use global"
                    value={g.schedule_cron || ""}
                    onChange={(e) =>
                      setGuests((list) =>
                        list.map((x) =>
                          x.id === g.id ? { ...x, schedule_cron: e.target.value || null } : x
                        )
                      )
                    }
                    onBlur={(e) =>
                      patch(g.id, {
                        schedule_cron: e.target.value || null,
                      } as Partial<Guest>)
                    }
                  />
                </td>
                <td className="row-actions">
                  <button
                    className="btn small"
                    type="button"
                    disabled={busyId === g.id}
                    onClick={() => runNow(g.id)}
                  >
                    {busyId === g.id ? "Starting…" : "Run now"}
                  </button>
                </td>
              </tr>
            ))}
            {!guests.length && (
              <tr>
                <td colSpan={7} className="help">
                  No guests yet. Add a host and sync inventory. <Link to="/hosts">Hosts</Link>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
