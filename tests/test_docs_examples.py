"""The worked examples in docs/architecture.md are executed here.

"Writing a validator" is the entry point for the pluggable-validator API, so
its `CooldownValidator` is the shape third-party gates get copied from. A
worked example that is only ever read drifts from what the kernel does; this
runs the code in the document itself, extracted from the fenced block, so it
cannot drift without failing.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict

import pytest

from alethic import Kernel, SymbolicValidator, ValidationContext, ValidationResult

DOCS = Path(__file__).resolve().parent.parent / "docs" / "architecture.md"


def _python_block_defining(name: str) -> str:
    blocks = re.findall(r"```python\n(.*?)```", DOCS.read_text(), re.S)
    matching = [b for b in blocks if f"class {name}" in b]
    assert len(matching) == 1, (
        f"expected exactly one documented `class {name}`, found {len(matching)}"
    )
    return matching[0]


def _cooldown_class() -> Any:
    namespace: Dict[str, Any] = {}
    exec(compile(_python_block_defining("CooldownValidator"), str(DOCS), "exec"),
         namespace)
    return namespace["CooldownValidator"]


def _propose_contact(kernel: Kernel, trace: str) -> str:
    return kernel.write(
        "planner", "actions", "PROPOSE", "contact", {"type": "contact"}, trace,
    ).id


def _kernel_with_cooldown(window_ms: int = 3_600_000) -> Kernel:
    cooldown = _cooldown_class()
    return Kernel(action_validators=[SymbolicValidator(), cooldown(window_ms=window_ms)])


def test_the_documented_cooldown_blocks_a_recent_contact() -> None:
    """The example has to work at all before its edge cases matter."""
    kernel = _kernel_with_cooldown()
    assert kernel.decide_action(_propose_contact(kernel, "trace-1"), "trace-1").ok

    decision = kernel.decide_action(_propose_contact(kernel, "trace-2"), "trace-2")

    assert decision.ok is False
    assert decision.code == "COOLDOWN_ACTIVE"
    assert decision.severity == "review"


def test_the_documented_cooldown_ignores_a_retracted_contact() -> None:
    """The example filters on kind, mode and trace_id but not status, so an
    INVALIDATED or EXPIRED action -- one that was retracted, or superseded,
    and never counted as having happened -- still started a cooldown. It is
    the canonical worked example for this branch's headline feature, so the
    bug is copied into every gate written from it.
    """
    kernel = _kernel_with_cooldown()
    assert kernel.decide_action(_propose_contact(kernel, "trace-1"), "trace-1").ok
    committed = [r for r in kernel.store.list_slot("actions") if r.mode == "COMMIT"]
    assert len(committed) == 1
    kernel.store.invalidate(committed[0].id, "RETRACTED")

    decision = kernel.decide_action(_propose_contact(kernel, "trace-2"), "trace-2")

    assert decision.ok is True, (
        "a retracted action still triggered the cooldown: "
        f"{decision.code} {decision.reasons!r}"
    )


def test_writing_a_validator_warns_about_the_commit_lock() -> None:
    """Both chains run every validator inside `Kernel._commit_lock`, which is
    held for the whole decision. Before pluggable validators that lock
    covered two fast in-tree gates; it now covers third-party code the same
    document invites to do retrieval and model calls. A stranger writing a
    validator cannot discover that from the code, and the consequences --
    one slow gate stalling every commit on the kernel, and a gate that calls
    back into `kernel.commit_*` deadlocking outright -- are not recoverable
    by the caller.
    """
    section = DOCS.read_text().split("## Writing a validator", 1)
    assert len(section) == 2, "docs/architecture.md lost its 'Writing a validator' section"
    body = section[1].split("\n## ", 1)[0].lower()

    assert "commit lock" in body or "_commit_lock" in body, (
        "'Writing a validator' does not mention that validators run under the "
        "kernel's commit lock"
    )
    assert "deadlock" in body, (
        "'Writing a validator' does not warn that re-entering the kernel from "
        "a validator deadlocks"
    )


def test_validators_really_do_run_under_the_commit_lock() -> None:
    """The warning above is only worth printing while it is true."""
    held: list[bool] = []

    class Peeking:
        validator_id = "peek"

        def validate_action(self, action: Dict[str, Any],
                            committed_beliefs: Dict[str, Any],
                            constraints: Dict[str, Any],
                            context: ValidationContext) -> ValidationResult:
            held.append(kernel._commit_lock.locked())
            return ValidationResult(True, "OK", "fine")

        def validate_belief_commit(self, belief_payload: Dict[str, Any],
                                   percepts: Dict[str, Any],
                                   context: ValidationContext) -> ValidationResult:
            held.append(kernel._commit_lock.locked())
            return ValidationResult(True, "OK", "fine")

    kernel = Kernel(action_validators=[Peeking()], belief_validators=[Peeking()])
    trace = "lock-check"
    belief = kernel.write("planner", "beliefs", "PROPOSE", "b", {"value": 1}, trace)
    kernel.commit_belief_from_proposal(belief.id, trace)
    kernel.decide_action(_propose_contact(kernel, trace), trace)

    assert held == [True, True], (
        "a validator ran without the commit lock held; the documented warning "
        "no longer describes the code"
    )


def test_a_validator_that_re_enters_the_kernel_is_not_silently_fine() -> None:
    """The documented reason `ValidationContext` carries the `store` and not
    the `Kernel`: a validator calling back into a commit path would block on
    a lock its own call already holds.
    """
    class ReEntrant:
        validator_id = "re_entrant"

        def validate_action(self, action: Dict[str, Any],
                            committed_beliefs: Dict[str, Any],
                            constraints: Dict[str, Any],
                            context: ValidationContext) -> ValidationResult:
            assert kernel._commit_lock.locked()
            assert not kernel._commit_lock.acquire(blocking=False), (
                "the commit lock was re-acquirable from inside a validator"
            )
            return ValidationResult(True, "OK", "fine")

    kernel = Kernel(action_validators=[ReEntrant()])
    trace = "re-entrant"

    assert kernel.decide_action(_propose_contact(kernel, trace), trace).ok


def test_the_cooldown_example_is_the_only_one_of_its_name() -> None:
    with pytest.raises(AssertionError, match="exactly one documented"):
        _python_block_defining("NoSuchValidator")
