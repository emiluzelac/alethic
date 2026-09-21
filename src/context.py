from __future__ import annotations

from dataclasses import dataclass

from .store_protocol import StoreProtocol


@dataclass(frozen=True)
class ValidationContext:
    """What a validator may consult besides the payload it is judging.

    Without this a validator sees only dicts, which makes every
    history-dependent or time-dependent rule impossible to express: a
    cooldown cannot know what came before, and a freshness rule cannot know
    what time it is. Frozen so a validator cannot retarget the kernel.
    """

    store: StoreProtocol
    trace_id: str
    now_ms: int
