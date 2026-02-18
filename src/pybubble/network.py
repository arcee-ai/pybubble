from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import time
from tempfile import NamedTemporaryFile


def _is_installed(command: list[str]) -> bool:
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5.0,
        )
        if result.stderr and b"command not found" in result.stderr.lower():
            return False
        return True
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def system_supports_slirp4netns() -> bool:
    return _is_installed(["slirp4netns", "--help"])


class SandboxNetwork:
    def __init__(self, *, enable_outbound: bool = False, allow_host_loopback: bool = False):
        if not system_supports_slirp4netns():
            raise ValueError(
                "slirp4netns was not found, but enable_network was True. Please ensure it is installed and in your PATH."
            )

        self.namespace_watchdog: subprocess.Popen | None = None
        self.hosts_tmp = None
        self.resolv_tmp = None
        self.bridge_api_socket = None
        self.outbound_bridge = None

        try:
            self.namespace_watchdog = subprocess.Popen(
                [
                    "unshare",
                    "--user",
                    "--map-root-user",
                    "--net",
                    "--keep-caps",
                    "sh",
                    "-c",
                    "sleep infinity",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._ensure_network_ready_blocking(self.namespace_watchdog.pid)
            self._ensure_loopback_up(self.namespace_watchdog.pid)

            self.hosts_tmp = NamedTemporaryFile(dir="/tmp")
            self.hosts_tmp.write(b"127.0.0.1 localhost\n::1 localhost\n127.0.1.1 sandbox\n")
            self.hosts_tmp.flush()

            if enable_outbound:
                self.bridge_api_socket = NamedTemporaryFile(dir="/tmp", suffix=".sock")
                bridge_cmd = [
                    "slirp4netns",
                    "--api-socket",
                    str(self.bridge_api_socket.name),
                ]
                if not allow_host_loopback:
                    bridge_cmd.append("--disable-host-loopback")

                self.outbound_bridge = subprocess.Popen(
                    [*bridge_cmd, "--configure", f"{self.namespace_watchdog.pid}", "tap0"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self.resolv_tmp = NamedTemporaryFile(dir="/tmp")
                self.resolv_tmp.write(b"nameserver 8.8.8.8\nnameserver 8.8.4.4\n")
                self.resolv_tmp.flush()
        except Exception:
            self.close()
            raise

    async def ensure_network_ready(self, ns_pid: int, timeout: float = 0.5) -> None:
        user_ns = f"/proc/{ns_pid}/ns/user"
        net_ns = f"/proc/{ns_pid}/ns/net"
        deadline = asyncio.get_running_loop().time() + timeout
        last_error = ""

        while True:
            if not (os.path.exists(user_ns) and os.path.exists(net_ns)):
                last_error = f"Network namespace for PID {ns_pid} does not exist yet."
            else:
                probe = await asyncio.create_subprocess_exec(
                    "nsenter",
                    f"--user={user_ns}",
                    f"--net={net_ns}",
                    "--preserve-credentials",
                    "--",
                    "true",
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )
                _, probe_stderr = await probe.communicate()
                if probe.returncode == 0:
                    return
                last_error = (
                    probe_stderr.decode(errors="replace").strip()
                    if probe_stderr
                    else f"nsenter probe failed with exit code {probe.returncode}"
                )

            if asyncio.get_running_loop().time() >= deadline:
                raise RuntimeError(
                    f"Network namespace for PID {ns_pid} was not ready within {timeout:.2f}s: {last_error}"
                )
            await asyncio.sleep(0.01)

    def namespace_pid(self, ns_pid_override: int | None = None) -> int:
        return self.namespace_watchdog.pid if ns_pid_override is None else ns_pid_override

    def wrap_command(self, command: list[str], ns_pid: int) -> list[str]:
        return [
            "nsenter",
            f"--user=/proc/{ns_pid}/ns/user",
            f"--net=/proc/{ns_pid}/ns/net",
            "--preserve-credentials",
            "--",
            *command,
        ]

    def bwrap_args(self) -> list[str]:
        args = ["--ro-bind", self.hosts_tmp.name, "/etc/hosts", "--share-net", "--cap-add", "CAP_NET_RAW"]
        if self.resolv_tmp is not None:
            args.extend(["--ro-bind", self.resolv_tmp.name, "/etc/resolv.conf"])
        return args

    def forward_port(self, sandbox_port: int, host_port: int, proto: str = "tcp") -> dict:
        if self.outbound_bridge is None:
            raise RuntimeError("Port forwarding requires enable_outbound=True.")

        msg = json.dumps(
            {
                "execute": "add_hostfwd",
                "arguments": {
                    "proto": proto,
                    "host_addr": "127.0.0.1",
                    "host_port": host_port,
                    "guest_addr": "10.0.2.100",
                    "guest_port": sandbox_port,
                },
            }
        ) + "\n"
        sock = self._connect_bridge_api_socket()
        try:
            sock.sendall(msg.encode())
            return json.loads(sock.recv(4096))
        finally:
            sock.close()

    def _connect_bridge_api_socket(self, timeout: float = 1.0) -> socket.socket:
        assert self.bridge_api_socket is not None
        assert self.outbound_bridge is not None

        socket_path = self.bridge_api_socket.name
        deadline = time.monotonic() + timeout
        last_error = "API socket not ready yet"

        while True:
            if self.outbound_bridge.poll() is not None:
                raise RuntimeError("slirp4netns exited before API socket became ready.")

            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                sock.connect(socket_path)
                return sock
            except OSError as exc:
                last_error = str(exc)
                sock.close()

            if time.monotonic() >= deadline:
                raise RuntimeError(f"Timed out waiting for slirp4netns API socket: {last_error}")
            time.sleep(0.01)

    def _ensure_network_ready_blocking(self, ns_pid: int, timeout: float = 0.5) -> None:
        user_ns = f"/proc/{ns_pid}/ns/user"
        net_ns = f"/proc/{ns_pid}/ns/net"
        deadline = time.monotonic() + timeout
        last_error = ""

        while True:
            if self.namespace_watchdog.poll() is not None:
                raise RuntimeError("Network namespace watchdog exited before becoming ready.")

            if not (os.path.exists(user_ns) and os.path.exists(net_ns)):
                last_error = f"Namespace paths for PID {ns_pid} not present yet."
            else:
                probe = subprocess.run(
                    [
                        "nsenter",
                        f"--user={user_ns}",
                        f"--net={net_ns}",
                        "--preserve-credentials",
                        "--",
                        "true",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )
                if probe.returncode == 0:
                    return
                last_error = probe.stderr.decode(errors="replace").strip() or (
                    f"nsenter probe failed with exit code {probe.returncode}"
                )

            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"Network namespace for PID {ns_pid} was not ready within {timeout:.2f}s: {last_error}"
                )
            time.sleep(0.01)

    def _ensure_loopback_up(self, ns_pid: int) -> None:
        user_ns = f"/proc/{ns_pid}/ns/user"
        net_ns = f"/proc/{ns_pid}/ns/net"
        bring_up = subprocess.run(
            [
                "nsenter",
                f"--user={user_ns}",
                f"--net={net_ns}",
                "--preserve-credentials",
                "--",
                "ip",
                "link",
                "set",
                "lo",
                "up",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        if bring_up.returncode != 0:
            stderr = bring_up.stderr.decode(errors="replace").strip()
            raise RuntimeError(f"Failed to bring loopback up in namespace: {stderr}")

    def close(self) -> None:
        if self.outbound_bridge is not None:
            self.outbound_bridge.terminate()
            try:
                self.outbound_bridge.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                self.outbound_bridge.kill()
                self.outbound_bridge.wait(timeout=1.0)
            self.outbound_bridge = None
        if self.namespace_watchdog is not None:
            self.namespace_watchdog.terminate()
            try:
                self.namespace_watchdog.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                self.namespace_watchdog.kill()
                self.namespace_watchdog.wait(timeout=1.0)
            self.namespace_watchdog = None
        if self.resolv_tmp is not None:
            self.resolv_tmp.close()
            self.resolv_tmp = None
        if self.hosts_tmp is not None:
            self.hosts_tmp.close()
            self.hosts_tmp = None
        if self.bridge_api_socket is not None:
            self.bridge_api_socket.close()
            self.bridge_api_socket = None
