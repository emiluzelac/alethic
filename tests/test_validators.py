from __future__ import annotations

from alethic import MemoryStore, ValidationContext, ValidationResult
from alethic.validators import EvidenceValidator, SymbolicValidator


class TestEvidenceValidator:
    def setup_method(self):
        self.ev = EvidenceValidator()
        self.context = ValidationContext(store=MemoryStore(), trace_id="t-1", now_ms=1)

    def test_ok_with_clean_percepts(self, clean_charge):
        belief = {"value": True, "depends_on": ["charge"]}
        percepts = {"charge": clean_charge}
        result = self.ev.validate_belief_commit(belief, percepts, self.context)
        assert result.ok is True
        assert result.code == "OK"

    def test_missing_evidence(self):
        belief = {"value": True, "depends_on": ["charge"]}
        percepts = {}  # no charge
        result = self.ev.validate_belief_commit(belief, percepts, self.context)
        assert result.ok is False
        assert result.code == "MISSING_EVIDENCE"
        assert result.context["percept_key"] == "charge"

    def test_stale_evidence(self, stale_charge):
        belief = {"value": True, "depends_on": ["charge"]}
        percepts = {"charge": stale_charge}
        result = self.ev.validate_belief_commit(belief, percepts, self.context)
        assert result.ok is False
        assert result.code == "STALE_EVIDENCE"

    def test_conflicting_evidence(self, conflict_charge):
        belief = {"value": True, "depends_on": ["charge"]}
        percepts = {"charge": conflict_charge}
        result = self.ev.validate_belief_commit(belief, percepts, self.context)
        assert result.ok is False
        assert result.code == "CONFLICTING_EVIDENCE"

    def test_no_depends_on_always_passes(self):
        belief = {"value": True}  # no depends_on
        percepts = {}
        result = self.ev.validate_belief_commit(belief, percepts, self.context)
        assert result.ok is True

    def test_multiple_dependencies_first_missing(self):
        belief = {"value": True, "depends_on": ["charge", "invoice"]}
        percepts = {"invoice": {"stale": False, "conflict": False}}
        result = self.ev.validate_belief_commit(belief, percepts, self.context)
        assert result.ok is False
        assert result.code == "MISSING_EVIDENCE"
        assert result.context["percept_key"] == "charge"

    def test_multiple_dependencies_second_stale(self, clean_charge):
        belief = {"value": True, "depends_on": ["charge", "invoice"]}
        percepts = {"charge": clean_charge, "invoice": {"stale": True}}
        result = self.ev.validate_belief_commit(belief, percepts, self.context)
        assert result.ok is False
        assert result.code == "STALE_EVIDENCE"


class TestSymbolicValidator:
    def setup_method(self):
        self.sv = SymbolicValidator()
        self.context = ValidationContext(store=MemoryStore(), trace_id="t-1", now_ms=1)

    def test_ok_action(self):
        action = {"type": "issue_refund", "requires_beliefs": ["refund_due"]}
        beliefs = {"refund_due": {"value": True}}
        constraints = {}
        result = self.sv.validate_action(action, beliefs, constraints, self.context)
        assert result.ok is True

    def test_missing_belief(self):
        action = {"type": "issue_refund", "requires_beliefs": ["refund_due"]}
        beliefs = {}
        constraints = {}
        result = self.sv.validate_action(action, beliefs, constraints, self.context)
        assert result.ok is False
        assert result.code == "NO_COMMITTED_BELIEF"

    def test_unsatisfied_belief(self):
        action = {"type": "issue_refund", "requires_beliefs": ["refund_due"]}
        beliefs = {"refund_due": {"value": False}}
        constraints = {}
        result = self.sv.validate_action(action, beliefs, constraints, self.context)
        assert result.ok is False
        assert result.code == "BELIEF_NOT_SATISFIED"

    def test_constraint_blocks(self):
        action = {
            "type": "issue_refund",
            "is_duplicate": True,
        }
        beliefs = {}
        constraints = {
            "no_duplicate_refund": {
                "enabled": True,
                "blocks_field": "is_duplicate",
            },
        }
        result = self.sv.validate_action(action, beliefs, constraints, self.context)
        assert result.ok is False
        assert result.code == "NO_DUPLICATE_REFUND_BLOCKED"

    def test_constraint_not_enabled(self):
        action = {"type": "issue_refund", "is_duplicate": True}
        beliefs = {}
        constraints = {
            "no_duplicate_refund": {
                "enabled": False,
                "blocks_field": "is_duplicate",
            },
        }
        result = self.sv.validate_action(action, beliefs, constraints, self.context)
        assert result.ok is True

    def test_constraint_field_not_true(self):
        action = {
            "type": "issue_refund",
            "requires_beliefs": ["refund_due"],
            "is_duplicate": False,
        }
        beliefs = {"refund_due": {"value": True}}
        constraints = {
            "no_duplicate_refund": {
                "enabled": True,
                "blocks_field": "is_duplicate",
            },
        }
        result = self.sv.validate_action(action, beliefs, constraints, self.context)
        assert result.ok is True

    def test_action_with_no_requires_beliefs(self):
        action = {"type": "queue_for_review", "reason": "test"}
        beliefs = {}
        constraints = {}
        result = self.sv.validate_action(action, beliefs, constraints, self.context)
        assert result.ok is True


class TestValidationResult:
    def test_defaults(self):
        vr = ValidationResult(ok=True, code="OK", detail="fine")
        assert vr.context == {}

    def test_with_context(self):
        vr = ValidationResult(ok=False, code="ERR", detail="bad",
                              context={"key": "val"})
        assert vr.context["key"] == "val"


def test_validation_result_defaults_to_blocking_and_not_marginal() -> None:
    result = ValidationResult(False, "NOPE", "no")
    assert result.marginal is False
    assert result.severity == "block"


def test_validation_result_can_ask_for_human_review() -> None:
    result = ValidationResult(False, "NEEDS_A_PERSON", "judgement call", severity="review")
    assert result.severity == "review"


def test_a_passing_result_can_still_be_marginal() -> None:
    """Passed, but close enough to the line that a caller may want to say so."""
    result = ValidationResult(True, "OK", "within tolerance", marginal=True)
    assert result.ok is True
    assert result.marginal is True
