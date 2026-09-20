from typing import Any, Dict

from alethic import Kernel, ValidationContext, ValidationResult


class Failing:
    def __init__(self, validator_id: str, code: str, severity: str = "block") -> None:
        self.validator_id = validator_id
        self.code = code
        self.severity = severity

    def validate_action(self, action: Dict[str, Any], committed_beliefs: Dict[str, Any],
                        constraints: Dict[str, Any], context: ValidationContext) -> ValidationResult:
        return ValidationResult(False, self.code, f"{self.validator_id} refused",
                                severity=self.severity)  # type: ignore[arg-type]


class MarginalPass:
    validator_id = "narrow"

    def validate_action(self, action: Dict[str, Any], committed_beliefs: Dict[str, Any],
                        constraints: Dict[str, Any], context: ValidationContext) -> ValidationResult:
        return ValidationResult(True, "OK", "close to the line", marginal=True)


def _propose(kernel: Kernel, trace: str) -> str:
    return kernel.write("planner", "actions", "PROPOSE", "send", {"type": "send"}, trace).id


def test_every_failure_is_reported_not_just_the_first() -> None:
    kernel = Kernel(action_validators=[Failing("a", "A_SAID_NO"), Failing("b", "B_SAID_NO")])
    trace = "t-1"
    decision = kernel.decide_action(_propose(kernel, trace), trace)

    assert decision.ok is False
    assert [r.code for r in decision.results] == ["A_SAID_NO", "B_SAID_NO"]
    assert len(decision.reasons) == 2


def test_marginal_passes_are_collected_as_concerns() -> None:
    kernel = Kernel(action_validators=[MarginalPass()])
    trace = "t-2"
    decision = kernel.decide_action(_propose(kernel, trace), trace)

    assert decision.ok is True
    assert decision.concerns == ("close to the line",)


def test_review_severity_wins_over_block() -> None:
    """If any gate says a person decides, the decision as a whole does."""
    kernel = Kernel(action_validators=[Failing("a", "A", "block"),
                                       Failing("b", "B", "review")])
    trace = "t-3"
    decision = kernel.decide_action(_propose(kernel, trace), trace)

    assert decision.severity == "review"


def test_a_raising_validator_fails_closed_and_stops_the_chain() -> None:
    class Exploding:
        validator_id = "boom"

        def validate_action(self, action: Dict[str, Any], committed_beliefs: Dict[str, Any],
                            constraints: Dict[str, Any], context: ValidationContext) -> ValidationResult:
            raise RuntimeError("kaboom")

    kernel = Kernel(action_validators=[Exploding()])
    trace = "t-4"
    decision = kernel.decide_action(_propose(kernel, trace), trace)

    assert decision.ok is False
    assert decision.code == "VALIDATOR_ERROR"


def test_a_raising_validator_after_a_failure_still_reports_the_crash() -> None:
    """A crash must be visible in `reasons` even when an earlier gate already
    failed -- the earlier failure must not silently swallow the crash detail
    for the person reading the reasons."""
    class Exploding:
        validator_id = "boom"

        def validate_action(self, action: Dict[str, Any], committed_beliefs: Dict[str, Any],
                            constraints: Dict[str, Any], context: ValidationContext) -> ValidationResult:
            raise RuntimeError("kaboom")

    kernel = Kernel(action_validators=[Failing("a", "A_SAID_NO"), Exploding()])
    trace = "t-6"
    decision = kernel.decide_action(_propose(kernel, trace), trace)

    assert decision.ok is False
    assert decision.code == "VALIDATOR_ERROR"
    assert "a refused" in decision.reasons
    assert any("boom" in r and "kaboom" in r for r in decision.reasons), (
        f"the crash detail must survive in reasons, got {decision.reasons!r}"
    )


def test_the_evidence_record_pairs_each_validator_with_its_own_result_in_order() -> None:
    """The chain now runs to completion, so the evidence artifact's
    `validators` list must pair every validator_id with *its own* code and
    outcome, in chain order -- including a gate that passed after an earlier
    one failed."""
    kernel = Kernel(action_validators=[Failing("a", "A_SAID_NO"), MarginalPass()])
    trace = "t-7"
    proposal_id = _propose(kernel, trace)
    decision = kernel.decide_action(proposal_id, trace)

    assert decision.ok is False
    view = kernel.current_view(trace)
    record = view["evidence"]["validation_action_send"]
    assert record["validators"] == [
        {"validator_id": "a", "code": "A_SAID_NO", "ok": False},
        {"validator_id": "narrow", "code": "OK", "ok": True},
    ]


def test_the_old_two_tuple_api_still_works() -> None:
    kernel = Kernel(action_validators=[Failing("a", "A_SAID_NO")])
    trace = "t-5"
    ok, code = kernel.commit_action_from_proposal(_propose(kernel, trace), trace)

    assert (ok, code) == (False, "A_SAID_NO")


def test_a_marginal_pass_survives_a_later_crash() -> None:
    """A concern from a validator that already ran must not vanish just
    because a later validator in the same chain crashes. `concerns` is
    documented as collected "whether or not the overall decision
    succeeded" -- a VALIDATOR_ERROR abort is exactly such a case."""
    class Exploding:
        validator_id = "boom"

        def validate_action(self, action: Dict[str, Any], committed_beliefs: Dict[str, Any],
                            constraints: Dict[str, Any], context: ValidationContext) -> ValidationResult:
            raise RuntimeError("kaboom")

    kernel = Kernel(action_validators=[MarginalPass(), Exploding()])
    trace = "t-8"
    decision = kernel.decide_action(_propose(kernel, trace), trace)

    assert decision.ok is False
    assert decision.code == "VALIDATOR_ERROR"
    assert decision.concerns == ("close to the line",)


def test_belief_and_action_validation_evidence_do_not_collide() -> None:
    """Both chains write into the `evidence` slot, and `current_view()` keys
    that slot by kind, so a belief and an action sharing a name used to
    produce two artifacts under one key -- the action's shadowed the
    belief's, and a reader of the view saw only one of the two decisions.
    """
    kernel = Kernel(action_validators=[Failing("a", "A_SAID_NO")])
    trace = "t-collide"
    kernel.write("tool", "percepts", "COMMIT", "src", {"value": 1}, trace)
    belief = kernel.write(
        "planner", "beliefs", "PROPOSE", "send",
        {"value": 1, "depends_on": ["src"]}, trace,
    )
    assert kernel.commit_belief_from_proposal(belief.id, trace) == (True, "COMMITTED")

    kernel.decide_action(_propose(kernel, trace), trace)

    evidence = kernel.current_view(trace)["evidence"]
    assert evidence["validation_send"]["belief"] == "send", (
        "the action's evidence artifact shadowed the belief's in the view"
    )
    assert evidence["validation_action_send"]["action"] == "send"


def test_a_committed_action_records_its_validation_evidence() -> None:
    """A refused action left an evidence artifact and a committed one left
    none, so the decision most worth auditing -- the one that let an action
    through -- was the one with no record. A gate's `marginal` concern
    existed only in the returned object and was lost the moment it went out
    of scope.
    """
    kernel = Kernel(action_validators=[MarginalPass()])
    trace = "t-pass-evidence"
    proposal_id = _propose(kernel, trace)

    decision = kernel.decide_action(proposal_id, trace)

    assert decision.ok is True
    record = kernel.current_view(trace)["evidence"]["validation_action_send"]
    assert record["action"] == "send"
    assert record["proposal_id"] == proposal_id
    assert record["result"] == "pass"
    assert record["validators"] == [
        {"validator_id": "narrow", "code": "OK", "ok": True},
    ]
    assert record["concerns"] == ["close to the line"], (
        "a concern raised by a gate that let the action through must outlive "
        "the ActionDecision object"
    )


def test_a_committed_action_points_at_the_evidence_that_cleared_it() -> None:
    kernel = Kernel(action_validators=[MarginalPass()])
    trace = "t-pass-refs"
    kernel.decide_action(_propose(kernel, trace), trace)

    committed = [r for r in kernel.store.list_slot("actions") if r.mode == "COMMIT"]
    assert len(committed) == 1
    assert len(committed[0].evidence_refs) == 1, (
        "the committed action cites no validation evidence"
    )
    evidence = kernel.store.get(committed[0].evidence_refs[0])
    assert evidence is not None
    assert evidence.kind == "validation_action_send"
    assert evidence.payload["result"] == "pass"


def test_an_invalid_proposal_refusal_says_why() -> None:
    kernel = Kernel()

    decision = kernel.decide_action("actions:nope:1", "t-invalid")

    assert decision.code == "INVALID_ACTION_PROPOSAL"
    assert decision.reasons == ("Not an active action proposal: actions:nope:1",), (
        f"`reasons` is documented as why it was refused, got {decision.reasons!r}"
    )


def test_a_missing_prediction_refusal_says_why() -> None:
    """The detail was computed and written into the invalidation reason, then
    dropped from the decision handed back to the caller."""
    kernel = Kernel()
    trace = "t-no-prediction"
    proposal_id = _propose(kernel, trace)

    decision = kernel.decide_action(proposal_id, trace, require_prediction=True)

    assert decision.code == "NO_PREDICTION"
    assert decision.reasons == ("No prediction for action type: send",)
    refused = kernel.store.get(proposal_id)
    assert refused is not None
    assert refused.reason == decision.reasons[0], (
        "the store's reason and the decision's reason must be the same sentence"
    )


def test_a_negative_prediction_refusal_says_why() -> None:
    kernel = Kernel()
    trace = "t-negative-prediction"
    kernel.write(
        "kernel", "predictions", "COMMIT", "outcome",
        {"action_type": "send", "expected_outcome": -1}, trace,
    )
    proposal_id = _propose(kernel, trace)

    decision = kernel.decide_action(proposal_id, trace, require_prediction=True)

    assert decision.code == "NEGATIVE_PREDICTION"
    assert decision.reasons == ("Prediction negative for: send",)
    refused = kernel.store.get(proposal_id)
    assert refused is not None
    assert refused.reason == decision.reasons[0]


class Exploding:
    def __init__(self, validator_id: str) -> None:
        self.validator_id = validator_id

    def validate_action(self, action: Dict[str, Any], committed_beliefs: Dict[str, Any],
                        constraints: Dict[str, Any], context: ValidationContext) -> ValidationResult:
        raise RuntimeError("kaboom")


class WrongReturn:
    validator_id = "garbage"

    def validate_action(self, action: Dict[str, Any], committed_beliefs: Dict[str, Any],
                        constraints: Dict[str, Any], context: ValidationContext) -> ValidationResult:
        return "nope"  # type: ignore[return-value]


def test_the_evidence_names_the_validator_that_crashed() -> None:
    """A crashing validator appended no result, so it was absent from the
    evidence artifact's `validators` list entirely and a person reading that
    list concluded the gate never ran. The belief chain records an explicit
    VALIDATOR_ERROR entry; the action chain must too.
    """
    kernel = Kernel(action_validators=[Failing("gate_a", "A_NO"), Exploding("gate_b")])
    trace = "t-crash-evidence"

    decision = kernel.decide_action(_propose(kernel, trace), trace)

    assert decision.code == "VALIDATOR_ERROR"
    record = kernel.current_view(trace)["evidence"]["validation_action_send"]
    assert record["validators"] == [
        {"validator_id": "gate_a", "code": "A_NO", "ok": False},
        {
            "validator_id": "gate_b",
            "code": "VALIDATOR_ERROR",
            "ok": False,
            "detail": "action validator 'gate_b' raised: kaboom",
        },
    ]


def test_the_evidence_names_the_validator_that_returned_garbage() -> None:
    kernel = Kernel(action_validators=[WrongReturn()])
    trace = "t-garbage-evidence"

    decision = kernel.decide_action(_propose(kernel, trace), trace)

    assert decision.code == "VALIDATOR_ERROR"
    record = kernel.current_view(trace)["evidence"]["validation_action_send"]
    assert record["validators"] == [
        {
            "validator_id": "garbage",
            "code": "VALIDATOR_ERROR",
            "ok": False,
            "detail": "action validator 'garbage' returned str, not ValidationResult",
        },
    ]
