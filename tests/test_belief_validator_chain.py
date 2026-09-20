"""Belief-validator chain API and fail-closed commitment behavior."""

from __future__ import annotations

from typing import Any, Dict

import pytest

from alethic import EvidenceValidator, Kernel, ValidationContext, ValidationResult


class ExactEntailmentValidator:
    validator_id = "exact_entailment"

    def validate_belief_commit(
        self,
        belief_payload: Dict[str, Any],
        percepts: Dict[str, Any],
        context: ValidationContext,
    ) -> ValidationResult:
        claim = belief_payload.get("value")
        cited = [
            percepts[key].get("value")
            for key in belief_payload.get("depends_on", [])
            if isinstance(percepts.get(key), dict)
        ]
        if claim not in cited:
            return ValidationResult(
                False,
                "SEMANTIC_NOT_ENTAILED",
                "Claim is not entailed by its cited evidence",
                {"claim": claim},
            )
        return ValidationResult(
            True,
            "ENTAILED",
            "Claim exactly matches cited evidence",
            {"supporting_value": claim},
        )


class RecordingValidator:
    def __init__(self, validator_id: str, calls: list[str], *, ok: bool = True) -> None:
        self.validator_id = validator_id
        self.calls = calls
        self.ok = ok

    def validate_belief_commit(
        self,
        belief_payload: Dict[str, Any],
        percepts: Dict[str, Any],
        context: ValidationContext,
    ) -> ValidationResult:
        self.calls.append(self.validator_id)
        return ValidationResult(
            self.ok,
            "OK" if self.ok else "POLICY_REJECTED",
            f"{self.validator_id} {'passed' if self.ok else 'rejected'}",
        )


class RaisingValidator:
    validator_id = "raising"

    def validate_belief_commit(
        self,
        belief_payload: Dict[str, Any],
        percepts: Dict[str, Any],
        context: ValidationContext,
    ) -> ValidationResult:
        raise TimeoutError("external verifier timed out")


class WrongReturnValidator:
    validator_id = "wrong_return"

    def validate_belief_commit(
        self,
        belief_payload: Dict[str, Any],
        percepts: Dict[str, Any],
        context: ValidationContext,
    ) -> Any:
        return {"ok": True}


def propose_claim(
    kernel: Kernel,
    trace_id: str,
    *,
    evidence: str = "Paris is the capital of France.",
    claim: str = "Paris is the capital of France.",
    conflict: bool = False,
    confidence: float = 0.99,
):
    kernel.write(
        "tool",
        "percepts",
        "COMMIT",
        "source",
        {"value": evidence, "stale": False, "conflict": conflict},
        trace_id,
        confidence=confidence,
    )
    return kernel.write(
        "planner",
        "beliefs",
        "PROPOSE",
        "capital",
        {"value": claim, "depends_on": ["source"]},
        trace_id,
        input_refs=["source"],
    )


def test_default_chain_preserves_structural_evidence_validator() -> None:
    kernel = Kernel()
    assert len(kernel.belief_validators) == 1
    assert isinstance(kernel.evidence_validator, EvidenceValidator)
    assert kernel.belief_validators[0].validator_id == "structural_evidence"


def test_semantic_validator_rejects_mismatched_claim() -> None:
    kernel = Kernel(
        belief_validators=[EvidenceValidator(), ExactEntailmentValidator()]
    )
    proposal = propose_claim(
        kernel,
        "semantic-reject",
        claim="Tokyo is the capital of France.",
    )

    committed, code = kernel.commit_belief_from_proposal(
        proposal.id, "semantic-reject"
    )

    assert committed is False
    assert code == "SEMANTIC_NOT_ENTAILED"
    assert "capital" not in kernel.current_view("semantic-reject")["beliefs"]
    rejected = kernel.store.get(proposal.id)
    assert rejected is not None
    assert rejected.status == "INVALIDATED"
    assert rejected.reason == "Claim is not entailed by its cited evidence"
    evidence = kernel.current_view("semantic-reject")["evidence"]["validation_capital"]
    assert evidence["result"] == "fail"
    assert evidence["code"] == "SEMANTIC_NOT_ENTAILED"
    assert evidence["validators"][1]["context"] == {
        "claim": "Tokyo is the capital of France.",
    }


def test_successful_chain_is_recorded_in_validation_evidence() -> None:
    kernel = Kernel(
        belief_validators=[EvidenceValidator(), ExactEntailmentValidator()]
    )
    proposal = propose_claim(kernel, "semantic-pass")

    committed, code = kernel.commit_belief_from_proposal(
        proposal.id, "semantic-pass"
    )

    assert (committed, code) == (True, "COMMITTED")
    evidence = kernel.current_view("semantic-pass")["evidence"]["validation_capital"]
    assert evidence["validators"] == [
        {
            "validator_id": "structural_evidence",
            "code": "OK",
            "detail": "Belief evidence acceptable",
        },
        {
            "validator_id": "exact_entailment",
            "code": "ENTAILED",
            "detail": "Claim exactly matches cited evidence",
            "context": {
                "supporting_value": "Paris is the capital of France.",
            },
        },
    ]


def test_validator_audit_context_round_trips_through_store(store: Any) -> None:
    kernel = Kernel(
        store=store,
        belief_validators=[EvidenceValidator(), ExactEntailmentValidator()],
    )
    proposal = propose_claim(kernel, "audit-round-trip")
    assert kernel.commit_belief_from_proposal(
        proposal.id, "audit-round-trip"
    ) == (True, "COMMITTED")

    evidence = kernel.current_view("audit-round-trip")["evidence"]["validation_capital"]
    assert evidence["validators"][1]["context"] == {
        "supporting_value": "Paris is the capital of France.",
    }


def test_chain_is_ordered_and_short_circuits_after_rejection() -> None:
    calls: list[str] = []
    kernel = Kernel(belief_validators=[
        RecordingValidator("first", calls),
        RecordingValidator("reject", calls, ok=False),
        RecordingValidator("never", calls),
    ])
    proposal = propose_claim(kernel, "ordered-chain")

    committed, code = kernel.commit_belief_from_proposal(
        proposal.id, "ordered-chain"
    )

    assert (committed, code) == (False, "POLICY_REJECTED")
    assert calls == ["first", "reject"]


@pytest.mark.parametrize("validator", [RaisingValidator(), WrongReturnValidator()])
def test_validator_failures_fail_closed(validator: Any) -> None:
    kernel = Kernel(belief_validators=[EvidenceValidator(), validator])
    proposal = propose_claim(kernel, f"failure-{validator.validator_id}")

    committed, code = kernel.commit_belief_from_proposal(
        proposal.id, f"failure-{validator.validator_id}"
    )

    assert (committed, code) == (False, "VALIDATOR_ERROR")
    assert "capital" not in kernel.current_view(
        f"failure-{validator.validator_id}"
    )["beliefs"]
    rejected = kernel.store.get(proposal.id)
    assert rejected is not None
    assert rejected.status == "INVALIDATED"
    evidence = kernel.current_view(
        f"failure-{validator.validator_id}"
    )["evidence"]["validation_capital"]
    assert evidence["result"] == "fail"
    assert evidence["code"] == "VALIDATOR_ERROR"


def test_conflict_arbitration_continues_through_remaining_chain() -> None:
    calls: list[str] = []
    semantic = RecordingValidator("semantic", calls)
    kernel = Kernel(belief_validators=[EvidenceValidator(), semantic])
    proposal = propose_claim(kernel, "arbitrated", conflict=True, confidence=0.9)

    committed, code = kernel.commit_belief_from_proposal(proposal.id, "arbitrated")

    assert (committed, code) == (True, "COMMITTED")
    assert calls == ["semantic"]
    evidence = kernel.current_view("arbitrated")["evidence"]["validation_capital"]
    assert evidence["validators"][0]["code"] == "CONFLICT_ARBITRATED"


def test_compatibility_setter_replaces_only_first_validator() -> None:
    calls: list[str] = []
    second = RecordingValidator("second", calls)
    replacement = RecordingValidator("replacement", calls)
    kernel = Kernel(belief_validators=[EvidenceValidator(), second])

    kernel.evidence_validator = replacement

    assert [item.validator_id for item in kernel.belief_validators] == [
        "replacement",
        "second",
    ]


def test_chain_configuration_rejects_empty_duplicate_and_invalid_entries() -> None:
    with pytest.raises(ValueError, match="at least one"):
        Kernel(belief_validators=[])
    duplicate = RecordingValidator("structural_evidence", [])
    with pytest.raises(ValueError, match="duplicate"):
        Kernel(belief_validators=[EvidenceValidator(), duplicate])
    with pytest.raises(TypeError, match="validator_id"):
        Kernel(belief_validators=[object()])  # type: ignore[list-item]


def test_exposed_chain_is_an_immutable_tuple() -> None:
    kernel = Kernel()
    assert isinstance(kernel.belief_validators, tuple)


def test_belief_validators_receive_the_context() -> None:
    seen = {}

    class Recording:
        validator_id = "recording"

        def validate_belief_commit(
            self,
            belief_payload: Dict[str, Any],
            percepts: Dict[str, Any],
            context: ValidationContext,
        ) -> ValidationResult:
            seen["trace_id"] = context.trace_id
            seen["has_store"] = context.store is not None
            return ValidationResult(True, "OK", "fine")

    kernel = Kernel(belief_validators=[Recording()])
    trace = "t-ctx"
    kernel.write("tool", "percepts", "COMMIT", "obs", {"value": 1}, trace, confidence=0.9)
    proposal = kernel.write("planner", "beliefs", "PROPOSE", "b",
                            {"value": True, "depends_on": ["obs"]}, trace)
    kernel.commit_belief_from_proposal(proposal.id, trace)

    assert seen == {"trace_id": "t-ctx", "has_store": True}
