# Sandboxes

Sandbox objects manage an unpacked root filesystem (stored, usually, in `~/.cache/pybubble/rootfs/{hash_of_rootfs_archive}/` and reused between environments) and a writable session directory, usually stored in a uniquely-named directory in `/tmp`.

Unless you pass `work_dir` to the constructor, the session directory will be automatically deleted when the Sandbox is closed or goes out of scope. The directory bound to `/tmp` will always be deleted when a sandbox is closed.

Programs running in the sandbox see a read-only root filesystem (unless an overlay is enabled) and a writable partition at `/home/sandbox`, which is also the default working directory. When `allow_network=True` is passed to `run()` or `run_script()`, a read-only copy of `/etc/resolv.conf` is mounted for DNS resolution. A separate writable directory is used under the host's `/tmp` for the sandbox's `/tmp`.

The sandbox runs with its own hostname (`sandbox`), its own PID namespace, and an isolated user namespace.

## Context manager

`Sandbox` implements the context manager protocol.  This is the recommended way to use it, especially when overlay filesystems are enabled, since `close()` must run to unmount the FUSE overlay.

```python
async with Sandbox() as sbox:
    proc = await sbox.run("echo hello")
    stdout, stderr = await proc.communicate()
# overlay unmounted, temp dirs cleaned up
```

You can also call `close()` manually:

```python
sbox = Sandbox()
# ... use the sandbox ...
sbox.close()
```

## Constructor

```python
def __init__(
    self,
    rootfs: str | Path | None = None,
    work_dir: str | Path | None = None,
    rootfs_path: str | Path | None = None,
    rootfs_overlay: bool = False,
    rootfs_overlay_path: str | Path | None = None,
    persist_overlayfs: bool = False,
)
```

Creates a sandbox from the specified `rootfs` tarball, expected to be in the form of a tarball or compressed tarball.

| Parameter | Description |
|---|---|
| `rootfs` | Path to a rootfs tarball. When `None` (the default), the bundled `default.tgz` that ships with the wheel is used. |
| `work_dir` | Writable working directory for sandbox sessions, mounted at `/home/sandbox`. If `None`, a temporary directory in `/tmp` is used and deleted on close. |
| `rootfs_path` | Directory to extract the rootfs tarball into. If `None`, a hash-based cache under `~/.cache/pybubble/rootfs/` is used, so identical tarballs share one extraction. |
| `rootfs_overlay` | When `True`, mount a `fuse-overlayfs` layer on top of the read-only rootfs so the sandbox can write to `/usr`, `/etc`, etc. Requires `fuse-overlayfs` to be installed. |
| `rootfs_overlay_path` | Directory for the overlay `upper/`, `work/`, and `mount/` subdirectories. If `None`, a temporary directory in `/tmp` is used. |
| `persist_overlayfs` | When `True`, the overlay is **not** unmounted on close — useful for exporting the modified filesystem. Requires `rootfs_overlay_path` to be set. |

## `run()`

```python
async def run(
    self,
    command: str,
    allow_network: bool = False,
    timeout: float | None = 10.0,
    stdin_pipe: bool = True,
    stdout_pipe: bool = True,
    stderr_pipe: bool = True,
    use_pty: bool = False,
) -> SandboxedProcess
```

Runs a shell command in the sandbox asynchronously and returns a `SandboxedProcess`.

| Parameter | Description |
|---|---|
| `command` | Shell command to run (passed to `bash -c`). |
| `allow_network` | Grant network access and mount the host's `/etc/resolv.conf` for DNS. |
| `timeout` | Default timeout (in seconds) used by `SandboxedProcess.wait()` and `communicate()`. `None` means no timeout. |
| `stdin_pipe` | Pipe stdin for programmatic input via `send()` / `send_text()`. Ignored when `use_pty` is `True`. |
| `stdout_pipe` / `stderr_pipe` | Pipe stdout/stderr for programmatic streaming. Ignored when `use_pty` is `True`. |
| `use_pty` | Allocate a pseudoterminal for the child process. The returned `SandboxedProcess` exposes the master fd via `master_fd` and supports `set_terminal_size()`. Ctrl+C, colors, curses apps, and job control all work in PTY mode. |

### Pipe mode (default)

Standard mode for programmatic use. stdout and stderr are separate streams.

```python
process = await sandbox.run("echo hello")
stdout, stderr = await process.communicate()
```

```python
process = await sandbox.run("bash -c 'echo out; echo err 1>&2'")
async for stream_name, chunk in process.stream(include_stream=True):
    print(stream_name, chunk)
await process.wait(check=True)
```

For line-oriented streaming:

```python
process = await sandbox.run("bash -c 'printf \"line1\\nline2\\n\"'")
async for line in process.stream_lines():
    print(line, end="")
await process.wait(check=True)
```

Sending input:

```python
process = await sandbox.run("cat")
await process.send_text("hello\n")
process.close_stdin()
stdout, stderr = await process.communicate()
```

### PTY mode

The child gets a real pseudoterminal, so interactive programs (bash, python REPL, vim, etc.) work correctly. stdout and stderr are merged into a single stream; `stream()` and `stream_lines()` work transparently and label everything as `"stdout"`.

```python
process = await sandbox.run("bash", use_pty=True)

await process.send(b"echo hello\n")

async for chunk in process.stream(decode=True):
    print(chunk, end="")

process.set_terminal_size(40, 120)

await process.wait()
process.close_pty()
```

PTY mode also works without a host terminal attached (e.g., in a web server or CI), and can be paired with a virtual terminal emulator like [pyte](https://github.com/selectel/pyte) for headless terminal rendering.

---

## `run_script()`

```python
async def run_script(
    self,
    code: str,
    allow_network: bool = False,
    timeout: float | None = 10.0,
    run_command: str = "python",
    extension: str = "py",
) -> SandboxedProcess
```

Writes `code` to a temporary file and runs it with `run_command`. Defaults to Python.

```python
stdout, stderr = await (await sandbox.run_script("print('hi')")).communicate()
```

## Accessing session data

The writable portion of the sandbox's filesystem can be accessed from the host via the `Path` at `Sandbox.work_dir`. Changes made by the host are visible instantly inside the sandbox, and vice versa.

```python
# Write a file from the host
(sandbox.work_dir / "input.txt").write_text("data")

# Read it from inside the sandbox
proc = await sandbox.run("cat input.txt")
stdout, _ = await proc.communicate()
```
