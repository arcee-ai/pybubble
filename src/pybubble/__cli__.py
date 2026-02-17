#!/usr/bin/env python3
"""CLI interface for pybubble - run code in sandboxes or generate rootfs files from dockerfiles."""

import argparse
import asyncio
import os
import shutil
import sys
import termios
from pathlib import Path

from pybubble.rootfs import generate_rootfs
from pybubble.sandbox import Sandbox


def cmd_run(args):
    """Run a command in a sandbox."""
    async def _run():
        sandbox = Sandbox(
            work_dir=args.work_dir,
            rootfs=args.rootfs,
            rootfs_path=args.rootfs_path,
            user=args.user,
            mutable_rootfs=args.mutable_rootfs,
        )
        
        # Join the command parts back together
        if not args.cmd:
            print("Error: No command provided", file=sys.stderr)
            return 1
        cmd_str = " ".join(args.cmd)
        
        # Save terminal state so we can restore it after the child exits,
        # even if the sandboxed process (e.g. bash) changed raw mode / echo.
        tty_fd = sys.stdin.fileno() if sys.stdin.isatty() else None
        saved_attrs = termios.tcgetattr(tty_fd) if tty_fd is not None else None

        try:
            process = await sandbox.run(
                cmd_str,
                allow_network=not args.no_network,
                timeout=args.timeout,
                stdin_pipe=False,
                stdout_pipe=False,
                stderr_pipe=False,
            )

            returncode = await process.wait(timeout=args.timeout)

            if returncode != 0:
                return returncode

            return 0
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
        "--no-network",
        action="store_true",
        help="Allow network access"
    )
    run_parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Command timeout in seconds (default: no timeout)"
    )
    run_parser.add_argument(
        "--user",
        default="sandbox",
        help="User to run the sandbox as (default: sandbox)"
    )
    run_parser.add_argument(
        "--mutable-rootfs",
        action="store_true",
        help="Allow the rootfs to be modified (requires --rootfs-path)"
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
        default=6,
        help="Compression level for the generated rootfs tarball (default: 6)"
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
