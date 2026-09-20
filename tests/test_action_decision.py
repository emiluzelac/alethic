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


def test_every_failure_is_reported_not_just_the_first():
    kernel = Kernel(action_validators=[Failing("a", "A_SAID_NO"), Failing("b", "B_SAID_NO")])
    trace = "t-1"
    decision = kernel.decide_action(_propose(kernel, trace), trace)

    assert decision.ok is False
    assert [r.code for r in decision.results] == ["A_SAID_NO", "B_SAID_NO"]
    assert len(decision.reasons) == 2


def test_marginal_passes_are_collected_as_concerns():
    kernel = Kernel(action_validators=[MarginalPass()])
    trace = "t-2"
    decision = kernel.decide_action(_propose(kernel, trace), trace)

    assert decision.ok is True
    assert decision.concerns == ("close to the line",)


def test_review_severity_wins_over_block():
    """If any gate says a person decides, the decision as a whole does."""
    kernel = Kernel(action_validators=[Failing("a", "A", "block"),
                                       Failing("b", "B", "review")])
    trace = "t-3"
    decision = kernel.decide_action(_propose(kernel, trace), trace)

    assert decision.severity == "review"


def test_a_raising_validator_fails_closed_and_stops_the_chain():
    class Exploding:
        validator_id = "boom"

        def validate_action(self, action, committed_beliefs, constraints, context):
            raise RuntimeError("kaboom")

    kernel = Kernel(action_validators=[Exploding()])
    trace = "t-4"
    decision = kernel.decide_action(_propose(kernel, trace), trace)

    assert decision.ok is False
    assert decision.code == "VALIDATOR_ERROR"


def test_the_old_two_tuple_api_still_works():
    kernel = Kernel(action_validators=[Failing("a", "A_SAID_NO")])
    trace = "t-5"
    ok, code = kernel.commit_action_from_proposal(_propose(kernel, trace), trace)

    assert (ok, code) == (False, "A_SAID_NO")
