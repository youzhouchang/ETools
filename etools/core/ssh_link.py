"""SSH session helper (paramiko) for the Terminal tool."""

from __future__ import annotations

import base64
import hashlib
import socket
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path

from etools.logger import get_logger

log = get_logger("ssh")

#: Upper bound for one-shot command output kept in memory (per stream).
EXEC_OUTPUT_LIMIT = 4 * 1024 * 1024


class _CappedBuffer:
    """Keep up to *limit* bytes; count the rest so the caller can say it was cut."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.buf = bytearray()
        self.truncated = False

    def feed(self, chunk: bytes) -> None:
        room = self.limit - len(self.buf)
        if room > 0:
            self.buf.extend(chunk[:room])
        if len(chunk) > max(room, 0):
            self.truncated = True

    def text(self) -> str:
        data = bytes(self.buf)
        if self.truncated:
            data += f"\n[output truncated at {self.limit} bytes]\n".encode()
        return data.decode("utf-8", errors="replace")


def _drain_channel(
    channel, *, limit: int = EXEC_OUTPUT_LIMIT, idle_timeout: float = 30.0
) -> tuple[str, str]:
    """Read stdout and stderr together until the command exits.

    Reading one stream to EOF first can deadlock: the other stream fills the
    shared SSH window and the server stops sending.
    """
    out, err = _CappedBuffer(limit), _CappedBuffer(limit)
    last = time.monotonic()
    while True:
        busy = False
        while channel.recv_ready():
            out.feed(channel.recv(64 * 1024))
            busy = True
        while channel.recv_stderr_ready():
            err.feed(channel.recv_stderr(64 * 1024))
            busy = True
        if busy:
            last = time.monotonic()
            continue
        if channel.exit_status_ready() and not channel.recv_ready():
            if not channel.recv_stderr_ready():
                break
            continue
        if idle_timeout and time.monotonic() - last > idle_timeout:
            raise TimeoutError(f"no command output for {idle_timeout:.0f}s")
        time.sleep(0.01)
    return out.text(), err.text()


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
        with socket.create_connection((host, int(port)), timeout=5.0) as sock:
            transport = paramiko.Transport(sock)
            try:
                transport.start_client(timeout=5.0)
                key = transport.get_remote_server_key()
            finally:
                transport.close()
    except Exception:
        # Offline / not SSH — caller will fail on connect with a real error.
        return "unknown", ""
    fp = host_key_fingerprint(key)
    known = paramiko.HostKeys()
    known_hosts = Path.home() / ".ssh" / "known_hosts"
    try:
        if known_hosts.exists():
            known.load(str(known_hosts))
    except Exception as exc:  # noqa: BLE001
        log.warning("cannot read %s: %s", known_hosts, exc)
        return "unknown", fp
    candidates = known.lookup(host) or known.lookup(f"[{host}]:{port}")
    if not candidates:
        return "missing", fp
    for _key_type, known_key in candidates.items():
        if known_key.get_name() == key.get_name() and known_key == key:
            return "ok", fp
    return "mismatch", fp


class SshLink:
    """SSH client: an interactive shell plus one-shot commands and SFTP."""

    def __init__(self) -> None:
        self._client = None
        self._shell = None
        self._lock = threading.RLock()
        self._on_error: Callable[[str], None] | None = None
        self._accept_new_host_key = False

    @property
    def is_connected(self) -> bool:
        return self._client is not None

    @property
    def shell_open(self) -> bool:
        return self._shell is not None

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
        expected_fingerprint: str = "",
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

        if accept_new_host_key and expected_fingerprint:
            expected = expected_fingerprint

            class FingerprintPolicy(paramiko.MissingHostKeyPolicy):
                def missing_host_key(self, ssh_client, hostname, key) -> None:
                    actual = host_key_fingerprint(key)
                    if actual != expected:
                        raise HostKeyMismatchError(host, int(port), actual)
                    ssh_client._host_keys.add(hostname, key.get_name(), key)

            client.set_missing_host_key_policy(FingerprintPolicy())
        else:
            # Trusting a new key requires the fingerprint the user confirmed.
            accept_new_host_key = False
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
            except Exception as exc:  # noqa: BLE001
                log.warning("cannot save host key to %s: %s", known_hosts, exc)

    def open_shell(self, width: int = 120, height: int = 32) -> None:
        """Open an interactive PTY. Further keystrokes go through shell_write."""
        with self._lock:
            if self._client is None:
                raise RuntimeError("SSH not connected")
            self._close_shell_unlocked()
            channel = self._client.invoke_shell(
                term="xterm-256color",
                width=max(20, int(width)),
                height=max(8, int(height)),
            )
            self._shell = channel

    def shell_resize(self, width: int, height: int) -> None:
        if not self._lock.acquire(blocking=False):
            return
        try:
            if self._shell is None:
                return
            self._shell.resize_pty(width=max(20, int(width)), height=max(8, int(height)))
        finally:
            self._lock.release()

    def shell_write(self, data: bytes) -> None:
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("SSH transport is busy")
        try:
            if self._shell is None:
                raise RuntimeError("SSH shell is not open")
            self._shell.sendall(bytes(data))
        finally:
            self._lock.release()

    def shell_read(self, max_bytes: int = 4096) -> bytes:
        if not self._lock.acquire(blocking=False):
            return b""
        try:
            channel = self._shell
            if channel is None:
                return b""
            exit_ready = getattr(channel, "exit_status_ready", lambda: False)
            if bool(getattr(channel, "closed", False)) or exit_ready():
                raise ConnectionError("SSH shell closed")
            if not channel.recv_ready():
                return b""
            return channel.recv(max(1, int(max_bytes)))
        finally:
            self._lock.release()

    def close_shell(self) -> None:
        with self._lock:
            self._close_shell_unlocked()

    def _close_shell_unlocked(self) -> None:
        channel, self._shell = self._shell, None
        if channel is not None:
            try:
                channel.close()
            except Exception:
                pass

    def exec_command(self, command: str, timeout: float = 30.0) -> tuple[int, str, str]:
        """Return (exit_status, stdout, stderr)."""
        with self._lock:
            if self._client is None:
                raise RuntimeError("SSH not connected")
            stdin, stdout, _stderr = self._client.exec_command(command, timeout=timeout)
            stdin.close()
            channel = stdout.channel
            out, err = _drain_channel(channel, idle_timeout=timeout)
            return channel.recv_exit_status(), out, err

    @contextmanager
    def _sftp(self):
        with self._lock:
            if self._client is None:
                raise RuntimeError("SSH not connected")
            sftp = self._client.open_sftp()
            try:
                yield sftp
            finally:
                sftp.close()

    def sftp_listdir(self, remote_path: str) -> list[tuple[str, str, int]]:
        """List a remote directory. Returns [(name, kind, size), ...].

        kind is "dir" or "file"; size is 0 for dirs.
        """
        with self._sftp() as sftp:
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

    def sftp_upload(self, local_path: str, remote_path: str, callback=None) -> None:
        with self._sftp() as sftp:
            sftp.put(local_path, remote_path, callback=callback)

    def sftp_download(self, remote_path: str, local_path: str, callback=None) -> None:
        with self._sftp() as sftp:
            sftp.get(remote_path, local_path, callback=callback)

    def sftp_mkdir(self, remote_path: str) -> None:
        with self._sftp() as sftp:
            sftp.mkdir(remote_path)

    def sftp_remove(self, remote_path: str) -> None:
        with self._sftp() as sftp:
            sftp.remove(remote_path)

    def close(self) -> None:
        with self._lock:
            self._close_shell_unlocked()
            client, self._client = self._client, None
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
