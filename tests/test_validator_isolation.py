"""A validator judges a proposal; it must not be able to rewrite it.

The docs promise that a validator cannot alter state -- it returns a verdict
and nothing else. That promise only holds if the kernel hands the chain
copies: every argument a validator receives is otherwise the live object the
kernel is about to write (or, on MemoryStore, an object already *in* the
store), so a mutation would change what becomes state and the audit trail
would record the mutated payload as if it had been proposed.

Both backends are exercised, because the exposure differs between them --
MemoryStore hands out live record payloads, SqliteStore rebuilds a fresh dict
per read -- and a governance decision must never depend on which store is
configured.
"""
from __future__ import annotations

from typing import Any, Dict, List

from alethic import Kernel, ValidationContext, ValidationResult
from alethic.store_protocol import StoreProtocol


class MutatingBeliefValidator:
    """Mutates every argument it is handed, then approves."""

    validator_id = "belief_mutator"

    def validate_belief_commit(
        self,
        belief_payload: Dict[str, Any],
        percepts: Dict[str, Any],
        context: ValidationContext,
    ) -> ValidationResult:
        belief_payload["value"] = "INJECTED"
        belief_payload["depends_on"] = []
        for percept in percepts.values():
            if isinstance(percept, dict):
                percept["value"] = "PERCEPT_INJECTED"
        return ValidationResult(True, "OK", "mutated everything it was handed")


class RecordingBeliefValidator:
    """Records what it was handed so a later assertion can inspect it."""

    validator_id = "belief_recorder"

    def __init__(self, seen: List[Dict[str, Any]]) -> None:
        self.seen = seen

    def validate_belief_commit(
        self,
        belief_payload: Dict[str, Any],
        percepts: Dict[str, Any],
        context: ValidationContext,
    ) -> ValidationResult:
        self.seen.append({"belief": dict(belief_payload), "percepts": dict(percepts)})
        return ValidationResult(True, "OK", "looked but did not touch")


class MutatingActionValidator:
    validator_id = "action_mutator"

    def validate_action(
        self,
        action: Dict[str, Any],
        committed_beliefs: Dict[str, Any],
        constraints: Dict[str, Any],
        context: ValidationContext,
    ) -> ValidationResult:
        action["value"] = "INJECTED"
        action["requires_beliefs"] = []
        for belief in committed_beliefs.values():
            if isinstance(belief, dict):
                belief["value"] = "BELIEF_INJECTED"
        for constraint in constraints.values():
            if isinstance(constraint, dict):
                constraint["enabled"] = False
        return ValidationResult(True, "OK", "mutated everything it was handed")


class RecordingActionValidator:
    validator_id = "action_recorder"

    def __init__(self, seen: List[Dict[str, Any]]) -> None:
        self.seen = seen

    def validate_action(
        self,
        action: Dict[str, Any],
        committed_beliefs: Dict[str, Any],
        constraints: Dict[str, Any],
        context: ValidationContext,
    ) -> ValidationResult:
        self.seen.append({
            "action": dict(action),
            "beliefs": dict(committed_beliefs),
            "constraints": dict(constraints),
        })
        return ValidationResult(True, "OK", "looked but did not touch")


# ── beliefs ──────────────────────────────────────────────────────────


def _propose_belief(kernel: Kernel, trace: str, confidence: float) -> str:
    kernel.write(
        "tool", "percepts", "COMMIT", "source",
        {"value": "original", "stale": False, "conflict": False},
        trace, confidence=confidence,
    )
    return kernel.write(
        "planner", "beliefs", "PROPOSE", "claim",
        {"value": "original", "depends_on": ["source"]},
        trace,
    ).id


def test_a_mutating_belief_validator_cannot_change_what_is_committed(
    store: StoreProtocol,
) -> None:
    kernel = Kernel(store=store, belief_validators=[MutatingBeliefValidator()])
    trace = "mutating-belief"
    proposal_id = _propose_belief(kernel, trace, confidence=0.9)

    assert kernel.commit_belief_from_proposal(proposal_id, trace) == (True, "COMMITTED")

    view = kernel.current_view(trace)
    assert view["beliefs"]["claim"] == {"value": "original", "depends_on": ["source"]}, (
        "the validator's mutation of belief_payload reached the committed record"
    )
    assert view["percepts"]["source"]["value"] == "original", (
        "the validator's mutation of the percepts view reached stored state"
    )


def test_a_mutating_belief_validator_cannot_disarm_the_confidence_gate(
    store: StoreProtocol,
) -> None:
    """Clearing `depends_on` leaves the confidence gate nothing to check.

    The gate reads `prop.payload["depends_on"]` after the chain has run, so a
    validator that empties that list walks a low-confidence belief straight
    past the gate that exists to stop it.
    """
    kernel = Kernel(store=store, belief_validators=[MutatingBeliefValidator()])
    trace = "mutating-belief-gate"
    proposal_id = _propose_belief(kernel, trace, confidence=0.1)

    committed, code = kernel.commit_belief_from_proposal(proposal_id, trace)

    assert (committed, code) == (False, "LOW_CONFIDENCE"), (
        "a validator emptied depends_on and the low-confidence percept gate "
        f"never fired; got {(committed, code)!r}"
    )


def test_a_belief_validator_cannot_rewrite_what_the_next_gate_judges(
    store: StoreProtocol,
) -> None:
    seen: List[Dict[str, Any]] = []
    kernel = Kernel(
        store=store,
        belief_validators=[MutatingBeliefValidator(), RecordingBeliefValidator(seen)],
    )
    trace = "mutating-belief-chain"
    proposal_id = _propose_belief(kernel, trace, confidence=0.9)

    kernel.commit_belief_from_proposal(proposal_id, trace)

    assert len(seen) == 1
    assert seen[0]["belief"] == {"value": "original", "depends_on": ["source"]}, (
        "the second gate judged a payload the first gate had rewritten"
    )
    assert seen[0]["percepts"]["source"]["value"] == "original", (
        "the second gate judged percepts the first gate had rewritten"
    )


# ── actions ──────────────────────────────────────────────────────────


def _propose_action(kernel: Kernel, trace: str) -> str:
    kernel.write("kernel", "beliefs", "COMMIT", "ready", {"value": True}, trace)
    kernel.write(
        "symbolic_validator", "constraints", "COMMIT", "quiet_hours",
        {"enabled": True, "blocks_field": "after_hours"}, trace,
    )
    return kernel.write(
        "planner", "actions", "PROPOSE", "send",
        {"type": "send", "value": "original", "requires_beliefs": ["ready"]},
        trace,
    ).id


def test_a_mutating_action_validator_cannot_change_what_is_committed(
    store: StoreProtocol,
) -> None:
    kernel = Kernel(store=store, action_validators=[MutatingActionValidator()])
    trace = "mutating-action"
    proposal_id = _propose_action(kernel, trace)

    decision = kernel.decide_action(proposal_id, trace)

    assert decision.ok is True
    view = kernel.current_view(trace)
    assert view["actions"]["send"] == {
        "type": "send", "value": "original", "requires_beliefs": ["ready"],
    }, "the validator's mutation of the action payload reached the committed record"
    assert view["beliefs"]["ready"] == {"value": True}, (
        "the validator's mutation of the beliefs view reached stored state"
    )
    assert view["constraints"]["quiet_hours"]["enabled"] is True, (
        "the validator's mutation of the constraints view reached stored state"
    )


def test_an_action_validator_cannot_rewrite_what_the_next_gate_judges(
    store: StoreProtocol,
) -> None:
    seen: List[Dict[str, Any]] = []
    kernel = Kernel(
        store=store,
        action_validators=[MutatingActionValidator(), RecordingActionValidator(seen)],
    )
    trace = "mutating-action-chain"
    proposal_id = _propose_action(kernel, trace)

    kernel.decide_action(proposal_id, trace)

    assert len(seen) == 1
    assert seen[0]["action"]["value"] == "original", (
        "the second gate judged an action payload the first gate had rewritten"
    )
    assert seen[0]["action"]["requires_beliefs"] == ["ready"], (
        "the first gate erased the belief requirement the second gate checks"
    )
    assert seen[0]["beliefs"]["ready"] == {"value": True}, (
        "the second gate judged beliefs the first gate had rewritten"
    )
    assert seen[0]["constraints"]["quiet_hours"]["enabled"] is True, (
        "the first gate disabled a constraint the second gate enforces"
    )
