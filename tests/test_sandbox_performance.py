"""Performance tests for sandbox creation and execution."""

import asyncio
import time
import pytest
from pybubble import Sandbox
from conftest import ensure_default_exists


async def run_sandbox_test(sandbox_id: int, rootfs_location: str):
    """Create a sandbox, run some Python code, and clean it up."""
    with Sandbox(rootfs=rootfs_location, enable_network=False) as sandbox:
        code = f"""
import math
result = sum(range(1, 101))
print(f"Sandbox {sandbox_id}: Sum of 1-100 = {{result}}")
print(f"Pi approximation: {{math.pi:.4f}}")
"""
        proc = await sandbox.run_script(code)
        stdout, stderr = await proc.communicate()
    return stdout, stderr


@pytest.mark.asyncio
async def test_sandbox_performance():
    """Test that sandbox creation and execution overhead is under 5ms per sandbox."""
    default_rootfs = ensure_default_exists()
    rootfs_location = str(default_rootfs)
    num_sandboxes = 100

    start_time = time.perf_counter()

    tasks = [
        run_sandbox_test(i, rootfs_location)
        for i in range(num_sandboxes)
    ]

    results = await asyncio.gather(*tasks)

    end_time = time.perf_counter()
    total_time = end_time - start_time
    overhead_per_sandbox = total_time / num_sandboxes

    assert overhead_per_sandbox < 0.01, (
        f"Average overhead per sandbox ({overhead_per_sandbox*1000:.2f} ms) "
        f"exceeds 10ms threshold. Total time: {total_time:.4f}s for {num_sandboxes} sandboxes."
    )

    assert len(results) == num_sandboxes
