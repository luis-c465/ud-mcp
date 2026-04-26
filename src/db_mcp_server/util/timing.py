"""Timing helpers for lightweight duration tracking."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from time import perf_counter
from typing import Iterator


@dataclass(slots=True)
class TimingResult:
    """Container for timing measurements in milliseconds."""

    started_at: float
    ended_at: float | None = None

    @property
    def elapsed_ms(self) -> float:
        """Return the measured duration in milliseconds."""

        end = self.ended_at if self.ended_at is not None else perf_counter()
        return (end - self.started_at) * 1000.0

    def stop(self) -> float:
        """Mark the timing window as complete and return elapsed milliseconds."""

        if self.ended_at is None:
            self.ended_at = perf_counter()
        return self.elapsed_ms


@contextmanager
def timing() -> Iterator[TimingResult]:
    """Measure elapsed time for a code block.

    Example
    -------
    >>> with timing() as timer:
    ...     do_work()
    >>> timer.elapsed_ms
    12.3
    """

    timer = TimingResult(started_at=perf_counter())
    try:
        yield timer
    finally:
        timer.stop()


def elapsed_ms(start: float, end: float | None = None) -> float:
    """Return the elapsed milliseconds between ``start`` and ``end``."""

    stop = perf_counter() if end is None else end
    return (stop - start) * 1000.0
