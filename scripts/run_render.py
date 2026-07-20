"""Run the website and Discord bot together on one Render service."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time


def main() -> int:
    port = os.getenv("PORT", "10000")
    processes = [
        subprocess.Popen([sys.executable, "-m", "src.bot"]),
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "src.web:app",
                "--host",
                "0.0.0.0",
                "--port",
                port,
                "--proxy-headers",
                "--forwarded-allow-ips=*",
            ]
        ),
    ]

    stopping = False

    def stop_processes(_signum: int | None = None, _frame: object | None = None) -> None:
        nonlocal stopping
        if stopping:
            return
        stopping = True
        for process in processes:
            if process.poll() is None:
                process.terminate()

    signal.signal(signal.SIGTERM, stop_processes)
    signal.signal(signal.SIGINT, stop_processes)

    try:
        while not stopping:
            for process in processes:
                return_code = process.poll()
                if return_code is not None:
                    stop_processes()
                    return return_code
            time.sleep(1)
    finally:
        stop_processes()
        deadline = time.monotonic() + 10
        for process in processes:
            if process.poll() is None:
                try:
                    process.wait(timeout=max(0.1, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    process.kill()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
