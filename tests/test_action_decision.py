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
    record = view["evidence"]["validation_send"]
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
