/**
 * Purpose: VM/LXC and OS badges shown on restore runs.
 * Author: Doug Hesseltine
 * Created: 2026-10-07
 * Modified: 2026-10-07
 * Version: 1.0.0
 */

/** qemu is a virtual machine; lxc is a container. */
export function guestKindLabel(guestType: string): "VM" | "LXC" {
  return guestType === "lxc" ? "LXC" : "VM";
}

export function GuestSystem({
  guestType,
  osLabel,
}: {
  guestType: string;
  osLabel?: string | null;
}) {
  const kind = guestKindLabel(guestType);
  const os = (osLabel || "").trim() || "Unknown";
  const osClass = os.toLowerCase().startsWith("windows") ? "windows" : "os";
  return (
    <span className="guest-system">
      <span className={`badge kind ${kind === "LXC" ? "lxc" : "vm"}`}>{kind}</span>
      <span className={`badge ${osClass}`}>{os}</span>
    </span>
  );
}
