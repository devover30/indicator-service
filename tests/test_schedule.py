"""Cutoff (run_until) tests — pure time logic, no Redis."""

from datetime import datetime, timezone

from ta_engine.config import IST, Settings


def at(hour, minute, tz=IST):
    return datetime(2026, 6, 16, hour, minute, tzinfo=tz)


def test_before_cutoff_is_false():
    s = Settings()  # default 15:00
    assert s.past_cutoff(at(14, 59)) is False


def test_exactly_at_cutoff_is_true():
    s = Settings()
    assert s.past_cutoff(at(15, 0)) is True


def test_after_cutoff_is_true():
    s = Settings()
    assert s.past_cutoff(at(15, 1)) is True


def test_custom_cutoff_respected(monkeypatch):
    monkeypatch.setenv("TA_RUN_UNTIL", "09:30")
    s = Settings(run_until="09:30")
    assert s.past_cutoff(at(9, 29)) is False
    assert s.past_cutoff(at(9, 30)) is True


def test_non_ist_input_is_converted():
    # 09:35 UTC == 15:05 IST -> past a 15:00 cutoff
    s = Settings()
    assert s.past_cutoff(at(9, 35, tz=timezone.utc)) is True
