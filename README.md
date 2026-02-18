# pybubble

A simple wrapper around [bubblewrap](https://github.com/containers/bubblewrap) to create sandboxed environments for executing code. It works without Docker or other daemon-based container runtimes, using shared read-only root filesystems for quick (1-2ms) setup times.

While these environments are sandboxed and provide protection from accidental modification of your host system by overzealous LLMs, **pybubble is not sufficient to protect you against actively malicious code**. In general, while containerization solutions like pybubble or Docker offer a reasonable degree of protection from accidental damage, when accepting input from the public you should consider using virtualization in place of or in addition to containers.

Feel free to submit bug reports and pull requests via GitHub, but note that Arcee is not committing to long-term support of this software. I wrote this library in my spare time to solve an irritating problem with building code execution environments, so expect a pace of updates consistent with "time I have while waiting for a debug run to finish".

Due to relying on Linux kernel features to operate, pybubble is not compatible with macOS or Windows.

## Setup

Install `bwrap`. On Ubuntu, do:

```bash
$ sudo apt-get install bubblewrap
```

Optionally, for overlay filesystem support (writable rootfs without modifying the original):

```bash
$ sudo apt-get install fuse-overlayfs
```

For outbound internet access (or port forwarding via `enable_outbound=True`), install `slirp4netns`:

```bash
$ sudo apt-get install slirp4netns
```

Basic internal networking (`enable_network=True`) does not require `slirp4netns`.

Then, add `pybubble` to your project.

```bash
$ uv add pybubble
```

## Root filesystem archives

Prebuilt wheels for pybubble come bundled with an x86 Alpine Linux root filesystem archive based on `default-rootfs.dockerfile`. It comes with:

- Python
- uv
- bash
- ripgrep
- cURL & wget
- numpy
- pandas
- httpx & requests
- pillow
- ImageMagick

If you need more tools or want to run a leaner environment, follow [this guide](docs/build-rootfs.md) to build one yourself.

## Run sandboxed code

```python
from pybubble import Sandbox
import asyncio

async def main():
    with Sandbox(enable_outbound=True) as sbox:
        process = await sbox.run("ping -c 1 google.com")
        stdout, stderr = await process.communicate()
        print(stdout.decode())

        process = await sbox.run_script("print('hello, world')", timeout=5.0)
        stdout, stderr = await process.communicate()
        print(stdout.decode())

if __name__ == "__main__":
    asyncio.run(main())
```

## PTY mode

For interactive programs, pass `use_pty=True` to get a real pseudoterminal. Ctrl+C, colors, job control, and curses apps all work.

```python
async def main():
    with Sandbox() as sbox:
        proc = await sbox.run("bash", use_pty=True)
        await proc.send(b"echo hello\n")

        async for chunk in proc.stream(decode=True):
            print(chunk, end="")

        await proc.wait()
        proc.close_pty()
```

## Overlay filesystem

With `fuse-overlayfs` installed, you can make the rootfs writable without modifying the cached original:

```python
with Sandbox(rootfs_overlay=True, enable_outbound=True) as sbox:
    proc = await sbox.run("apk add git")
    await proc.communicate()
```

## Networking

`Sandbox` networking is configured on construction:

- `enable_network=True` enables an isolated internal network namespace.
- `enable_outbound=True` adds outbound internet access via `slirp4netns`.
- `allow_host_loopback=True` allows access to host loopback services.

If you only need internal networking between sandboxed processes, leave outbound disabled and `slirp4netns` is not required.

Port forwarding is available via `forward_port(...)`:

```python
with Sandbox(enable_outbound=True) as sbox:
    sbox.forward_port(8080, 18080)  # sandbox:8080 -> host:18080
```

## Use the CLI

You can also run programs interactively via the CLI.

```bash
uv run pybubble run bash
sandbox:~$ echo "Hello, world!"
Hello, world!
```

With an overlay filesystem:

```bash
uv run pybubble run --rootfs-overlay bash
sandbox:~$ apk add nodejs
```

To learn more about the features available in `Sandbox`, see [this page](docs/sandbox.md).
