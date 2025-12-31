# pybubble

A simple wrapper around [bubblewrap](https://github.com/containers/bubblewrap) to create sandbox environments for executing code. It works without Docker or other daemon-based container runtimes, using shared read-only root filesystems for quick (1-2ms) setup times.

While these environments are sandboxed and provide protection from accidental modification of your host system by overzealous LLMs, **pybubble is not sufficient to protect you against actively malicious code**. In general, while containerization solutions like pybubble or Docker offer a reasonable degree of protection from accidental damage and unsophisticated attackers, when accepting input from the public you should consider using more robust security solutions in addition to tools like pybubble or Docker.

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

If all you need is basic Python code execution, consider using the provided root filesystem archive under our GitHub release. It comes preinstalled with:

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

## Run code

Create a sandbox by doing:

```python
from pybubble import Sandbox
import asyncio

async def main():
    s = Sandbox("path/to/rootfs.tgz")

    stdout, stderr = await s.run("ping -c 1 google.com", allow_network=True)

    print(stdout.decode("utf-8")) # ping output

    stdout, stderr = await s.run_python("print('hello, world')", timeout=5.0)

    print(stdout.decode("utf-8")) # "hello, world"

if __name__ == "__main__":
    asyncio.run(main())
```

To learn more about the features available in `Sandbox`, see [this page](docs/sandbox.md).
