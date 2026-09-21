from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Tuple

from .validators import ValidationResult


@dataclass(frozen=True)
class ActionDecision:
    """The outcome of running an action proposal past every gate.

    ``reasons`` are why it was refused; ``concerns`` are gates that passed
    but said they nearly did not. ``severity`` is "review" when any failing
    gate asked for a person, otherwise "block".
    """

    ok: bool
    code: str
    results: Tuple[ValidationResult, ...] = ()
    reasons: Tuple[str, ...] = ()
    concerns: Tuple[str, ...] = ()
    severity: Literal["block", "review"] = "block"
