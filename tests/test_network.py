import asyncio
import subprocess
from pybubble import Sandbox
import pytest

@pytest.mark.asyncio
async def test_internal_network(default_rootfs):
    with Sandbox(rootfs=str(default_rootfs)) as sandbox:
        process = await sandbox.run(
            "nc -l -p 8080",
        )
        try:
            response = await sandbox.run(
                "echo 'Hello, world!' | nc -w 2 localhost 8080",
            )
            _, stderr = await response.communicate()
            assert response.returncode == 0, f"Command failed with exit code {response.returncode}: {stderr}"
        finally:
            if process.returncode is None:
                process.terminate()
            await process.wait(timeout=5)

@pytest.mark.asyncio
async def test_internet(default_rootfs):
    with Sandbox(rootfs=str(default_rootfs), enable_outbound=True) as sandbox:
        process = await sandbox.run("curl http://example.com/")
        await process.wait(check=True)
        assert process.returncode == 0

@pytest.mark.asyncio
async def test_forward_port(default_rootfs):
    with Sandbox(rootfs=str(default_rootfs), enable_outbound=True) as sandbox:
        sandbox.forward_port(8080, 22222)
        server = await sandbox.run(
            "nc -l -p 8080",
        )
        try:
            response = subprocess.run(
                ["bash", "-c", "echo 'Hello, world!' | nc -w 2 localhost 22222"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            assert response.returncode == 0
        finally:
            if server.returncode is None:
                server.terminate()
            try:
                await server.wait(timeout=5)
            except TimeoutError:
                server.kill()
                await server.wait(timeout=5)

@pytest.mark.asyncio
async def test_forward_port_multiple(default_rootfs):
    with Sandbox(rootfs=str(default_rootfs), enable_outbound=True) as sandbox:
        sandbox.forward_port(8080, 22222)
        sandbox.forward_port(8081, 22223)
        server1 = await sandbox.run(
            "nc -l -p 8080",
        )
        server2 = await sandbox.run(
            "nc -l -p 8081",
        )
        try:
            response1 = subprocess.run(
                ["bash", "-c", "echo 'Hello, world!' | nc -w 2 localhost 22222"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            assert response1.returncode == 0
            response2 = subprocess.run(
                ["bash", "-c", "echo 'Hello, world!' | nc -w 2 localhost 22223"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            assert response2.returncode == 0
        finally:
            for server in (server1, server2):
                if server.returncode is None:
                    server.terminate()
                try:
                    await server.wait(timeout=5)
                except TimeoutError:
                    server.kill()
                    await server.wait(timeout=5)


@pytest.mark.asyncio
async def test_access_host_loopback(default_rootfs):
    with Sandbox(
        rootfs=str(default_rootfs),
        enable_outbound=True,
        allow_host_loopback=True,
    ) as sandbox:
        server = subprocess.Popen(
            ["nc", "-l", "-p", "22222"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            response = await sandbox.run("echo 'Hello, world!' | nc -w 2 10.0.2.2 22222")
            await response.wait(check=True)
            assert response.returncode == 0
        finally:
            if server.poll() is None:
                server.kill()
            server.wait(timeout=5)
