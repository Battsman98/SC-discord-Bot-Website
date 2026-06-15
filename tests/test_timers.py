from src.timers import (
    EXEC_BLACK_PHASE_SECONDS,
    EXEC_GREEN_PHASE_SECONDS,
    EXEC_RED_PHASE_SECONDS,
    calculate_countdown_end_unix,
    calculate_cycle_start_from_phase,
    calculate_exec_hangar_status,
)


def test_exec_hangar_closed_phase() -> None:
    status = calculate_exec_hangar_status(1_000, 1_000 + 10)

    assert status.status == "Closed"
    assert status.status_detail == "Charging"
    assert status.phase_remaining_seconds == EXEC_RED_PHASE_SECONDS - 10
    assert status.lights.startswith("RED")


def test_exec_hangar_open_phase() -> None:
    status = calculate_exec_hangar_status(1_000, 1_000 + EXEC_RED_PHASE_SECONDS + 10)

    assert status.status == "Open"
    assert status.status_detail == "Active"
    assert status.phase_remaining_seconds == EXEC_GREEN_PHASE_SECONDS - 10
    assert "GREEN" in status.lights


def test_exec_hangar_resetting_phase() -> None:
    now = 1_000 + EXEC_RED_PHASE_SECONDS + EXEC_GREEN_PHASE_SECONDS + 10
    status = calculate_exec_hangar_status(1_000, now)

    assert status.status == "Resetting"
    assert status.status_detail == "Death zone"
    assert status.phase_remaining_seconds == EXEC_BLACK_PHASE_SECONDS - 10
    assert status.lights == "BLACK BLACK BLACK BLACK BLACK"


def test_countdown_end_accounts_for_elapsed_minutes(monkeypatch) -> None:
    monkeypatch.setattr("src.timers.time.time", lambda: 1_000)

    assert calculate_countdown_end_unix(15 * 60, started_minutes_ago=5) == 1_600


def test_calculate_cycle_start_from_open_phase() -> None:
    cycle_start = calculate_cycle_start_from_phase("open", remaining_minutes=30, now_unix=10_000)

    status = calculate_exec_hangar_status(cycle_start, 10_000)

    assert status.status == "Open"
    assert status.phase_remaining_seconds == 30 * 60
