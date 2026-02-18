#!/usr/bin/env python3
"""CLI interface for pybubble - run code in sandboxes or generate rootfs files from dockerfiles."""

import tarfile
import argparse
import asyncio
import fcntl
import os
import signal
import shutil
import sys
import termios
import tty
from pathlib import Path

from pybubble.process import SandboxedProcess
from pybubble.rootfs import generate_rootfs
from pybubble.sandbox import Sandbox


async def _proxy_pty(process: SandboxedProcess) -> int:
    """Bidirectional proxy between the real terminal and the sandbox PTY.

    Puts the host terminal in raw mode, shuttles bytes in both directions,
    and forwards window-resize events.  Returns the child exit code.
    """
    loop = asyncio.get_running_loop()
    master_fd = process.master_fd
    assert master_fd is not None

    stdin_fd = sys.stdin.fileno()
    stdout_fd = sys.stdout.fileno()

    os.set_blocking(master_fd, False)

    def _on_master_output() -> None:
        try:
            data = os.read(master_fd, 4096)
            if data:
                os.write(stdout_fd, data)
        except OSError:
            pass

    def _on_stdin_input() -> None:
        try:
            data = os.read(stdin_fd, 4096)
            if data:
                os.write(master_fd, data)
        except OSError:
            pass

    def _on_resize() -> None:
        try:
            size = fcntl.ioctl(stdin_fd, termios.TIOCGWINSZ, b"\x00" * 8)
            fcntl.ioctl(master_fd, termios.TIOCSWINSZ, size)
        except OSError:
            pass

    loop.add_reader(master_fd, _on_master_output)
    loop.add_reader(stdin_fd, _on_stdin_input)
    loop.add_signal_handler(signal.SIGWINCH, _on_resize)

    try:
        returncode = await process.wait(timeout=None)
        # Let the event loop flush any remaining PTY output.
        await asyncio.sleep(0.05)
    finally:
        loop.remove_reader(master_fd)
        loop.remove_reader(stdin_fd)
        loop.remove_signal_handler(signal.SIGWINCH)
        # Drain anything left in the PTY buffer after readers are removed.
        try:
            while True:
                leftover = os.read(master_fd, 4096)
                if not leftover:
                    break
                os.write(stdout_fd, leftover)
        except OSError:
            pass
        process.close_pty()

    return returncode


def cmd_run(args):
    """Run a command in a sandbox."""
    async def _run():
        if not args.cmd:
            print("Error: No command provided", file=sys.stderr)
            return 1
        cmd_str = " ".join(args.cmd)

        interactive = sys.stdin.isatty()
        tty_fd = sys.stdin.fileno() if interactive else None
        saved_attrs = termios.tcgetattr(tty_fd) if tty_fd is not None else None
        
        if args.persist_overlayfs and not args.rootfs_overlay:
            print("Error: --persist-overlayfs can only be used when --rootfs-overlay is enabled", file=sys.stderr)
            return 1

        forward_ports = {}
        if args.forward_port:
            try:
                for port_pair in args.forward_port.split(","):
                    sandbox_port, host_port = port_pair.split(":")
                    forward_ports[int(sandbox_port)] = int(host_port)
            except Exception as e:
                print(f"Error: {e}", file=sys.stderr)
                return 1

        with Sandbox(
            work_dir=args.work_dir,
            rootfs=args.rootfs,
            rootfs_path=args.rootfs_path,
            rootfs_overlay=args.rootfs_overlay,
            rootfs_overlay_path=args.rootfs_overlay_path,
            persist_overlayfs=args.persist_overlayfs,
            enable_outbound=not args.no_outbound,
            allow_host_loopback=args.allow_host_loopback,
        ) as sandbox:
            try:
                if args.share_net:
                    if sandbox.network is None:
                        print("Error: Network namespace not available - is slirp4netns installed?", file=sys.stderr)
                        return 1
                    print(f"Network namespace PID: {sandbox.network.namespace_watchdog.pid}")
                
                for sandbox_port, host_port in forward_ports.items():
                    sandbox.forward_port(sandbox_port, host_port)
                
                process = await sandbox.run(
                    cmd_str,
                    timeout=args.timeout,
                    use_pty=interactive,
                    ns_pid_override=args.net_share_pid,
                )

                if interactive:
                    tty.setraw(tty_fd)
                    returncode = await _proxy_pty(process)
                else:
                    returncode = await process.wait(timeout=args.timeout)
                
                return returncode
            except Exception as e:
                raise RuntimeError("An error occurred while running the command") from e
            finally:
                if saved_attrs is not None:
                    termios.tcsetattr(tty_fd, termios.TCSADRAIN, saved_attrs)

    return asyncio.run(_run())


def cmd_generate_rootfs(args):
    """Generate a rootfs file from a Dockerfile."""
    dockerfile = Path(args.dockerfile)
    output_file = Path(args.output)
    
    if not dockerfile.exists():
        print(f"Error: Dockerfile not found: {dockerfile}", file=sys.stderr)
        return 1
    
    try:
        generate_rootfs(dockerfile, output_file, compress_level=args.compress_level)
        print(f"Successfully generated rootfs: {output_file}")
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def clear_cache(args):
    """Clear the cache."""
    home = os.getenv("HOME") or str(Path.home())
    cache_dir = Path(home) / ".cache" / "pybubble"
    shutil.rmtree(cache_dir, ignore_errors=True)
    return 0


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Run code in sandboxes or generate rootfs files from dockerfiles",
        prog="pybubble"
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Run command subparser
    run_parser = subparsers.add_parser("run", help="Run a shell command in a sandbox")
    run_parser.add_argument(
        "cmd",
        nargs=argparse.REMAINDER,
        help="Shell command to run (use -- before command if it starts with -)"
    )
    run_parser.add_argument(
        "--rootfs",
        default=None,
        help="Path to rootfs tarball (default: bundled rootfs)"
    )
    run_parser.add_argument(
        "--work-dir",
        default="work",
        help="Working directory for sandbox sessions (default: work)"
    )
    run_parser.add_argument(
        "--rootfs-path",
        help="Path to extract/cache rootfs (default: auto-generated cache path)"
    )
    run_parser.add_argument(
        "--no-outbound",
        action="store_true",
        help="Disallow access to host network (including forwarded ports)"
    )
    run_parser.add_argument(
        "--share-net",
        action="store_true",
        help="Print a network namespace PID to use in another process with --net-share-pid"
    )
    run_parser.add_argument(
        "--net-share-pid",
        type=int,
        default=None,
        help="Network namespace PID to share with another process"
    )
    run_parser.add_argument(
        "--forward-port",
        type=str,
        default=None,
        help="Forward a port on the sandbox to the host. Format: \"<sandbox_port>:<host_port>,<sandbox_port>:<host_port>,...\""
    )
    run_parser.add_argument(
        "--allow-host-loopback",
        action="store_true",
        help="Allow the sandbox to access running servers on the host"
    )
    run_parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Command timeout in seconds (default: no timeout)"
    )
    run_parser.add_argument(
        "--rootfs-overlay",
        action="store_true",
        help="Allow the rootfs to be modified via overlayfs"
    )
    run_parser.add_argument(
        "--rootfs-overlay-path",
        help="Path in which to store the overlay filesystem and its mount point"
    )
    run_parser.add_argument(
        "--persist-overlayfs",
        action="store_true",
        help="When the process exits, do not unmount the overlayfs. You will need to manually unmount it when you are done."
    )
    run_parser.set_defaults(func=cmd_run)
    
    # Generate rootfs subparser
    rootfs_parser = subparsers.add_parser(
        "rootfs",
        help="Generate a rootfs file from a Dockerfile"
    )
    rootfs_parser.add_argument(
        "dockerfile",
        help="Path to Dockerfile"
    )
    rootfs_parser.add_argument(
        "output",
        help="Output path for the generated rootfs tarball"
    )
    rootfs_parser.add_argument(
        "--compress-level",
        type=int,
        default=19,
        help="Zstd compression level for the generated rootfs tarball (default: 19)"
    )
    rootfs_parser.set_defaults(func=cmd_generate_rootfs)
    
    cache_clear_parser = subparsers.add_parser(
        "clear-cache",
        help="Clear the cache"
    )
    cache_clear_parser.set_defaults(func=clear_cache)
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
