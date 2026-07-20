"""Run the website and Discord bot together on one Render service."""

from __future__ import annotations

import os
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path


DEFAULT_MAINTENANCE_RESTART_SECONDS = 24 * 60 * 60


def maintenance_restart_seconds() -> int:
    """Return the configured cycle length, using 24 hours by default."""
    raw_value = os.getenv(
        "MAINTENANCE_RESTART_SECONDS",
        str(DEFAULT_MAINTENANCE_RESTART_SECONDS),
    )
    try:
        return max(60, int(raw_value))
    except ValueError:
        return DEFAULT_MAINTENANCE_RESTART_SECONDS


def clean_expired_cache(database_path: str, now: int | None = None) -> int:
    """Remove disposable expired cache rows without touching application data."""
    path = Path(database_path)
    if not path.exists():
        return 0

    connection = sqlite3.connect(path, timeout=30)
    try:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'cache_entries'"
        ).fetchone()
        if table is None:
            return 0
        cursor = connection.execute(
            "DELETE FROM cache_entries WHERE expires_at <= ?",
            (int(time.time()) if now is None else now,),
        )
        removed = max(0, cursor.rowcount)
        connection.commit()
        connection.execute("VACUUM")
        return removed
    finally:
        connection.close()


def start_processes(port: str) -> list[subprocess.Popen]:
    return [
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


def stop_processes(processes: list[subprocess.Popen], timeout_seconds: float = 10) -> None:
    for process in processes:
        if process.poll() is None:
            process.terminate()

    deadline = time.monotonic() + timeout_seconds
    for process in processes:
        if process.poll() is None:
            try:
                process.wait(timeout=max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def main() -> int:
    port = os.getenv("PORT", "10000")
    database_path = os.getenv("DATABASE_PATH", "data/bot.sqlite3")
    restart_seconds = maintenance_restart_seconds()
    stopping = False

    def request_stop(_signum: int | None = None, _frame: object | None = None) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    while not stopping:
        removed = clean_expired_cache(database_path)
        print(
            f"Maintenance startup: removed {removed} expired cache entr{'y' if removed == 1 else 'ies'}; "
            f"next restart in {restart_seconds} seconds.",
            flush=True,
        )
        processes = start_processes(port)
        restart_at = time.monotonic() + restart_seconds
        unexpected_return_code: int | None = None

        while not stopping and time.monotonic() < restart_at:
            for process in processes:
                return_code = process.poll()
                if return_code is not None:
                    unexpected_return_code = return_code
                    break
            if unexpected_return_code is not None:
                break
            time.sleep(1)

        if not stopping and unexpected_return_code is None:
            print("Daily maintenance restart: stopping bot and website.", flush=True)
        stop_processes(processes)

        if unexpected_return_code is not None:
            return unexpected_return_code

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
