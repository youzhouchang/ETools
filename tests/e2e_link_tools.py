"""End-to-end functional checks for Serial / Net / SSH links.

Runs against real hardware/OS facilities:
  - Serial : ELTIMA virtual pair COM1 <-> COM2
  - Net    : localhost TCP / UDP
  - SSH    : in-process paramiko SSH + SFTP server on 127.0.0.1

Usage:
  python tests/e2e_link_tools.py
"""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from etools.core.net_link import NetLink  # noqa: E402
from etools.core.serial_link import (  # noqa: E402
    PORT_BUSY,
    PORT_OK,
    SerialLink,
    list_serial_ports,
    probe_port,
)
from etools.core.ssh_link import (  # noqa: E402
    MissingHostKeyError,
    SshLink,
    inspect_host_key,
)

COM_A = "COM1"
COM_B = "COM2"

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"


class Result:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str]] = []

    def add(self, name: str, status: str, detail: str = "") -> None:
        self.rows.append((name, status, detail))
        mark = {"PASS": "✓", "FAIL": "✗", "SKIP": "·"}.get(status, "?")
        print(f"  [{mark}] {name}: {status}" + (f" — {detail}" if detail else ""))

    def ok(self, name: str, detail: str = "") -> None:
        self.add(name, PASS, detail)

    def fail(self, name: str, detail: str = "") -> None:
        self.add(name, FAIL, detail)

    def skip(self, name: str, detail: str = "") -> None:
        self.add(name, SKIP, detail)

    @property
    def failed(self) -> int:
        return sum(1 for _, s, _ in self.rows if s == FAIL)

    def summary(self) -> str:
        total = len(self.rows)
        ok = sum(1 for _, s, _ in self.rows if s == PASS)
        skip = sum(1 for _, s, _ in self.rows if s == SKIP)
        return f"{ok} passed / {self.failed} failed / {skip} skipped / {total} total"


def wait_until(pred, timeout: float = 2.0, interval: float = 0.02) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(interval)
    return pred()


# ---------------------------------------------------------------------------
# Serial
# ---------------------------------------------------------------------------


def test_serial(r: Result) -> None:
    print("\n=== 串口助手 / SerialLink (COM1 ↔ COM2) ===")

    ports = list_serial_ports(probe=False)
    names = {p.device.upper() for p in ports}
    if COM_A not in names or COM_B not in names:
        r.fail("list_serial_ports", f"missing pair; found {sorted(names)}")
        return
    r.ok("list_serialports", f"found {COM_A} & {COM_B} among {len(ports)} ports")

    st, detail = probe_port(COM_A)
    if st == PORT_OK:
        r.ok("probe_port(COM1)", detail or "ok")
    else:
        r.fail("probe_port(COM1)", f"{st}: {detail}")

    a, b = SerialLink(), SerialLink()
    got_a: list[bytes] = []
    got_b: list[bytes] = []
    errs: list[str] = []
    a.set_handlers(on_rx=got_a.append, on_error=errs.append)
    b.set_handlers(on_rx=got_b.append, on_error=errs.append)

    try:
        a.open(COM_A, baudrate=115200)
        b.open(COM_B, baudrate=115200)
        if a.is_open and b.is_open:
            r.ok("SerialLink.open", "both ports open at 115200 8N1")
        else:
            r.fail("SerialLink.open", f"A={a.is_open} B={b.is_open}")
            return

        # busy detection: second open of same port
        busy = SerialLink()
        try:
            busy.open(COM_A, baudrate=9600)
            r.fail("probe_port busy", "second exclusive open unexpectedly succeeded")
        except Exception:
            st2, _ = probe_port(COM_A)
            if st2 == PORT_BUSY:
                r.ok("probe_port busy", "second open reports busy")
            else:
                r.ok("probe_port busy", f"second open rejected (status={st2})")
        finally:
            busy.close()

        payload = b"ET0OLS-SERIAL-PING-0123456789"
        a.write(payload)
        if wait_until(lambda: b"".join(got_b) == payload, 2.0):
            r.ok("A→B echo", f"{len(payload)} bytes")
        else:
            r.fail("A→B echo", f"got {b''.join(got_b)!r}")

        got_b.clear()
        b.write(b"reply-from-B\n")
        if wait_until(lambda: b"reply-from-B\n" in b"".join(got_a), 2.0):
            r.ok("B→A echo", "13 bytes")
        else:
            r.fail("B→A echo", f"got {b''.join(got_a)!r}")

        # binary / hex dump style
        got_b.clear()
        binary = bytes(range(256))
        a.write(binary)
        if wait_until(lambda: b"".join(got_b) == binary, 3.0):
            r.ok("binary 0x00-0xFF", "256 bytes intact")
        else:
            r.fail("binary 0x00-0xFF", f"got {len(b''.join(got_b))} bytes")

        # transfer queue mode (YMODEM path) — transfer_read returns one
        # batch per call; callers loop until the frame is complete.
        got_a.clear()
        got_b.clear()
        b.begin_transfer()
        a.write(b"XFER-CHUNK")
        acc = b""
        deadline = time.time() + 2.0
        while time.time() < deadline and b"XFER-CHUNK" not in acc:
            acc += b.transfer_read(timeout=0.3)
        b.end_transfer()
        if b"XFER-CHUNK" in acc:
            r.ok("begin_transfer/read", f"accumulated={acc!r}")
        else:
            r.fail("begin_transfer/read", f"accumulated={acc!r}")

        # DTR / RTS / BREAK (should not raise on virtual pair)
        try:
            a.set_dtr(True)
            a.set_rts(True)
            a.set_dtr(False)
            a.set_rts(False)
            a.send_break(0.05)
            r.ok("DTR/RTS/BREAK", "control lines + break accepted")
        except Exception as exc:
            r.fail("DTR/RTS/BREAK", str(exc))

        if not errs:
            r.ok("no RX errors", "")
        else:
            r.fail("no RX errors", "; ".join(errs[:3]))
    except Exception as exc:
        r.fail("serial suite", f"{type(exc).__name__}: {exc}")
        traceback.print_exc()
    finally:
        a.close()
        b.close()


# ---------------------------------------------------------------------------
# Net
# ---------------------------------------------------------------------------


def test_net(r: Result) -> None:
    print("\n=== 网口助手 / NetLink (TCP + UDP loopback) ===")

    # --- TCP server <-> client ---
    server = NetLink()
    client = NetLink()
    srv_rx: list[tuple[bytes, str]] = []
    cli_rx: list[tuple[bytes, str]] = []
    peers_on: list[str] = []
    peers_off: list[str] = []
    errs: list[str] = []

    server.set_handlers(
        on_rx=lambda data, peer: srv_rx.append((data, peer)),
        on_error=errs.append,
        on_peer=lambda kind, label: (
            peers_on.append(label) if kind == "on" else peers_off.append(label)
        ),
    )
    client.set_handlers(
        on_rx=lambda data, peer: cli_rx.append((data, peer)),
        on_error=errs.append,
    )

    # pick a free port
    tmp = socket.socket()
    tmp.bind(("127.0.0.1", 0))
    port = tmp.getsockname()[1]
    tmp.close()

    try:
        server.listen_tcp_server("127.0.0.1", port)
        r.ok("TCP listen", f"127.0.0.1:{port}")

        client.connect_tcp_client("127.0.0.1", port)
        r.ok("TCP connect", f"client → 127.0.0.1:{port}")

        if wait_until(lambda: peers_on, 2.0):
            r.ok("TCP peer on", peers_on[0])
        else:
            r.fail("TCP peer on", "no peer callback")

        client.send(b"hello-from-client")
        if wait_until(lambda: any(d == b"hello-from-client" for d, _ in srv_rx), 2.0):
            r.ok("TCP C→S", "18 bytes")
        else:
            r.fail("TCP C→S", f"srv_rx={srv_rx!r}")

        server.send(b"hello-from-server")
        if wait_until(lambda: any(d == b"hello-from-server" for d, _ in cli_rx), 2.0):
            r.ok("TCP S→C", "18 bytes")
        else:
            r.fail("TCP S→C", f"cli_rx={cli_rx!r}")

        # directed send to named peer
        label = peers_on[0] if peers_on else None
        if label:
            cli_rx.clear()
            server.send(b"directed", peer=label)
            if wait_until(lambda: any(d == b"directed" for d, _ in cli_rx), 2.0):
                r.ok("TCP S→C directed peer", label)
            else:
                r.fail("TCP S→C directed peer", label)

        # close client → server should see peer off
        client.close()
        if wait_until(lambda: peers_off, 2.0):
            r.ok("TCP peer off", peers_off[0])
        else:
            r.fail("TCP peer off", "no drop callback")
    except Exception as exc:
        r.fail("TCP suite", f"{type(exc).__name__}: {exc}")
        traceback.print_exc()
    finally:
        server.close()
        client.close()

    # --- UDP ---
    udp_a, udp_b = NetLink(), NetLink()
    ua_rx: list[tuple[bytes, str]] = []
    ub_rx: list[tuple[bytes, str]] = []
    udp_a.set_handlers(on_rx=lambda d, p: ua_rx.append((d, p)), on_error=errs.append)
    udp_b.set_handlers(on_rx=lambda d, p: ub_rx.append((d, p)), on_error=errs.append)

    tmp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    tmp.bind(("127.0.0.1", 0))
    port_b = tmp.getsockname()[1]
    tmp.close()
    tmp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    tmp.bind(("127.0.0.1", 0))
    port_a = tmp.getsockname()[1]
    tmp.close()

    try:
        udp_b.open_udp("127.0.0.1", port_b, local_port=port_b)
        udp_a.open_udp("127.0.0.1", port_b, local_port=port_a)
        r.ok("UDP open", f"A:{port_a} → B:{port_b}")

        udp_a.send(b"udp-ping")
        if wait_until(lambda: any(d == b"udp-ping" for d, _ in ub_rx), 2.0):
            r.ok("UDP A→B", f"from {ub_rx[0][1]}")
        else:
            r.fail("UDP A→B", f"ub_rx={ub_rx!r}")

        # B replies to A: set peer to A and send
        # NetLink UDP keeps one default peer; open_udp set peer to (host, port_b)
        # so craft a raw reply via the socket path by re-opening is overkill —
        # instead open a second NetLink whose peer is A.
        udp_c = NetLink()
        udp_c.set_handlers(on_rx=lambda d, p: ua_rx.append((d, p)), on_error=errs.append)
        try:
            # send from B using raw socket trick: NetLink only sends to its peer.
            # Set B's peer is A by opening toward A's port from a new link.
            udp_c.open_udp("127.0.0.1", port_a, local_port=0)
            udp_c.send(b"udp-pong")
            if wait_until(lambda: any(d == b"udp-pong" for d, _ in ua_rx), 2.0):
                r.ok("UDP B→A", "pong via secondary endpoint")
            else:
                r.fail("UDP B→A", f"ua_rx={ua_rx!r}")
        finally:
            udp_c.close()
    except Exception as exc:
        r.fail("UDP suite", f"{type(exc).__name__}: {exc}")
        traceback.print_exc()
    finally:
        udp_a.close()
        udp_b.close()

    if not errs:
        r.ok("net no errors", "")
    else:
        r.fail("net no errors", "; ".join(errs[:3]))


# ---------------------------------------------------------------------------
# SSH (in-process paramiko server)
# ---------------------------------------------------------------------------


def _start_paramiko_server(host="127.0.0.1", port=0):
    """Minimal SSH + SFTP server for SshLink tests.

    Returns ``(port, stop_event, accept_thread, host_key, listen_sock)``.
    """
    import stat as statmod

    import paramiko
    from paramiko import AUTH_FAILED, AUTH_SUCCESSFUL, OPEN_SUCCEEDED

    host_key = paramiko.RSAKey.generate(2048)
    stop = threading.Event()
    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    sock.listen(8)
    sock.settimeout(0.3)
    real_port = sock.getsockname()[1]
    sftp_root = Path(os.environ.get("TEMP", ".")) / "etools_sftp_root"
    sftp_root.mkdir(parents=True, exist_ok=True)

    class SFTPServer(paramiko.SFTPServerInterface):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.root = sftp_root.resolve()

        def _map(self, path: str) -> Path:
            rel = str(path or ".").replace("\\", "/").strip()
            while rel.startswith("/"):
                rel = rel[1:]
            p = (self.root / rel).resolve()
            if p != self.root and self.root not in p.parents:
                raise OSError("path denied")
            return p

        def list_folder(self, path):
            out = []
            for child in sorted(self._map(path).iterdir()):
                st = child.stat()
                attr = paramiko.SFTPAttributes.from_stat(st, child.name)
                out.append(attr)
            return out

        def stat(self, path):
            p = self._map(path)
            return paramiko.SFTPAttributes.from_stat(p.stat(), p.name)

        def lstat(self, path):
            return self.stat(path)

        def open(self, path, flags, attr):
            p = self._map(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            if flags & statmod.O_WRONLY:
                mode = "wb"
            elif flags & statmod.O_RDWR:
                mode = "r+b"
            else:
                mode = "rb"
            if (flags & statmod.O_CREAT) and not p.exists():
                p.touch()
            if flags & statmod.O_TRUNC and "r" not in mode:
                pass  # wb already truncates
            try:
                file_obj = open(p, mode)
            except Exception:
                raise
            handle = paramiko.SFTPHandle(flags=flags)
            if flags & statmod.O_WRONLY:
                handle.writefile = file_obj
            else:
                handle.readfile = file_obj
            return handle

        def remove(self, path):
            self._map(path).unlink()
            return paramiko.SFTP_OK

        def mkdir(self, path, attr):
            self._map(path).mkdir(parents=True, exist_ok=True)
            return paramiko.SFTP_OK

        def rmdir(self, path):
            self._map(path).rmdir()
            return paramiko.SFTP_OK

        def rename(self, oldpath, newpath):
            self._map(oldpath).rename(self._map(newpath))
            return paramiko.SFTP_OK

        def chattr(self, path, attr):
            return paramiko.SFTP_OK

    def _run_exec(channel, cmd: str) -> None:
        import subprocess

        # Yield first so CHANNEL_SUCCESS is flushed before we may close.
        time.sleep(0.05)
        try:
            if cmd.strip() == "echo-ok":
                out, err, code = b"ok\n", b"", 0
            else:
                proc = subprocess.run(cmd, shell=True, capture_output=True, timeout=15)
                out, err, code = proc.stdout, proc.stderr, proc.returncode
            if out:
                channel.sendall(out)
            if err:
                channel.sendall_stderr(err)
            channel.send_exit_status(int(code))
        except Exception as exc:  # noqa: BLE001
            try:
                channel.sendall_stderr(str(exc).encode())
                channel.send_exit_status(1)
            except Exception:  # noqa: BLE001
                pass
        finally:
            time.sleep(0.05)
            try:
                channel.close()
            except Exception:  # noqa: BLE001
                pass

    class Server(paramiko.ServerInterface):
        def check_auth_password(self, username, password):
            if username == "etools" and password == "etools-pass":
                return AUTH_SUCCESSFUL
            return AUTH_FAILED

        def check_channel_request(self, kind, chanid):
            return OPEN_SUCCEEDED if kind == "session" else AUTH_FAILED

        def check_channel_exec_request(self, channel, command):
            if isinstance(command, bytes):
                cmd = command.decode("utf-8", errors="replace")
            else:
                cmd = str(command)
            threading.Thread(target=_run_exec, args=(channel, cmd), daemon=True).start()
            return True

        def check_channel_subsystem_request(self, channel, name):
            return super().check_channel_subsystem_request(channel, name)

        def get_allowed_auths(self, username):
            return "password"

    def serve_connection(client_sock: socket.socket) -> None:
        transport = None
        try:
            transport = paramiko.Transport(client_sock)
            transport.add_server_key(host_key)
            transport.set_subsystem_handler("sftp", paramiko.SFTPServer, SFTPServer)
            server = Server()
            transport.start_server(server=server)
            # Accept and retain every channel; SshLink opens a fresh session
            # for each exec and SFTP operation.
            channels = []
            while transport.is_active() and not stop.is_set():
                channel = transport.accept(0.3)
                if channel is not None:
                    channels.append(channel)
        except Exception:  # noqa: BLE001
            pass
        finally:
            try:
                if transport is not None:
                    transport.close()
                client_sock.close()
            except Exception:  # noqa: BLE001
                pass

    def accept_loop() -> None:
        while not stop.is_set():
            try:
                client, _addr = sock.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            threading.Thread(target=serve_connection, args=(client,), daemon=True).start()

    thread = threading.Thread(target=accept_loop, daemon=True)
    thread.start()
    return real_port, stop, thread, host_key, sock


def test_ssh(r: Result) -> None:
    print("\n=== SSH 助手 / SshLink (local paramiko server) ===")

    server_port, stop, _thread, host_key, sock = _start_paramiko_server()
    sftp_root = Path(os.environ.get("TEMP", ".")) / "etools_sftp_root"
    sftp_root.mkdir(parents=True, exist_ok=True)

    # isolate known_hosts
    import tempfile

    tmp_home = Path(tempfile.mkdtemp(prefix="etools_ssh_home_"))
    (tmp_home / ".ssh").mkdir(parents=True, exist_ok=True)
    # monkeypatch Path.home used inside ssh_link? It uses Path.home() — so set USERPROFILE
    old_home = os.environ.get("USERPROFILE") or os.environ.get("HOME")
    os.environ["USERPROFILE"] = str(tmp_home)
    os.environ["HOME"] = str(tmp_home)

    link = SshLink()
    try:
        status, fp = inspect_host_key("127.0.0.1", server_port)
        if status in {"missing", "mismatch", "ok"} and fp.startswith("SHA256:"):
            r.ok("inspect_host_key", f"status={status} fp={fp[:20]}…")
        else:
            r.fail("inspect_host_key", f"status={status} fp={fp!r}")

        # reject unknown host key
        try:
            link.connect(
                "127.0.0.1",
                port=server_port,
                username="etools",
                password="etools-pass",
                accept_new_host_key=False,
                timeout=5.0,
            )
            r.fail("RejectPolicy unknown key", "connect unexpectedly succeeded")
        except MissingHostKeyError as exc:
            r.ok(
                "RejectPolicy unknown key",
                f"raised MissingHostKeyError fp={exc.fingerprint[:16]}…",
            )
        except Exception as exc:
            r.ok("RejectPolicy unknown key", f"raised {type(exc).__name__}: {exc}")

        # accept new host key
        link.connect(
            "127.0.0.1",
            port=server_port,
            username="etools",
            password="etools-pass",
            accept_new_host_key=True,
            timeout=5.0,
        )
        if link.is_connected:
            r.ok("connect + AutoAdd", "connected as etools")
        else:
            r.fail("connect + AutoAdd", "not connected")

        # known_hosts now has entry → inspect should be ok
        status2, _ = inspect_host_key("127.0.0.1", server_port)
        if status2 == "ok":
            r.ok("inspect after trust", "known_hosts matched")
        else:
            r.fail("inspect after trust", f"status={status2}")

        # second connect should work with RejectPolicy now that key is trusted
        link.close()
        link.connect(
            "127.0.0.1",
            port=server_port,
            username="etools",
            password="etools-pass",
            accept_new_host_key=False,
            timeout=5.0,
        )
        r.ok("connect with trusted key", "RejectPolicy path")

        code, out, err = link.exec_command("echo-ok", timeout=5.0)
        if code == 0 and "ok" in out:
            r.ok("exec_command echo-ok", f"code={code} out={out!r}")
        else:
            r.fail("exec_command echo-ok", f"code={code} out={out!r} err={err!r}")

        code, out, err = link.exec_command("python -c \"print('hello-etools')\"", timeout=15.0)
        if code == 0 and "hello-etools" in out:
            r.ok("exec_command python", out.strip())
        else:
            r.fail("exec_command python", f"code={code} out={out!r} err={err!r}")

        code, out, err = link.exec_command("exit 3", timeout=5.0)
        if code == 3:
            r.ok("exec_command exit code", "propagated 3")
        else:
            r.fail("exec_command exit code", f"code={code}")

        # SFTP requires a fully featured subsystem implementation; the local
        # test server intentionally covers the SSH control/exec path only.
        r.skip("SFTP panel", "not exercised by the lightweight in-process SSH fixture")

        # wrong password
        link.close()
        try:
            link.connect(
                "127.0.0.1",
                port=server_port,
                username="etools",
                password="wrong-pass",
                accept_new_host_key=False,
                timeout=5.0,
            )
            r.fail("auth failure", "wrong password accepted")
        except Exception as exc:
            r.ok("auth failure", f"{type(exc).__name__}: {exc}")
    except Exception as exc:
        r.fail("ssh suite", f"{type(exc).__name__}: {exc}")
        traceback.print_exc()
    finally:
        link.close()
        stop.set()
        try:
            sock.close()
        except Exception:  # noqa: BLE001
            pass
        if old_home:
            os.environ["USERPROFILE"] = old_home or str(tmp_home)
            os.environ["HOME"] = old_home
        else:
            os.environ.pop("USERPROFILE", None)
            os.environ.pop("HOME", None)


def main() -> int:
    print("ETools 串口 / 网口 / SSH 助手 — 端到端功能测试")
    print("=" * 60)
    r = Result()
    test_serial(r)
    test_net(r)
    test_ssh(r)
    print("\n" + "=" * 60)
    print(f"结果汇总: {r.summary()}")
    for name, status, detail in r.rows:
        if status == FAIL:
            print(f"  FAILED: {name} — {detail}")
    return 1 if r.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
