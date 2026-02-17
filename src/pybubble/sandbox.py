import warnings
import asyncio
import fcntl
import os
import struct
import sys
import termios
from pathlib import Path
import subprocess
import tempfile
import uuid

from pybubble.process import SandboxedProcess
from pybubble.rootfs import setup_rootfs

# Path to the bundled default rootfs tarball (ships inside the wheel)
_BUNDLED_ROOTFS = Path(__file__).parent / "data" / "default.tar.zst"

def is_installed(command: list[str]) -> bool:
    """Checks if a command is installed."""
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5.0
        )
        # If there's an error message in stderr (like "command not found"), bwrap is not installed
        if result.stderr and b"command not found" in result.stderr.lower():
            return False
        # If the command succeeded or stderr is empty/minimal, bwrap is installed
        return True
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False

def is_system_compatible() -> bool:
    """Checks if the system has bubblewrap installed."""
    return is_installed(["bwrap", "--help"])

def system_supports_overlayfs() -> bool:
    """Checks if the system supports overlayfs."""
    return is_installed(["fuse-overlayfs", "--help"])

class Sandbox:
    def __init__(
        self,
        rootfs: str | Path | None = None,
        work_dir: str | Path | None = None,
        rootfs_path: str | Path | None = None,
        rootfs_overlay: bool = False,
        rootfs_overlay_path: str | Path | None = None,
        persist_overlayfs: bool = False,
    ):
        """Creates a sandbox from the specified rootfs tarball, expected to be in the form of a tarball or compressed tarball.
        
        Args:
            rootfs: Path to rootfs tarball.  When *None* (the default), the
                bundled rootfs is used.
            work_dir: Path to writable working directory for sandbox sessions. If None, uses a unique directory in `/tmp` (default: None)
            rootfs_path: Path to extract rootfs to. If None, uses unique dir in `~/.cache/pybubble/rootfs` (default: None)
            rootfs_overlay: Whether to allow writing to the rootfs via fuse-overlayfs (default: False)
            rootfs_overlay_path: Path to the overlayfs directory. If None, uses a unique directory in `/tmp` (default: None)
            persist_overlayfs: Whether to skip unmounting the overlayfs after the sandbox exits. rootfs_overlay_path must be provided when this is True. (default: False)
        """
        
        if not is_system_compatible():
            raise RuntimeError("Bubblewrap was not found. Please ensure it is installed and in your PATH.")
        
        # Fall back to the bundled rootfs when none is provided
        if rootfs is None:
            if not _BUNDLED_ROOTFS.exists():
                raise FileNotFoundError(
                    "No rootfs tarball was supplied and the bundled default.tar.zst "
                    "was not found. If you are running from a source checkout, "
                    "build the rootfs first (see docs/build-rootfs.md)."
                )
            rootfs = _BUNDLED_ROOTFS
        
        if work_dir is None:
            self._temp_dir = tempfile.TemporaryDirectory(dir="/tmp")
            self.work_dir = Path(self._temp_dir.name)
        else:
            self._temp_dir = None
            self.work_dir = Path(work_dir)
        
        # Ensure work_dir exists
        Path.mkdir(self.work_dir, parents=True, exist_ok=True)
        
        # Temp directory to mount at /tmp
        self.tmp_dir = tempfile.TemporaryDirectory(dir="/tmp")
        
        # Convert rootfs_path to Path if provided, otherwise None (which triggers caching)
        rootfs_path_obj = Path(rootfs_path) if rootfs_path is not None else None
        
        self.rootfs_dir = setup_rootfs(str(rootfs), rootfs_path_obj)
        
        self.persist_overlayfs = persist_overlayfs
        
        if rootfs_overlay:
            if not system_supports_overlayfs():
                raise RuntimeError("fuse-overlayfs was not found. Please ensure it is installed and in your PATH.")

            self.rootfs_overlay = True
            self.rootfs_overlay_lowerdir = self.rootfs_dir
            
            if rootfs_overlay_path is None:
                if self.persist_overlayfs:
                    raise ValueError("persist_overlayfs was enabled but no rootfs_overlay_path was provided")
                # This needs to be kept as a class member so it gets cleaned up when the sandbox goes out of scope
                self.rootfs_dir_tmp = tempfile.TemporaryDirectory(dir="/tmp")
                self.rootfs_dir = Path(self.rootfs_dir_tmp.name)
            else:
                self.rootfs_dir = Path(rootfs_overlay_path)
                self.rootfs_dir.mkdir(parents=True, exist_ok=True)
            
            upper_dir = self.rootfs_dir / "upper"
            work_dir = self.rootfs_dir / "work"
            self.rootfs_dir = self.rootfs_dir / "mount"
            
            upper_dir.mkdir(parents=True, exist_ok=True)
            work_dir.mkdir(parents=True, exist_ok=True)
            self.rootfs_dir.mkdir(parents=True, exist_ok=True)
            
            fuse_opts = ",".join([
                f"lowerdir={self.rootfs_overlay_lowerdir.absolute()}",
                f"upperdir={upper_dir.absolute()}",
                f"workdir={work_dir.absolute()}",
            ])
            fuse_command = [
                "fuse-overlayfs",
                "-o", fuse_opts,
                str(self.rootfs_dir.absolute()),
            ]
            proc = subprocess.run(fuse_command, capture_output=True, text=True)
            if proc.returncode != 0:
                raise RuntimeError(f"Failed to mount overlayfs: {proc.stderr}")
        else:
            self.rootfs_overlay = False
            self.rootfs_overlay_lowerdir = None
            self.rootfs_overlay_upperdir = None
            self.rootfs_overlay_workdir = None
            

    async def run(
        self,
        command: str,
        allow_network: bool = False,
        timeout: float | None = 10.0,
        stdin_pipe: bool = True,
        stdout_pipe: bool = True,
        stderr_pipe: bool = True,
        use_pty: bool = False,
    ) -> SandboxedProcess:
        """Runs a shell command in the sandbox. Returns a SandboxedProcess.
        
        Args:
            command: Shell command to run
            allow_network: Whether to allow network access
            timeout: Default timeout in seconds for process waits/communication
            stdin_pipe: Whether to pipe stdin for programmatic input (ignored when use_pty is True)
            stdout_pipe: Whether to pipe stdout for programmatic streaming (ignored when use_pty is True)
            stderr_pipe: Whether to pipe stderr for programmatic streaming (ignored when use_pty is True)
            use_pty: Allocate a pseudoterminal for the child process.  The
                returned SandboxedProcess exposes the master fd via
                ``master_fd`` and supports ``set_terminal_size()``.
        """
        process, master_fd = await self._start_process(
            command, allow_network, stdin_pipe, stdout_pipe, stderr_pipe, use_pty
        )
        return SandboxedProcess(process, default_timeout=timeout, master_fd=master_fd)

    async def run_script(self, code: str, allow_network: bool = False, timeout: float | None = 10.0, run_command: str = "python", extension: str = "py") -> SandboxedProcess:
        """Write a script to a temporary file and run it in the sandbox.

        Returns a ``SandboxedProcess`` so the caller can stream output,
        send input, or simply call ``communicate()``.  Defaults to Python,
        but other interpreters can be specified via *run_command*.

        Args:
            code: Code to run
            allow_network: Whether to allow network access
            timeout: Command timeout in seconds
            run_command: Command to run the script (default: "python")
            extension: Extension of the script file (default: "py")
        """
        script_name = f"script_{uuid.uuid4().hex}.{extension}"
        with open(Path(self.tmp_dir.name) / script_name, "w") as f:
            f.write(code)

        process, _ = await self._start_process(
            f"{run_command} /tmp/{script_name}",
            allow_network,
            stdin_pipe=False,
            stdout_pipe=True,
            stderr_pipe=True,
        )
        return SandboxedProcess(process, default_timeout=timeout)


    async def _start_process(
        self,
        command: str,
        allow_network: bool,
        stdin_pipe: bool,
        stdout_pipe: bool,
        stderr_pipe: bool,
        use_pty: bool = False,
    ) -> tuple[asyncio.subprocess.Process, int | None]:
        if use_pty and (stdin_pipe or stdout_pipe or stderr_pipe):
            raise ValueError("PTY mode cannot be used with stdin_pipe, stdout_pipe, or stderr_pipe")
        
        built_command: list[str] = [
            "bwrap",
            "--unshare-all",
            "--die-with-parent",
            "--uid", "1000",
            "--hostname", "sandbox",
            "--ro-bind" if not self.rootfs_overlay else "--bind", str(self.rootfs_dir.absolute()), "/",
            "--bind", str(self.work_dir.absolute()), "/home/sandbox",
            "--dev", "/dev",
            "--proc", "/proc",
            "--bind", str(self.tmp_dir.name), "/tmp",
            "--clearenv",
            "--setenv", "HOME", "/home/sandbox",
            "--setenv", "PATH", "/usr/bin:/bin:/usr/local/bin:/sbin/",
            "--chdir", "/home/sandbox",
        ]

        # --new-session mitigates an attack where the child process can take over the terminal that called it by injecting inputs.
        # When we use a PTY, this attack is instead mitigated by the fact that the child process only has access to the PTY, not the host terminal.
        if not use_pty:
            built_command.append("--new-session")
        
        if allow_network:
            built_command.extend(["--ro-bind", "/etc/resolv.conf", "/etc/resolv.conf", "--share-net"])
        
        built_command.extend(["bash", "-c", command])
        
        master_fd: int | None = None

        if use_pty:
            master_fd, slave_fd = os.openpty()
            try:
                if sys.stdin.isatty():
                    size = fcntl.ioctl(sys.stdin.fileno(), termios.TIOCGWINSZ, b"\x00" * 8)
                else:
                    size = struct.pack("HHHH", 24, 80, 0, 0)
                fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, size)
            except OSError:
                pass

            def _pty_setup() -> None:
                """Create a new session and acquire the PTY as controlling terminal."""
                os.setsid()
                fcntl.ioctl(0, termios.TIOCSCTTY, 0)

            proc = await asyncio.create_subprocess_exec(
                *built_command,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                preexec_fn=_pty_setup,
            )
            os.close(slave_fd)
        else:
            proc = await asyncio.create_subprocess_exec(
                *built_command,
                stdin=subprocess.PIPE if stdin_pipe else None,
                stdout=subprocess.PIPE if stdout_pipe else None,
                stderr=subprocess.PIPE if stderr_pipe else None,
            )

        return proc, master_fd

    def close(self) -> None:
        """Tear down the sandbox.  Unmounts the overlay (if any), then
        removes temporary directories.  Safe to call multiple times."""
        if self.rootfs_overlay:
            if self.persist_overlayfs:
                warnings.warn(f"Overlay filesystem at {self.rootfs_dir} was not unmounted because persist_overlayfs was enabled. You will need to manually unmount it when you are done.")
            else:
                subprocess.run(
                    ["fusermount", "-u", str(self.rootfs_dir)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

        # Clean up temporary directories
        if hasattr(self, "tmp_dir") and self.tmp_dir is not None:
            self.tmp_dir.cleanup()
            self.tmp_dir = None
        if hasattr(self, "_temp_dir") and self._temp_dir is not None:
            self._temp_dir.cleanup()
            self._temp_dir = None

    def __enter__(self) -> "Sandbox":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
