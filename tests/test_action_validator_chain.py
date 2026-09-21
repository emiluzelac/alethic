from typing import Any, Dict

import pytest

from alethic import Kernel, ValidationContext, ValidationResult


class AlwaysOk:
    validator_id = "always_ok"

    def validate_action(self, action: Dict[str, Any], committed_beliefs: Dict[str, Any],
                        constraints: Dict[str, Any], context: ValidationContext) -> ValidationResult:
        return ValidationResult(True, "OK", "fine")


def test_default_chain_is_the_symbolic_validator():
    kernel = Kernel()
    assert [v.validator_id for v in kernel.action_validators] == ["symbolic"]


class AlwaysOk2(AlwaysOk):
    validator_id = "always_ok_2"


def test_chain_is_ordered_and_injectable():
    kernel = Kernel(action_validators=[AlwaysOk(), AlwaysOk2()])
    assert [v.validator_id for v in kernel.action_validators] == ["always_ok", "always_ok_2"]


def test_empty_chain_is_rejected():
    with pytest.raises(ValueError, match="at least one validator"):
        Kernel(action_validators=[])


def test_duplicate_validator_ids_are_rejected():
    with pytest.raises(ValueError, match="duplicate action validator id"):
        Kernel(action_validators=[AlwaysOk(), AlwaysOk()])


def test_validator_without_an_id_is_rejected():
    class Nameless:
        def validate_action(self, action, committed_beliefs, constraints, context):
            return ValidationResult(True, "OK", "fine")

    with pytest.raises(TypeError, match="non-empty validator_id"):
        Kernel(action_validators=[Nameless()])


class RecordingValidator:
    def __init__(self, validator_id: str) -> None:
        self.validator_id = validator_id

    def validate_action(self, action: Dict[str, Any], committed_beliefs: Dict[str, Any],
                        constraints: Dict[str, Any], context: ValidationContext) -> ValidationResult:
        return ValidationResult(True, "OK", "fine")


def test_compatibility_setter_replaces_only_first_validator() -> None:
    second = RecordingValidator("second")
    replacement = RecordingValidator("replacement")
    kernel = Kernel(action_validators=[RecordingValidator("first"), second])

    kernel.symbolic_validator = replacement

    assert [v.validator_id for v in kernel.action_validators] == ["replacement", "second"]
    assert kernel.symbolic_validator is replacement
