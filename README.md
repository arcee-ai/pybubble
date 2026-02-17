# pybubble

A simple wrapper around [bubblewrap](https://github.com/containers/bubblewrap) to create sandboxed environments for executing code. It works without Docker or other daemon-based container runtimes, using shared read-only root filesystems for quick (1-2ms) setup times.

While these environments are sandboxed and provide protection from accidental modification of your host system by overzealous LLMs, **pybubble is not sufficient to protect you against actively malicious code**. In general, while containerization solutions like pybubble or Docker offer a reasonable degree of protection from accidental damage, when accepting input from the public you should consider using virtualization in place of or in addition to containers.

Feel free to submit bug reports and pull requests via GitHub, but note that Arcee is not committing to long-term support of this software. I wrote this library in my spare time to solve an irritating problem with building code execution environments, so expect a pace of updates consistent with "time I have while waiting for a debug run to finish".

Due to relying on Linux kernel features to operate, pybubble is not compatible with macOS or Windows.

## Setup

Install `bwrap`. On Ubuntu, do:

```bash
sudo apt-get install bubblewrap
```

Then, add `pybubble` to your project.

```bash
uv add pybubble
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
    sbox = Sandbox()

    process = await sbox.run("ping -c 1 google.com", allow_network=True)
    stdout, stderr = await process.communicate()

    print(stdout.decode("utf-8")) # ping output

    process = await sbox.run_script("print('hello, world')", timeout=5.0)
    stdout, stderr = await process.communicate()

    print(stdout.decode("utf-8")) # "hello, world"

if __name__ == "__main__":
    asyncio.run(main())
```

To learn more about the features available in `Sandbox`, see [this page](docs/sandbox.md).
