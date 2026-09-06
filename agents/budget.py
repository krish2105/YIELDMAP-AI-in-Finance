"""Budgets and the kill switch.

An agent run is bounded on three axes: how many model requests it may make, how long it may take,
and how many steps it may execute. All three exist because they fail differently — a loop burns
steps without time, a slow provider burns time without steps, and a chatty agent burns requests
without either.

Exceeding a budget stops the run and is recorded as a distinct outcome. It is not an error: a run
that was stopped because it reached its limit produced whatever it produced, and the memo it
yields carries the fact that it was truncated.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any


class BudgetExceeded(RuntimeError):
    """The run has spent one of its allowances."""


class KillSwitched(RuntimeError):
    """The run was stopped deliberately."""


@dataclass
class Budget:
    max_requests: int = field(
        default_factory=lambda: int(os.environ.get("AGENT_MAX_REQUESTS_PER_RUN", "40"))
    )
    max_seconds: float = field(
        default_factory=lambda: float(os.environ.get("AGENT_MAX_SECONDS_PER_RUN", "180"))
    )
    max_steps: int = 24

    requests_used: int = 0
    steps_used: int = 0
    started_at: float = field(default_factory=time.monotonic)
    _killed: str | None = None

    @property
    def seconds_used(self) -> float:
        return time.monotonic() - self.started_at

    @property
    def killed(self) -> bool:
        return self._killed is not None

    def kill(self, reason: str = "stopped by operator") -> None:
        """The kill switch. Idempotent, and the first reason is the one kept."""
        if self._killed is None:
            self._killed = reason

    def check(self) -> None:
        """Raise if the run may not continue. Called before every step."""
        if self._killed is not None:
            raise KillSwitched(self._killed)
        if self.requests_used >= self.max_requests:
            raise BudgetExceeded(f"spent all {self.max_requests} model requests")
        if self.steps_used >= self.max_steps:
            raise BudgetExceeded(f"took all {self.max_steps} steps")
        if self.seconds_used >= self.max_seconds:
            raise BudgetExceeded(f"ran for {self.seconds_used:.0f}s of {self.max_seconds:.0f}s")

    def spend_request(self, n: int = 1) -> None:
        self.requests_used += n
        # Checked after spending as well, so the run stops at the limit rather than one past it.
        if self.requests_used > self.max_requests:
            raise BudgetExceeded(f"spent all {self.max_requests} model requests")

    def spend_step(self) -> None:
        self.steps_used += 1

    def remaining(self) -> dict[str, Any]:
        return {
            "requests": max(self.max_requests - self.requests_used, 0),
            "steps": max(self.max_steps - self.steps_used, 0),
            "seconds": max(self.max_seconds - self.seconds_used, 0.0),
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "requests_used": self.requests_used,
            "requests_limit": self.max_requests,
            "steps_used": self.steps_used,
            "steps_limit": self.max_steps,
            "seconds_used": round(self.seconds_used, 2),
            "seconds_limit": self.max_seconds,
            "killed": self.killed,
            "kill_reason": self._killed,
            "remaining": self.remaining(),
        }
