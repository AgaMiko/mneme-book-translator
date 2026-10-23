"""Compare a run's real cost with its estimate as it goes, and pause it when over.

Each run (glossary, speakers, voices, translation) counts what its calls
actually cost (``app.generation.usage``). After every unit of work (a
window, a fragment) it compares that with what the estimate predicted for
the work done so far. More than ``COST_PAUSE_THRESHOLD`` over (10% by
default), after at least ``COST_PAUSE_MIN_UNITS`` units, the run stops the
way Stop does: finished work is kept and Continue resumes it.

Continue keeps checking, against the estimate for the remaining work only.
"Continue without limit" turns the check off for that run.

The state shown in the app (spent so far, estimate, pause reason) lives in
``Book.cost_guard`` under the step's name.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from app.generation.usage import Spend

if TYPE_CHECKING:
    from collections.abc import Callable

    from app.core.config import Settings
    from app.models.book import Book

GuardStep = Literal["glossary", "speakers", "voices", "translation"]


@dataclass(slots=True)
class CostGuard:
    """One run's meter. ``expected(k)`` is the estimated cost of units 1..k."""

    step: GuardStep
    expected: Callable[[int], float]
    units_total: int
    start_units: int
    spent_before: float
    limit: bool
    threshold: float
    min_units: int
    unit_label: str = "window"
    spend: Spend = field(default_factory=Spend)
    units_done: int = 0
    # Set once the run pauses; parallel work finishing afterwards keeps it.
    paused_reason: str | None = None

    def __post_init__(self) -> None:
        self.units_done = self.start_units

    @property
    def estimate_usd(self) -> float:
        return self.expected(self.units_total)

    def overrun(self) -> str | None:
        """Why the run should pause now, or None. Call after each finished unit."""
        done = self.units_done - self.start_units
        if not self.limit or done < self.min_units:
            return None
        expected = self.expected(self.units_done) - self.expected(self.start_units)
        if expected <= 0 or self.spend.usd <= expected * (1 + self.threshold):
            return None
        over = self.spend.usd / expected - 1
        self.paused_reason = (
            f"Paused: {_usd(self.spend.usd)} spent on {done} {self.unit_label}s, "
            f"{over:.0%} over the {_usd(expected)} estimated for them."
        )
        return self.paused_reason

    def state(self) -> dict[str, Any]:
        return {
            "estimate_usd": round(self.estimate_usd, 4),
            "spent_usd": round(self.spent_before + self.spend.usd, 4),
            "units_done": self.units_done,
            "units_total": self.units_total,
            "limit": self.limit,
            "paused_reason": self.paused_reason,
        }


def _usd(amount: float) -> str:
    """Dollars with enough decimals to tell small amounts apart."""
    return f"${amount:.2f}" if amount >= 0.1 else f"${amount:.4f}"


def start_guard(
    book: Book,
    step: GuardStep,
    *,
    settings: Settings,
    expected: Callable[[int], float],
    units_total: int,
    start_units: int,
    limit: bool,
    unit_label: str = "window",
) -> CostGuard:
    """A meter for a run starting at unit ``start_units + 1``.

    A fresh start (``start_units == 0``) forgets earlier spend; a
    continuation adds to it.
    """
    previous = (book.cost_guard or {}).get(step) or {}
    guard = CostGuard(
        step=step,
        expected=expected,
        units_total=units_total,
        start_units=start_units,
        spent_before=float(previous.get("spent_usd") or 0.0) if start_units else 0.0,
        limit=limit and settings.COST_PAUSE_THRESHOLD > 0,
        threshold=settings.COST_PAUSE_THRESHOLD,
        min_units=settings.COST_PAUSE_MIN_UNITS,
        unit_label=unit_label,
    )
    save_state(book, guard)
    return guard


def save_state(book: Book, guard: CostGuard) -> None:
    """Write the meter to the book. The caller commits."""
    # A new dict, so SQLAlchemy sees the change to the JSONB column.
    book.cost_guard = {**(book.cost_guard or {}), guard.step: guard.state()}


def linear(total_usd: float, units_total: int) -> Callable[[int], float]:
    """Expected cost when every unit costs about the same."""
    per_unit = total_usd / units_total if units_total else 0.0
    return lambda k: per_unit * k
