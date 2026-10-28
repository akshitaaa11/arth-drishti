"""Browser smoke test of the built dashboard (Playwright, run through Node). Skipped unless `web/dist` is built and Playwright is available.

Build and run: ``make web`` then ``pytest tests/test_dashboard_e2e.py``. It checks all eight screens at desktop and phone width (no console
errors, no horizontal overflow, footer, takeaways), the source drawer, tile navigation, the what-if sliders, the risk filter and dark mode.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parents[1]


def _node_path() -> str | None:
    node, npm = shutil.which("node"), shutil.which("npm")
    if not node or not npm:
        return None
    root = subprocess.run([npm, "root", "-g"], capture_output=True, text=True).stdout.strip()
    env = {**os.environ, "NODE_PATH": root}
    ok = subprocess.run([node, "-e", "require('playwright')"], env=env, capture_output=True).returncode == 0
    return root if ok else None


@pytest.mark.skipif(not (ROOT / "web" / "dist" / "index.html").exists(), reason="web/dist is not built (make web)")
def test_dashboard_smoke_in_a_real_browser(tmp_path: Path) -> None:
    node_path = _node_path()
    if node_path is None:
        pytest.skip("node with Playwright is not available")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "bsp.api.app:app", "--port", str(port), "--log-level", "warning"], cwd=ROOT,
                              env={**os.environ, "REDIS_URL": "", "GROQ_API_KEY": ""}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                if requests.get(f"http://127.0.0.1:{port}/health", timeout=1).status_code == 200:
                    break
            except requests.RequestException:
                time.sleep(1)
        result = subprocess.run(["node", str(ROOT / "web" / "e2e" / "smoke.cjs"), f"http://127.0.0.1:{port}"], env={**os.environ, "NODE_PATH": node_path},
                                capture_output=True, text=True, timeout=300)
        assert result.returncode == 0 and result.stdout.strip() == "OK", result.stdout + result.stderr
    finally:
        server.terminate()
        server.wait(timeout=10)
