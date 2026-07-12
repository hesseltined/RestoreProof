"""
Purpose: SSH helpers for QMP screendump and key generation.
Author: Doug Hesseltine
Created: 2026-07-12
Version: 1.0.0
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import paramiko
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from app.config import get_settings

logger = logging.getLogger(__name__)


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
        """Capture VGA framebuffer via QEMU monitor screendump."""
        # Ensure directory exists
        remote_dir = os.path.dirname(remote_path)
        code, _, err = self.run(f"mkdir -p '{remote_dir}'")
        if code != 0:
            raise RuntimeError(f"mkdir failed: {err}")
        # qm monitor accepts interactive commands; use printf pipe
        cmd = f"printf 'screendump {remote_path}\\n' | qm monitor {vmid}"
        code, out, err = self.run(cmd, timeout=60)
        if code != 0:
            raise RuntimeError(f"screendump failed: {err or out}")
        code, out, err = self.run(f"test -s '{remote_path}' && echo OK")
        if code != 0 or "OK" not in out:
            raise RuntimeError(f"screendump file missing or empty at {remote_path}: {err}")

    def fetch_file(self, remote_path: str, local_path: str) -> None:
        assert self.client is not None
        sftp = self.client.open_sftp()
        try:
            sftp.get(remote_path, local_path)
        finally:
            sftp.close()
        self.run(f"rm -f '{remote_path}'")
