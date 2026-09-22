"""SSH session helper (paramiko) for the Terminal tool."""

from __future__ import annotations

import base64
import hashlib
import threading
from collections.abc import Callable
from pathlib import Path


class HostKeyMismatchError(RuntimeError):
    """Host key present but does not match known_hosts."""

    def __init__(self, host: str, port: int, fingerprint: str) -> None:
        super().__init__(f"host key mismatch for {host}:{port}")
        self.host = host
        self.port = port
        self.fingerprint = fingerprint


class MissingHostKeyError(RuntimeError):
    """Host key not yet trusted."""

    def __init__(self, host: str, port: int, fingerprint: str) -> None:
        super().__init__(f"missing host key for {host}:{port}")
        self.host = host
        self.port = port
        self.fingerprint = fingerprint


def host_key_fingerprint(key) -> str:
    """OpenSSH-style SHA256 fingerprint."""
    digest = hashlib.sha256(key.asbytes()).digest()
    b64 = base64.b64encode(digest).decode("ascii").rstrip("=")
    return f"SHA256:{b64}"


def inspect_host_key(host: str, port: int = 22) -> tuple[str, str]:
    """Return (status, fingerprint). status is ok|missing|mismatch|unknown."""
    try:
        import paramiko
    except ImportError:
        return "unknown", ""
    try:
        key = paramiko.Transport((host, int(port))).get_remote_server_key()
    except Exception:
        # Offline / not SSH — caller will fail on connect with a real error.
        return "unknown", ""
    fp = host_key_fingerprint(key)
    known = paramiko.HostKeys()
    known_hosts = Path.home() / ".ssh" / "known_hosts"
    try:
        if known_hosts.exists():
            known.load(str(known_hosts))
    except Exception:
        return "missing", fp
    candidates = known.lookup(host) or known.lookup(f"[{host}]:{port}")
    if not candidates:
        return "missing", fp
    for _key_type, known_key in candidates.items():
        if known_key.get_name() == key.get_name() and known_key == key:
            return "ok", fp
    return "mismatch", fp


class SshLink:
    """Run one-shot commands over SSH (paramiko)."""

    def __init__(self) -> None:
        self._client = None
        self._lock = threading.Lock()
        self._on_error: Callable[[str], None] | None = None
        self._accept_new_host_key = False

    @property
    def is_connected(self) -> bool:
        return self._client is not None

    def set_error_handler(self, on_error: Callable[[str], None] | None) -> None:
        self._on_error = on_error

    def connect(
        self,
        host: str,
        port: int = 22,
        username: str = "",
        password: str | None = None,
        key_filename: str | None = None,
        timeout: float = 10.0,
        accept_new_host_key: bool = False,
    ) -> None:
        try:
            import paramiko
        except ImportError as exc:
            raise RuntimeError("paramiko not installed") from exc

        self.close()
        client = paramiko.SSHClient()
        # Verify known hosts by default; never silently trust a new key.
        client.load_system_host_keys()
        known_hosts = Path.home() / ".ssh" / "known_hosts"
        if known_hosts.exists():
            client.load_host_keys(str(known_hosts))

        if accept_new_host_key:
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        else:
            client.set_missing_host_key_policy(paramiko.RejectPolicy())

        kwargs: dict = {
            "hostname": host,
            "port": int(port),
            "username": username or None,
            "timeout": timeout,
            "allow_agent": True,
            "look_for_keys": True,
        }
        if password:
            kwargs["password"] = password
        if key_filename:
            kwargs["key_filename"] = key_filename
        try:
            client.connect(**kwargs)
        except paramiko.BadHostKeyException as exc:
            client.close()
            fp = host_key_fingerprint(exc.key) if getattr(exc, "key", None) else ""
            raise HostKeyMismatchError(host, int(port), fp) from exc
        except paramiko.SSHException as exc:
            msg = str(exc)
            client.close()
            if "not found in known_hosts" in msg or "Server" in msg and "not found" in msg:
                # RejectPolicy path — surface as missing host key for UI trust dialog.
                status, fp = inspect_host_key(host, int(port))
                if status in {"missing", "mismatch"}:
                    if status == "mismatch":
                        raise HostKeyMismatchError(host, int(port), fp) from exc
                    raise MissingHostKeyError(host, int(port), fp) from exc
            raise
        except Exception:
            client.close()
            raise
        self._client = client
        if accept_new_host_key:
            try:
                known_hosts.parent.mkdir(parents=True, exist_ok=True)
                client.save_host_keys(str(known_hosts))
            except Exception:
                pass

    def exec_command(self, command: str, timeout: float = 30.0) -> tuple[int, str, str]:
        """Return (exit_status, stdout, stderr)."""
        with self._lock:
            if self._client is None:
                raise RuntimeError("SSH not connected")
            stdin, stdout, stderr = self._client.exec_command(command, timeout=timeout)
            stdin.close()
            out = stdout.read().decode("utf-8", errors="replace")
            err = stderr.read().decode("utf-8", errors="replace")
            status = stdout.channel.recv_exit_status()
            return status, out, err

    def _sftp(self):
        with self._lock:
            if self._client is None:
                raise RuntimeError("SSH not connected")
            return self._client.open_sftp()

    def sftp_listdir(self, remote_path: str) -> list[tuple[str, str, int]]:
        """List a remote directory. Returns [(name, kind, size), ...].

        kind is "dir" or "file"; size is 0 for dirs.
        """
        sftp = self._sftp()
        try:
            out: list[tuple[str, str, int]] = []
            for attr in sftp.listdir_attr(remote_path or "."):
                name = attr.filename
                import stat as statmod

                is_dir = statmod.S_ISDIR(attr.st_mode or 0)
                kind = "dir" if is_dir else "file"
                size = 0 if is_dir else int(attr.st_size or 0)
                out.append((name, kind, size))
            out.sort(key=lambda x: (0 if x[1] == "dir" else 1, x[0].lower()))
            return out
        finally:
            sftp.close()

    def sftp_upload(self, local_path: str, remote_path: str, callback=None) -> None:
        sftp = self._sftp()
        try:
            sftp.put(local_path, remote_path, callback=callback)
        finally:
            sftp.close()

    def sftp_download(self, remote_path: str, local_path: str, callback=None) -> None:
        sftp = self._sftp()
        try:
            sftp.get(remote_path, local_path, callback=callback)
        finally:
            sftp.close()

    def sftp_mkdir(self, remote_path: str) -> None:
        sftp = self._sftp()
        try:
            sftp.mkdir(remote_path)
        finally:
            sftp.close()

    def sftp_remove(self, remote_path: str) -> None:
        sftp = self._sftp()
        try:
            sftp.remove(remote_path)
        finally:
            sftp.close()

    def close(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
