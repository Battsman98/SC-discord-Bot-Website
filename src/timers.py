import time
from dataclasses import dataclass

import aiohttp


EXEC_TIMER_CFG_URL = "https://contestedzonetimers.com/lib/cfg.dat"
EXEC_TIMER_SOURCE_URL = "https://contestedzonetimers.com/"
EXEC_RED_PHASE_SECONDS = 2 * 60 * 60
EXEC_GREEN_PHASE_SECONDS = 1 * 60 * 60
EXEC_BLACK_PHASE_SECONDS = 5 * 60
EXEC_TOTAL_CYCLE_SECONDS = EXEC_RED_PHASE_SECONDS + EXEC_GREEN_PHASE_SECONDS + EXEC_BLACK_PHASE_SECONDS


@dataclass(frozen=True)
class ExecHangarStatus:
    status: str
    status_detail: str
    phase_remaining_seconds: int
    cycle_remaining_seconds: int
    next_change_unix: int
    lights: str
    source_url: str


async def fetch_exec_cycle_start_unix(timeout_seconds: int) -> int:
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(EXEC_TIMER_CFG_URL) as response:
            response.raise_for_status()
            text = await response.text()
            return int(text.strip())


def calculate_exec_hangar_status(cycle_start_unix: int, now_unix: int | None = None) -> ExecHangarStatus:
    now = now_unix if now_unix is not None else int(time.time())
    elapsed = max(0, now - cycle_start_unix)
    cycle_elapsed = elapsed % EXEC_TOTAL_CYCLE_SECONDS
    cycle_remaining = EXEC_TOTAL_CYCLE_SECONDS - cycle_elapsed

    if cycle_elapsed < EXEC_RED_PHASE_SECONDS:
        phase_elapsed = cycle_elapsed
        phase_remaining = EXEC_RED_PHASE_SECONDS - phase_elapsed
        lights = _exec_red_phase_lights(phase_elapsed)
        return ExecHangarStatus(
            status="Closed",
            status_detail="Charging",
            phase_remaining_seconds=phase_remaining,
            cycle_remaining_seconds=cycle_remaining,
            next_change_unix=now + phase_remaining,
            lights=lights,
            source_url=EXEC_TIMER_SOURCE_URL,
        )

    if cycle_elapsed < EXEC_RED_PHASE_SECONDS + EXEC_GREEN_PHASE_SECONDS:
        phase_elapsed = cycle_elapsed - EXEC_RED_PHASE_SECONDS
        phase_remaining = EXEC_GREEN_PHASE_SECONDS - phase_elapsed
        lights = _exec_green_phase_lights(phase_elapsed)
        return ExecHangarStatus(
            status="Open",
            status_detail="Active",
            phase_remaining_seconds=phase_remaining,
            cycle_remaining_seconds=cycle_remaining,
            next_change_unix=now + phase_remaining,
            lights=lights,
            source_url=EXEC_TIMER_SOURCE_URL,
        )

    phase_elapsed = cycle_elapsed - EXEC_RED_PHASE_SECONDS - EXEC_GREEN_PHASE_SECONDS
    phase_remaining = EXEC_BLACK_PHASE_SECONDS - phase_elapsed
    return ExecHangarStatus(
        status="Resetting",
        status_detail="Death zone",
        phase_remaining_seconds=phase_remaining,
        cycle_remaining_seconds=cycle_remaining,
        next_change_unix=now + phase_remaining,
        lights="BLACK BLACK BLACK BLACK BLACK",
        source_url=EXEC_TIMER_SOURCE_URL,
    )


def calculate_countdown_end_unix(duration_seconds: int, started_minutes_ago: int = 0) -> int:
    remaining = max(0, duration_seconds - started_minutes_ago * 60)
    return int(time.time()) + remaining


def _exec_red_phase_lights(phase_elapsed: int) -> str:
    lights = []
    for index in range(5):
        lights.append("GREEN" if phase_elapsed >= (index + 1) * 24 * 60 else "RED")
    return " ".join(lights)


def _exec_green_phase_lights(phase_elapsed: int) -> str:
    lights = []
    for index in range(5):
        lights.append("BLACK" if phase_elapsed >= (index + 1) * 12 * 60 else "GREEN")
    return " ".join(lights)
