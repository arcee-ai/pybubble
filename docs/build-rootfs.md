# Building a custom root filesystem archive

## From an existing image

When using an overlay filesystem via `pybubble run`, you can use `--persist-overlayfs` to keep the overlay mounted after the process exits. This lets you create new rootfs archives without Docker. For example:

```bash
$ uv run pybubble run --rootfs-overlay --rootfs-overlay-path ./overlayfs --persist-overlayfs bash
sandbox:~$ apk add nodejs
OK: 297 MiB in 131 packages
sandbox:~$ exit
$ tar -czvf with_node.tgz -C overlayfs/mount .
$ fusermount -u overlayfs/mount
$ uv run pybubble run --rootfs with_node.tgz bash
sandbox:~$ node --version
v22.22.0
```

## With Docker

A custom root filesystem archive can be generated from any Dockerfile. Ensure your image contains a user named "sandbox" with an empty home directory at `/home/sandbox`. Your ephemeral writable session storage will be mounted at this location.

To generate a root filesystem, ensure you have Docker installed and running, then run:

```bash
$ pybubble rootfs your.dockerfile rootfs.tgz
```

Your root filesystem archive can now be used with sandboxes. Docker does not need to be installed to use this file, only to generate it.
