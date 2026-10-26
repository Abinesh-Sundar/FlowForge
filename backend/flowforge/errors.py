from __future__ import annotations

from typing import Any


class NodeError(Exception):
    """A node-level failure. `simulated` marks failures injected by WhatIf / Failure Simulator."""

    def __init__(self, type_: str, message: str, details: Any = None, simulated: bool = False,
                 duration_ms: float | None = None):
        super().__init__(message)
        self.type = type_
        self.message = message
        self.details = details
        self.simulated = simulated
        self.duration_ms = duration_ms  # simulated duration (e.g. timeouts)

    def to_dict(self) -> dict:
        return {"type": self.type, "message": self.message, "details": self.details, "simulated": self.simulated}


class GraphInvalid(Exception):
    def __init__(self, issues: list[dict]):
        super().__init__("Workflow graph is invalid")
        self.issues = issues
