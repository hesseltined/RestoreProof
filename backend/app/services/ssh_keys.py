"""
Purpose: SSH helpers for QMP screendump, qmrestore/pct restore fallback, and key generation.
Author: Doug Hesseltine
Created: 2026-07-12
Modified: 2026-09-11
Version: 1.5.0
"""

from __future__ import annotations

import logging
import os
import shlex
from pathlib import Path

import paramiko
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from PIL import Image

from app.config import get_settings

logger = logging.getLogger(__name__)


def convert_screendump_to_png(src_path: str | Path, dest_path: str | Path) -> Path:
    """
    Normalize a QEMU screendump to PNG.

    PVE QEMU is often built without libpng, so `screendump … -f png` fails and the
    default dump is PPM (Netpbm) even when the remote filename ends in .png.
    Browsers and email clients cannot display that as an image.
    """
    src = Path(src_path)
    dest = Path(dest_path)
    if not src.exists() or src.stat().st_size == 0:
        raise RuntimeError(f"Screendump missing or empty: {src}")
    with Image.open(src) as img:
        # PPM dumps are RGB; force a portable PNG for UI + email CID
        rgb = img.convert("RGB")
        dest.parent.mkdir(parents=True, exist_ok=True)
        rgb.save(dest, format="PNG", optimize=True)
    if not dest.exists() or dest.stat().st_size == 0:
        raise RuntimeError(f"PNG conversion produced empty file: {dest}")
    return dest


def host_key_paths(host_id: int) -> tuple[Path, Path]:
    settings = get_settings()
    key_dir = Path(settings.data_dir) / "keys"
    key_dir.mkdir(parents=True, exist_ok=True)
    private = key_dir / f"host_{host_id}_ed25519"
    public = key_dir / f"host_{host_id}_ed25519.pub"
    return private, public


def generate_host_ssh_key(host_id: int) -> tuple[str, str]:
    """Create an Ed25519 keypair for a Proxmox host connection. Returns (private_path, public_key)."""
    private_path, public_path = host_key_paths(host_id)
    if private_path.exists():
        pub = public_path.read_text().strip() if public_path.exists() else ""
        return str(private_path), pub

    key = ed25519.Ed25519PrivateKey.generate()
    private_bytes = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = key.public_key().public_bytes(
        encoding=serialization.Encoding.OpenSSH,
        format=serialization.PublicFormat.OpenSSH,
    )
    comment = f" restoreproof-host-{host_id}"
    private_path.write_bytes(private_bytes)
    os.chmod(private_path, 0o600)
    pub_line = public_bytes.decode("utf-8") + comment + "\n"
    public_path.write_text(pub_line)
    os.chmod(public_path, 0o644)
    return str(private_path), pub_line.strip()


def read_public_key(host_id: int) -> str:
    _, public_path = host_key_paths(host_id)
    if not public_path.exists():
        return ""
    return public_path.read_text().strip()


class SSHSession:
    def __init__(self, host: str, port: int, username: str, private_key_path: str):
        self.host = host
        self.port = port
        self.username = username
        self.private_key_path = private_key_path
        self.client: paramiko.SSHClient | None = None

    def __enter__(self) -> "SSHSession":
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        pkey = paramiko.Ed25519Key.from_private_key_file(self.private_key_path)
        client.connect(
            hostname=self.host,
            port=self.port,
            username=self.username,
            pkey=pkey,
            timeout=30,
            allow_agent=False,
            look_for_keys=False,
        )
        self.client = client
        return self

    def __exit__(self, *args: object) -> None:
        if self.client:
            self.client.close()

    def run(self, command: str, timeout: int = 120) -> tuple[int, str, str]:
        assert self.client is not None
        _stdin, stdout, stderr = self.client.exec_command(command, timeout=timeout)
        exit_code = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        return exit_code, out, err

    def screendump_vm(self, vmid: int, remote_path: str) -> None:
        """
        Capture VGA framebuffer via QEMU monitor screendump.

        Prefer a .ppm remote path: Proxmox QEMU often lacks libpng, so `-f png`
        errors with "Enable PNG support with libpng for screendump".
        """
        remote_dir = os.path.dirname(remote_path)
        code, _, err = self.run(f"mkdir -p '{remote_dir}'")
        if code != 0:
            raise RuntimeError(f"mkdir failed: {err}")
        # qm monitor accepts interactive commands; use printf pipe
        cmd = f"printf 'screendump {remote_path}\\n' | qm monitor {vmid}"
        code, out, err = self.run(cmd, timeout=60)
        if code != 0:
            raise RuntimeError(f"screendump failed: {err or out}")
        combined = f"{out or ''}{err or ''}"
        if "Enable PNG support" in combined or "Error:" in combined:
            raise RuntimeError(f"screendump failed: {combined.strip() or err or out}")
        code, out, err = self.run(f"test -s '{remote_path}' && echo OK")
        if code != 0 or "OK" not in out:
            raise RuntimeError(f"screendump file missing or empty at {remote_path}: {err}")

    @staticmethod
    def format_qmrestore_cmd(
        archive: str,
        vmid: int,
        storage: str | None = None,
        unique: bool = True,
    ) -> str:
        """Shell command equivalent of an SSH qmrestore (for logs / manual retry)."""
        cmd = f"qmrestore {shlex.quote(archive)} {int(vmid)}"
        if storage:
            cmd += f" --storage {shlex.quote(storage)}"
        if unique:
            cmd += " --unique 1"
        return cmd

    @staticmethod
    def format_pct_restore_cmd(
        archive: str,
        vmid: int,
        storage: str | None = None,
        unique: bool = True,
    ) -> str:
        """Shell command equivalent of an LXC restore (for logs / manual retry)."""
        cmd = f"pct restore {int(vmid)} {shlex.quote(archive)}"
        if storage:
            cmd += f" --storage {shlex.quote(storage)}"
        if unique:
            cmd += " --unique 1"
        return cmd

    def qmrestore(
        self,
        archive: str,
        vmid: int,
        storage: str | None = None,
        unique: bool = True,
        timeout: int = 7200,
    ) -> str:
        """
        Restore a QEMU backup as root via SSH.
        Needed when the archive/config includes host USB/PCI devices that API tokens
        cannot apply ('only root can set usbN config for real devices').
        """
        cmd = self.format_qmrestore_cmd(archive, vmid, storage=storage, unique=unique)
        code, out, err = self.run(cmd, timeout=timeout)
        combined = (out or "") + (err or "")
        if code != 0:
            raise RuntimeError(
                f"qmrestore via SSH failed (exit {code}). "
                f"Command: {cmd}\n{combined[-2000:]}"
            )
        return combined.strip()

    def pct_restore(
        self,
        archive: str,
        vmid: int,
        storage: str | None = None,
        unique: bool = True,
        timeout: int = 7200,
    ) -> str:
        """
        Restore an LXC backup as root via SSH.

        API tokens cannot restore CT bind/device mounts
        ('restoring mpN to bind mount is only possible for root').
        """
        cmd = self.format_pct_restore_cmd(archive, vmid, storage=storage, unique=unique)
        code, out, err = self.run(cmd, timeout=timeout)
        combined = (out or "") + (err or "")
        if code != 0:
            raise RuntimeError(
                f"pct restore via SSH failed (exit {code}). "
                f"Command: {cmd}\n{combined[-2000:]}"
            )
        return combined.strip()

    def qm_delete_keys(self, vmid: int, keys: list[str]) -> list[str]:
        """Delete config keys from a QEMU guest (e.g. usb0, hostpci0, net0)."""
        if not keys:
            return []
        delete_arg = ",".join(sorted(keys))
        code, out, err = self.run(
            f"qm set {int(vmid)} --delete {shlex.quote(delete_arg)}",
            timeout=120,
        )
        if code != 0:
            raise RuntimeError(f"qm set --delete failed: {err or out}")
        return list(keys)

    def pct_delete_keys(self, vmid: int, keys: list[str]) -> list[str]:
        """Delete config keys from an LXC guest (e.g. net0, mp0 bind mounts)."""
        if not keys:
            return []
        delete_arg = ",".join(sorted(keys))
        code, out, err = self.run(
            f"pct set {int(vmid)} --delete {shlex.quote(delete_arg)}",
            timeout=120,
        )
        if code != 0:
            raise RuntimeError(f"pct set --delete failed: {err or out}")
        return list(keys)

    def clear_protection(self, guest_type: str, vmid: int) -> None:
        """Clear Proxmox protection so a test guest can be destroyed."""
        vid = int(vmid)
        if guest_type == "qemu":
            cmd = f"qm set {vid} --protection 0"
        else:
            cmd = f"pct set {vid} --protection 0"
        code, out, err = self.run(cmd, timeout=60)
        combined = f"{out or ''}{err or ''}".lower()
        if code != 0 and "does not exist" not in combined and "no such" not in combined:
            raise RuntimeError(f"clear protection failed: {err or out}")

    def unlock_guest(self, guest_type: str, vmid: int) -> None:
        """Best-effort unlock of a QEMU/LXC guest (safe if not locked)."""
        vid = int(vmid)
        if guest_type == "qemu":
            self.run(f"qm unlock {vid} || true")
            self.run(f"rm -f /var/lock/qemu-server/lock-{vid}.conf")
            return
        self.run(f"pct unlock {vid} || true")

    def destroy_guest(self, guest_type: str, vmid: int) -> str:
        """Stop and destroy a test guest as root. Returns 'deleted' or 'already gone'."""
        vid = int(vmid)
        self.unlock_guest(guest_type, vid)
        try:
            self.clear_protection(guest_type, vid)
        except Exception:  # noqa: BLE001
            pass
        if guest_type == "qemu":
            self.run(f"qm stop {vid} --timeout 30 || true", timeout=60)
            code, out, err = self.run(
                f"qm destroy {vid} --purge 1 --destroy-unreferenced-disks 1",
                timeout=600,
            )
        else:
            self.run(f"pct stop {vid} --timeout 30 || true", timeout=60)
            code, out, err = self.run(
                f"pct destroy {vid} --purge 1 --force 1",
                timeout=600,
            )
        combined = f"{out or ''}{err or ''}"
        low = combined.lower()
        if code != 0:
            if "does not exist" in low or "no such configuration" in low:
                return "already gone"
            raise RuntimeError(f"destroy {vid} failed: {combined[-2000:]}")
        return "deleted"

    def fetch_file(self, remote_path: str, local_path: str) -> None:
        assert self.client is not None
        sftp = self.client.open_sftp()
        try:
            sftp.get(remote_path, local_path)
        finally:
            sftp.close()
        self.run(f"rm -f '{remote_path}'")
