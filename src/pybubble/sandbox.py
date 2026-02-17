import asyncio
from pathlib import Path
import subprocess
import tempfile
import uuid
import warnings

from pybubble.process import SandboxedProcess
from pybubble.rootfs import setup_rootfs

# Path to the bundled default rootfs tarball (ships inside the wheel)
_BUNDLED_ROOTFS = Path(__file__).parent / "data" / "default.tgz"

def is_system_compatible() -> bool:
    """Checks if the system is Linux-based and has bubblewrap installed."""
    try:
        result = subprocess.run(
            ["bwrap", "--help"],
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


class Sandbox:
    def __init__(
        self,
        rootfs: str | Path | None = None,
        work_dir: str | Path | None = None,
        rootfs_path: str | Path | None = None,
        user: str = "sandbox",
        mutable_rootfs: bool = False
    ):
        """Creates a sandbox from the specified rootfs tarball, expected to be in the form of a tarball or compressed tarball.
        
        Args:
            rootfs: Path to rootfs tarball.  When *None* (the default), the
                bundled rootfs is used.
            work_dir: Path to writable working directory for sandbox sessions. If None, uses a unique directory in `/tmp` (default: None)
            rootfs_path: Path to extract rootfs to. If None, uses unique dir in `~/.cache/pybubble/rootfs` (default: None)
            user: User to run the sandbox as (default: "sandbox")
            mutable_rootfs: Whether to allow the extracted rootfs to be modified. If enabled, rootfs_path must be provided (default: False)
        """
        
        if not is_system_compatible():
            raise RuntimeError("Bubblewrap is not installed. Please ensure it is installed and in your PATH.")
        
        # Fall back to the bundled rootfs when none is provided
        if rootfs is None:
            if not _BUNDLED_ROOTFS.exists():
                raise FileNotFoundError(
                    "No rootfs tarball supplied and the bundled default.tgz "
                    "was not found.  If you are running from a source checkout, "
                    "build the rootfs first (see README)."
                )
            rootfs = _BUNDLED_ROOTFS
        
        if mutable_rootfs:
            if rootfs_path is None:
                raise ValueError("rootfs_path must be provided when mutable_rootfs is enabled")

            warnings.warn("Running sandbox with mutable root filesystem. Using other sandboxes with the same rootfs directory may cause instability.")
        
        if work_dir is None:
            self._temp_dir = tempfile.TemporaryDirectory(dir="/tmp")
            self.work_dir = Path(self._temp_dir.name)
            self.persist_session = False
        else:
            self._temp_dir = None
            self.work_dir = Path(work_dir)
            self.persist_session = True
        
        # Ensure work_dir exists
        Path.mkdir(self.work_dir, parents=True, exist_ok=True)
        
        # Temp directory to mount at /tmp
        self.tmp_dir = tempfile.TemporaryDirectory(dir="/tmp")
        
        # Convert rootfs_path to Path if provided, otherwise None (which triggers caching)
        rootfs_path_obj = Path(rootfs_path) if rootfs_path is not None else None
        
        self.rootfs_dir = setup_rootfs(str(rootfs), rootfs_path_obj)
        
        self.user = user
        self.mutable_rootfs = mutable_rootfs

    async def run(
        self,
        command: str,
        allow_network: bool = False,
        timeout: float | None = 10.0,
        stdin_pipe: bool = True,
        stdout_pipe: bool = True,
        stderr_pipe: bool = True,
    ) -> SandboxedProcess:
        """Runs a shell command in the sandbox. Returns a SandboxedProcess.
        
        Args:
            command: Shell command to run
            allow_network: Whether to allow network access
            timeout: Default timeout in seconds for process waits/communication
            stdin_pipe: Whether to pipe stdin for programmatic input
            stdout_pipe: Whether to pipe stdout for programmatic streaming
            stderr_pipe: Whether to pipe stderr for programmatic streaming
        """
        process = await self._start_process(command, allow_network, stdin_pipe, stdout_pipe, stderr_pipe)
        return SandboxedProcess(process, default_timeout=timeout)

    async def run_script(self, code: str, allow_network: bool = False, timeout: float | None = 10.0, run_command: str = "python", extension: str = "py") -> tuple[bytes, bytes]:
        """Writes a script to a temporary file and runs it in the sandbox. Returns a SandboxedProcess representing the running script process. Defaults to Python, but other commands can be specified.
        
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
        
        return await self._start_process(
            f"{run_command} /tmp/{script_name}",
            allow_network,
            stdin_pipe=False,
            stdout_pipe=True,
            stderr_pipe=True,
        )

    async def _start_process(
        self,
        command: str,
        allow_network: bool,
        stdin_pipe: bool,
        stdout_pipe: bool,
        stderr_pipe: bool
    ) -> asyncio.subprocess.Process:
        home_dir = f"/home/{self.user}" if self.user != "root" else "/root"
        built_command: list[str] = [
            "bwrap",
            "--unshare-all",
            "--die-with-parent",
            # Make sure we're using the sandboxed user.
            "--unshare-user",
            "--uid", "1000",
            # Bind root fs and work dir
            "--ro-bind" if not self.mutable_rootfs else "--bind", str(self.rootfs_dir.absolute()), "/",
            "--bind", str(self.work_dir.absolute()), home_dir,
            # Bind new /dev/ and /proc/ dirs - must happen after rootfs mount
            "--dev", "/dev",
            "--proc", "/proc",
            # Mount the temp dir at /tmp. We can't use --tmpfs because it doesn't persist between invocations of bwrap.
            "--bind", str(self.tmp_dir.name), "/tmp",
            # Set home directory and path
            "--setenv", "HOME", home_dir,
            "--setenv", "PATH", "/usr/bin:/bin:/usr/local/bin:/sbin/",
            "--chdir", home_dir,
            # Use --new-session to protect against certain attacks.
            "--new-session",
        ]
        
        if allow_network:
            # Bind system DNS config and allow network access
            built_command.extend(["--ro-bind", "/etc/resolv.conf", "/etc/resolv.conf", "--share-net"])
        
        built_command.extend(
            ["bash", "-c", command]
        )
        
        return await asyncio.create_subprocess_exec(
            *built_command,
            stdin=subprocess.PIPE if stdin_pipe else None,
            stdout=subprocess.PIPE if stdout_pipe else None,
            stderr=subprocess.PIPE if stderr_pipe else None,
        )

    def __del__(self):
        """Cleanup the sandbox work directory if it's temporary."""
        # Cleanup temporary directory if it was created and persistence is disabled
        if hasattr(self, "_temp_dir") and self._temp_dir is not None and not self.persist_session:
            self._temp_dir.cleanup()
