/**
 * Purpose: Datacenter guest list for the public RestoreProof demo.
 * Author: Doug Hesseltine
 * Created: 2026-10-07
 * Modified: 2026-10-07
 * Version: 1.1.0
 *
 * Real server roles from the datacenter (domain controllers, file server,
 * RDS, Windows 11, and a few Linux VMs and containers). Not a copy of the
 * live homelab inventory, and no LAN addresses.
 */

export type LiveGuest = {
  vmid: number;
  name: string;
  guest_type: "qemu" | "lxc";
  os_label: string;
  status: string;
  cpu_cores: number;
  memory_bytes: number;
  disk_bytes: number;
  excluded: boolean;
  in_backup_job: boolean;
  backup_job_enabled: boolean;
  backup_snapshot_count: number;
};

export const LIVE_BACKUP_SUMMARY = "datacenter (sun 01:00)";

export const LIVE_GUESTS: LiveGuest[] = [
  { vmid: 122, name: "DC1", guest_type: "qemu", os_label: "Windows", status: "running", cpu_cores: 4, memory_bytes: 17179869184, disk_bytes: 161061273600, excluded: false, in_backup_job: true, backup_job_enabled: true, backup_snapshot_count: 8 },
  { vmid: 126, name: "DC2", guest_type: "qemu", os_label: "Windows", status: "running", cpu_cores: 2, memory_bytes: 8589934592, disk_bytes: 128849018880, excluded: false, in_backup_job: true, backup_job_enabled: true, backup_snapshot_count: 6 },
  { vmid: 125, name: "FS1", guest_type: "qemu", os_label: "Windows", status: "running", cpu_cores: 2, memory_bytes: 8589934592, disk_bytes: 128849018880, excluded: false, in_backup_job: true, backup_job_enabled: true, backup_snapshot_count: 7 },
  { vmid: 123, name: "RDS", guest_type: "qemu", os_label: "Windows", status: "running", cpu_cores: 4, memory_bytes: 17179869184, disk_bytes: 128849018880, excluded: false, in_backup_job: true, backup_job_enabled: true, backup_snapshot_count: 5 },
  { vmid: 124, name: "Server2025", guest_type: "qemu", os_label: "Windows", status: "running", cpu_cores: 2, memory_bytes: 8589934592, disk_bytes: 128849018880, excluded: false, in_backup_job: true, backup_job_enabled: true, backup_snapshot_count: 4 },
  { vmid: 117, name: "Win11Pro", guest_type: "qemu", os_label: "Windows", status: "running", cpu_cores: 4, memory_bytes: 12884901888, disk_bytes: 66571993088, excluded: false, in_backup_job: true, backup_job_enabled: true, backup_snapshot_count: 9 },
  { vmid: 100, name: "DC01", guest_type: "qemu", os_label: "Windows", status: "stopped", cpu_cores: 4, memory_bytes: 8589934592, disk_bytes: 100000595968, excluded: true, in_backup_job: true, backup_job_enabled: true, backup_snapshot_count: 2 },
  { vmid: 210, name: "app-01", guest_type: "qemu", os_label: "Linux", status: "running", cpu_cores: 8, memory_bytes: 17179869184, disk_bytes: 268435456000, excluded: false, in_backup_job: true, backup_job_enabled: true, backup_snapshot_count: 6 },
  { vmid: 211, name: "db-01", guest_type: "qemu", os_label: "Linux", status: "running", cpu_cores: 4, memory_bytes: 17179869184, disk_bytes: 429496729600, excluded: false, in_backup_job: true, backup_job_enabled: true, backup_snapshot_count: 8 },
  { vmid: 212, name: "monitor-01", guest_type: "qemu", os_label: "Linux", status: "running", cpu_cores: 2, memory_bytes: 4294967296, disk_bytes: 34359738368, excluded: false, in_backup_job: true, backup_job_enabled: true, backup_snapshot_count: 4 },
  { vmid: 310, name: "proxy", guest_type: "lxc", os_label: "Debian", status: "running", cpu_cores: 2, memory_bytes: 2147483648, disk_bytes: 8589934592, excluded: false, in_backup_job: true, backup_job_enabled: true, backup_snapshot_count: 6 },
  { vmid: 311, name: "auth", guest_type: "lxc", os_label: "Debian", status: "running", cpu_cores: 2, memory_bytes: 4294967296, disk_bytes: 21474836480, excluded: false, in_backup_job: true, backup_job_enabled: true, backup_snapshot_count: 5 },
  { vmid: 312, name: "metrics", guest_type: "lxc", os_label: "Ubuntu", status: "running", cpu_cores: 2, memory_bytes: 4294967296, disk_bytes: 21474836480, excluded: false, in_backup_job: true, backup_job_enabled: true, backup_snapshot_count: 4 },
  { vmid: 313, name: "edge-cache", guest_type: "lxc", os_label: "Ubuntu", status: "running", cpu_cores: 1, memory_bytes: 1073741824, disk_bytes: 8589934592, excluded: false, in_backup_job: false, backup_job_enabled: false, backup_snapshot_count: 0 },
];
