"""
Purpose: OS label mapping from Proxmox ostype values.
Author: Doug Hesseltine
Created: 2026-10-07
Modified: 2026-10-07
Version: 1.0.0
"""

from app.services.os_label import os_label_from_ostype


def test_windows_and_linux_qemu_labels():
    assert os_label_from_ostype("qemu", "win11") == "Windows"
    assert os_label_from_ostype("qemu", "l26") == "Linux"
    assert os_label_from_ostype("qemu", "other") == "Other"
    assert os_label_from_ostype("qemu", "") == "Unknown"


def test_lxc_distro_labels():
    assert os_label_from_ostype("lxc", "debian") == "Debian"
    assert os_label_from_ostype("lxc", "ubuntu") == "Ubuntu"
    assert os_label_from_ostype("lxc", "") == "Linux"
    assert os_label_from_ostype("lxc", "unmanaged") == "Linux"
