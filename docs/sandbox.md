# Sandboxes

Sandbox objects are a reference to an unpacked root filesystem (stored, usually, in `~/.cache/pybubble/rootfs/{hash_of_rootfs_archive}/` and reused between environments) and a writable session directory, usually stored in a uniquely-named directory in `/tmp`.

Unless you pass `work_dir` to the constructor, the session directory will be automatically deleted as soon as the Sandbox goes out of scope or is deleted with the `del` keyword. The directory bound to `/tmp` will always be deleted when a sandbox goes out of scope.

Programs running in the sandbox see a read-only root filesystem and a writable partition at `/home/sandbox`, which is also the default working directory. The sandbox inherits the hostname of the host system, as well as a read-only copy of `/etc/resolv.conf` for DNS resolution when `allow_network=True` is passed to `run()` or `run_python()`. A separate writable directory is used under the host's `/tmp` for the sandbox's `/tmp`.

## API

`def __init__(self, rootfs: str | Path, work_dir: str | Path | None = None, rootfs_path: str | Path | None = None)`

Creates a sandbox from the specified `rootfs` tarball, expected to be in the form of a tarball or compressed tarball.

If `work_dir` is specified, the writable working directory for the sandbox will be stored at that location and will not be deleted when the sandbox goes out of scope. Otherwise, a temporary directory in `/tmp` will be used.

If `rootfs_path` is provided, the root filesystem tarball will be extracted to that directory. Otherwise, it will be extracted to `~/.cache/pybubble/rootfs/{hash}`. If a directory already exists at the path, extraction will be skipped and the cached filesystem will be reused.

---

`async def run(self, command: str, allow_network: bool = False, timeout: float = 10.0, stdin_pipe: bool = True, stdout_pipe: bool = True, stderr_pipe: bool = True) -> SandboxedProcess`

Runs a given shell command in a sandbox. The command is run asynchronously.

If `allow_network` is True, network access is granted to the process and the host's `/etc/resolv.conf` is mounted read-only to the sandbox for DNS resolution.

The argument `timeout` sets the default timeout (in seconds) used by `SandboxedProcess.wait()` and `SandboxedProcess.communicate()`, which raise `TimeoutError` if the process takes longer than that.

If `stdin_pipe` is True, stdin is piped so you can call `SandboxedProcess.send()` / `send_text()`. If False, stdin is inherited from the parent process.
If `stdout_pipe` or `stderr_pipe` are False, those streams are inherited from the parent process instead of being available for programmatic streaming.

Returns a `SandboxedProcess` that you can use to stream output and send stdin. Common patterns:

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

You can also send input:

```python
process = await sandbox.run("cat")
await process.send_text("hello\n")
process.close_stdin()
stdout, stderr = await process.communicate()
```

---

`async def run_python(self, code: str, allow_network: bool = False, timeout: float = 10.0) -> tuple[bytes, bytes]`

Convenience wrapper for running Python scripts. Creates a file called `script.py` and writes the value of `code` to it, and then runs `python script.py`. Returns `(stdout, stderr)` like the old `run()` behavior.

## Accessing the session data

The writable portion of the sandbox's filesystem can be accessed from the host with the Path object stored at `Sandbox.work_dir`. Changes made to this directory made by the host will be visible instantly in the sandbox, and vice versa. You can use this to access files created by the sandboxed code or place files in the session directory for the sandboxed code to access.
