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


def clean_expired_cache(
    database_path: str,
    now: int | None = None,
    compact: bool = True,
) -> int:
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
        if compact:
            connection.execute("VACUUM")
        return removed
    finally:
        connection.close()


def start_bot_process() -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-m", "src.bot"])


def start_web_process(port: str) -> subprocess.Popen:
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "src.web:app",
            "--host",
            "0.0.0.0",
            "--port",
            port,
            "--workers",
            "2",
            "--proxy-headers",
            "--forwarded-allow-ips=*",
        ]
    )


def rolling_restart_web(process: subprocess.Popen) -> bool:
    """Ask Uvicorn to replace its workers one at a time without dropping the port."""
    sighup = getattr(signal, "SIGHUP", None)
    if sighup is None or process.poll() is not None:
        return False
    process.send_signal(sighup)
    return True


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

    removed = clean_expired_cache(database_path)
    print(
        f"Maintenance startup: removed {removed} expired cache entr{'y' if removed == 1 else 'ies'}; "
        f"next restart in {restart_seconds} seconds.",
        flush=True,
    )
    bot_process = start_bot_process()
    web_process = start_web_process(port)
    restart_at = time.monotonic() + restart_seconds
    return_code = 0

    try:
        while not stopping:
            for process in (bot_process, web_process):
                child_return_code = process.poll()
                if child_return_code is not None:
                    return_code = child_return_code
                    stopping = True
                    break
            if stopping:
                break

            if time.monotonic() >= restart_at:
                print("Daily maintenance: rolling website workers and restarting bot.", flush=True)
                stop_processes([bot_process])
                removed = clean_expired_cache(database_path, compact=False)
                bot_process = start_bot_process()
                if not rolling_restart_web(web_process):
                    print("Website rolling restart is unavailable; leaving the healthy web process running.", flush=True)
                print(
                    f"Daily maintenance complete: removed {removed} expired cache "
                    f"entr{'y' if removed == 1 else 'ies'}.",
                    flush=True,
                )
                restart_at = time.monotonic() + restart_seconds

            time.sleep(1)
    finally:
        stop_processes([bot_process, web_process])

    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
