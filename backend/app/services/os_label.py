"""
Purpose: Human-readable OS labels from a Proxmox guest ostype.
Author: Doug Hesseltine
Created: 2026-10-07
Modified: 2026-10-07
Version: 1.0.0
"""

from __future__ import annotations

# Proxmox QEMU ostype values. win11 covers Windows 11 and Server 2022/2025.
_QEMU_OS = {
    "wxp": "Windows",
    "w2k": "Windows",
    "w2k3": "Windows",
    "w2k8": "Windows",
    "wvista": "Windows",
    "win7": "Windows",
    "win8": "Windows",
    "win10": "Windows",
    "win11": "Windows",
    "l24": "Linux",
    "l26": "Linux",
    "solaris": "Solaris",
    "other": "Other",
}

# Proxmox LXC ostype values (the container template's distro).
_LXC_OS = {
    "debian": "Debian",
    "devuan": "Devuan",
    "ubuntu": "Ubuntu",
    "centos": "CentOS",
    "fedora": "Fedora",
    "opensuse": "openSUSE",
    "archlinux": "Arch Linux",
    "alpine": "Alpine",
    "gentoo": "Gentoo",
    "nixos": "NixOS",
    "unmanaged": "Linux",
}


def os_label_from_ostype(guest_type: str, ostype: str | None) -> str:
    """Return a short OS name for the runs list. Empty ostype stays generic."""
    raw = (ostype or "").strip().lower()
    table = _LXC_OS if guest_type == "lxc" else _QEMU_OS
    if raw in table:
        return table[raw]
    if not raw:
        return "Linux" if guest_type == "lxc" else "Unknown"
    return raw.replace("_", " ").title()
