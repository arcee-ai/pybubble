#!/usr/bin/env python3
"""CLI interface for pybubble - run code in sandboxes or generate rootfs files from dockerfiles."""

import argparse
import asyncio
import os
import shutil
import sys
from pathlib import Path

from pybubble.rootfs import generate_rootfs
from pybubble.sandbox import Sandbox


def cmd_run(args):
    """Run a command in a sandbox."""
    async def _run():
        sandbox = Sandbox(
            work_dir=args.work_dir,
            rootfs=args.rootfs,
            rootfs_path=args.rootfs_path
        )
        
        # Join the command parts back together
        if not args.cmd:
            print("Error: No command provided", file=sys.stderr)
            return 1
        cmd_str = " ".join(args.cmd)
        
        try:
            process = await sandbox.run(
                cmd_str,
                allow_network=args.network,
                timeout=args.timeout,
                stdin_pipe=False,
                stdout_pipe=False,
                stderr_pipe=False,
            )

            returncode = await process.wait(timeout=args.timeout)
            if returncode != 0:
                print(f"Error: Command failed with exit code {returncode}", file=sys.stderr)
                return 1

            return 0
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
    
    return asyncio.run(_run())


def cmd_run_python(args):
    """Run Python code in a sandbox."""
    async def _run():
        sandbox = Sandbox(
            work_dir=args.work_dir,
            rootfs=args.rootfs,
            rootfs_path=args.rootfs_path
        )
        
        try:
            # Read code from file or use provided code string
            if args.file:
                code = Path(args.file).read_text()
            elif args.code:
                code = args.code
            else:
                # Read from stdin
                code = sys.stdin.read()
            
            stdout, stderr = await sandbox.run_python(
                code,
                allow_network=args.network,
                timeout=args.timeout
            )
            
            if stdout:
                sys.stdout.buffer.write(stdout)
            if stderr:
                sys.stderr.buffer.write(stderr)
            
            return 0
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
    
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
        "rootfs",
        help="Path to rootfs tarball"
    )
    run_parser.add_argument(
        "cmd",
        nargs=argparse.REMAINDER,
        help="Shell command to run (use -- before command if it starts with -)"
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
        "--network",
        action="store_true",
        help="Allow network access"
    )
    run_parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Command timeout in seconds (default: no timeout)"
    )
    run_parser.set_defaults(func=cmd_run)
    
    # Run Python subparser
    python_parser = subparsers.add_parser("python", help="Run Python code in a sandbox")
    python_parser.add_argument(
        "rootfs",
        help="Path to rootfs tarball"
    )
    python_parser.add_argument(
        "--code",
        help="Python code to run (or use --file or stdin)"
    )
    python_parser.add_argument(
        "--file",
        help="Path to Python file to run"
    )
    python_parser.add_argument(
        "--work-dir",
        default="work",
        help="Working directory for sandbox sessions (default: work)"
    )
    python_parser.add_argument(
        "--rootfs-path",
        help="Path to extract/cache rootfs (default: auto-generated cache path)"
    )
    python_parser.add_argument(
        "--network",
        action="store_true",
        help="Allow network access"
    )
    python_parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Command timeout in seconds (default: 10.0)"
    )
    python_parser.set_defaults(func=cmd_run_python)
    
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
