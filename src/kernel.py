from __future__ import annotations
import copy
import math
import threading
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple
import time

from .context import ValidationContext
from .decision import ActionDecision
from .schema import Record, Provenance, RecordIdConflict, Slot, WriteMode
from .store import MemoryStore
from .store_protocol import StoreProtocol
from .permissions import PERMISSIONS, Role
from .validators import (
    ActionValidator,
    BeliefValidator,
    EvidenceValidator,
    SymbolicValidator,
    ValidationResult,
)

def _rid(slot: str, n: int, trace_id: str) -> str:
    return f"{slot}:{trace_id}:{n}"


# A backstop against spinning forever if a store reports every id as taken.
# Reached only by a store that is misbehaving, never by a busy trace.
_MAX_ID_PROBES = 10_000


def _for_validator(value: Dict[str, Any]) -> Dict[str, Any]:
    """Return the copy a validator is handed in place of the live object.

    A validator judges a proposal; it must not be able to rewrite it. Without
    this, every argument the chain receives is the object the kernel is about
    to write, or -- on a store that hands out live record payloads, as
    MemoryStore does -- an object already in the store. A validator that
    mutated one would change what becomes state, and the audit trail would
    record the mutated payload as if it had been proposed. It could also
    disarm gates that run after the chain: emptying ``depends_on`` leaves the
    percept-confidence gate nothing to check.

    Each validator gets its own copy, so no gate can rewrite what a later
    gate in the same chain is asked to judge either. The cost is a deep copy
    per validator per decision; validators are documented as fast and
    payloads as store-serialisable, and a governance decision that can be
    edited by the code judging it is not a decision at all.
    """
    return copy.deepcopy(value)

class Kernel:
    def __init__(self, min_confidence: float = 0.5,
                 conflict_confidence_threshold: float = 0.7,
                 store: Optional[StoreProtocol] = None,
                 *,
                 belief_validators: Optional[Sequence[BeliefValidator]] = None,
                 action_validators: Optional[Sequence[ActionValidator]] = None) -> None:
        self.store: StoreProtocol = store if store is not None else MemoryStore()
        self._counters: Dict[str, int] = {}
        self._counter_lock = threading.Lock()
        self._commit_lock = threading.Lock()
        self._belief_validators = self._prepare_belief_validators(belief_validators)
        self._action_validators = self._prepare_action_validators(action_validators)
        self.min_confidence = min_confidence
        self.conflict_confidence_threshold = conflict_confidence_threshold

    @staticmethod
    def _prepare_belief_validators(
        validators: Optional[Sequence[BeliefValidator]],
    ) -> Tuple[BeliefValidator, ...]:
        configured = list(validators) if validators is not None else [EvidenceValidator()]
        if not configured:
            raise ValueError("belief_validators must contain at least one validator")
        seen: set[str] = set()
        for validator in configured:
            validator_id = getattr(validator, "validator_id", None)
            validate = getattr(validator, "validate_belief_commit", None)
            if not isinstance(validator_id, str) or not validator_id.strip():
                raise TypeError("each belief validator must define a non-empty validator_id")
            if not callable(validate):
                raise TypeError(
                    f"belief validator {validator_id!r} must define validate_belief_commit()"
                )
            if validator_id in seen:
                raise ValueError(f"duplicate belief validator id: {validator_id!r}")
            seen.add(validator_id)
        return tuple(configured)

    @property
    def belief_validators(self) -> Tuple[BeliefValidator, ...]:
        """The immutable ordered chain applied to every belief proposal."""
        return self._belief_validators

    @property
    def evidence_validator(self) -> BeliefValidator:
        """Compatibility alias for the first configured belief validator."""
        return self._belief_validators[0]

    @evidence_validator.setter
    def evidence_validator(self, validator: BeliefValidator) -> None:
        """Replace the first validator while retaining the remainder of the chain."""
        self._belief_validators = self._prepare_belief_validators(
            [validator, *self._belief_validators[1:]]
        )

    @staticmethod
    def _prepare_action_validators(
        validators: Optional[Sequence[ActionValidator]],
    ) -> Tuple[ActionValidator, ...]:
        configured = list(validators) if validators is not None else [SymbolicValidator()]
        if not configured:
            raise ValueError("action_validators must contain at least one validator")
        seen: set[str] = set()
        for validator in configured:
            validator_id = getattr(validator, "validator_id", None)
            validate = getattr(validator, "validate_action", None)
            if not isinstance(validator_id, str) or not validator_id.strip():
                raise TypeError("each action validator must define a non-empty validator_id")
            if not callable(validate):
                raise TypeError(
                    f"action validator {validator_id!r} must define validate_action()"
                )
            if validator_id in seen:
                raise ValueError(f"duplicate action validator id: {validator_id!r}")
            seen.add(validator_id)
        return tuple(configured)

    @property
    def action_validators(self) -> Tuple[ActionValidator, ...]:
        """The immutable ordered chain applied to every action proposal."""
        return self._action_validators

    @property
    def symbolic_validator(self) -> ActionValidator:
        """Compatibility alias for the first configured action validator."""
        return self._action_validators[0]

    @symbolic_validator.setter
    def symbolic_validator(self, validator: ActionValidator) -> None:
        """Replace the first validator while retaining the remainder of the chain."""
        self._action_validators = self._prepare_action_validators(
            [validator, *self._action_validators[1:]]
        )

    def _next_id(self, slot: str, trace_id: str) -> str:
        key = f"{slot}:{trace_id}"
        with self._counter_lock:
            self._counters[key] = self._counters.get(key, 0) + 1
            return _rid(slot, self._counters[key], trace_id)

    def _reject_belief_proposal(
        self,
        proposal: Record,
        trace_id: str,
        code: str,
        detail: str,
        validator_results: List[Dict[str, Any]],
    ) -> Tuple[bool, str]:
        """Atomically record a failed gate and invalidate its proposal."""
        with self.store.transaction():
            self.write(
                "evidence_validator",
                "evidence",
                "COMMIT",
                f"validation_{proposal.kind}",
                {
                    "belief": proposal.kind,
                    "proposal_id": proposal.id,
                    "result": "fail",
                    "code": code,
                    "validators": validator_results,
                },
                trace_id,
            )
            self.store.invalidate(proposal.id, detail)
        return False, code

    def _reject_action(
        self,
        proposal: Record,
        trace_id: str,
        code: str,
        detail: str,
        results: List[ValidationResult],
        severity: Literal["block", "review"] = "block",
        concerns: Tuple[str, ...] = (),
    ) -> ActionDecision:
        """Atomically record the failed gates and invalidate the proposal."""
        with self.store.transaction():
            self.write(
                "evidence_validator",
                "evidence",
                "COMMIT",
                # Distinct from the belief chain's `validation_{kind}`:
                # current_view() keys the evidence slot by kind, so a belief
                # and an action sharing a name would otherwise shadow each
                # other and a reader would see only one of the two decisions.
                f"validation_action_{proposal.kind}",
                {
                    "action": proposal.kind,
                    "proposal_id": proposal.id,
                    "result": "fail",
                    "code": code,
                    "validators": [
                        {"validator_id": v.validator_id, "code": r.code, "ok": r.ok}
                        for v, r in zip(self._action_validators, results)
                    ],
                },
                trace_id,
            )
            self.store.invalidate(proposal.id, detail)
        # `detail` is the reason this call was made -- for a gate that failed
        # cleanly it already equals that gate's own result.detail and so is
        # already in `reasons`; for a validator that raised or returned
        # garbage, no result was appended for it, so `detail` is the *only*
        # place that failure is recorded and must not be dropped just
        # because an earlier gate in the same chain also failed.
        reasons = tuple(r.detail for r in results if not r.ok)
        if detail not in reasons:
            reasons += (detail,)
        return ActionDecision(
            ok=False,
            code=code,
            results=tuple(results),
            reasons=reasons,
            concerns=concerns,
            severity=severity,
        )

    def write(self, role: Role, slot: Slot, mode: WriteMode, kind: str, payload: Dict[str, Any],
              trace_id: str, input_refs: Optional[List[str]] = None, confidence: Optional[float] = None,
              ttl_ms: Optional[int] = None, evidence_refs: Optional[List[str]] = None,
              scope: Literal["episode", "persistent"] = "episode") -> Record:
        perms = PERMISSIONS.get(role)
        allowed = perms.get(slot, frozenset()) if perms is not None else frozenset()
        if mode not in allowed:
            raise PermissionError(f"Role {role} cannot {mode} to {slot}")
        # Rejects NaN and the infinities as well as out-of-range values: every
        # comparison against NaN is False, so a NaN that reached the confidence
        # gate would pass straight through it.
        if confidence is not None and not (0.0 <= confidence <= 1.0):
            raise ValueError(f"confidence must be in [0.0, 1.0], got {confidence!r}")
        # Counters live in this process while the store may outlive it, so the
        # store can already hold `beliefs:order-123:1` — written by an earlier
        # run against the same database, or by another kernel sharing it. Walk
        # forward until an id is free rather than colliding on the primary key.
        # Each pass takes the next counter value, so this converges on the
        # records already under this trace.
        for _ in range(_MAX_ID_PROBES):
            rec = Record(
                id=self._next_id(slot, trace_id),
                slot=slot, mode=mode, kind=kind, payload=payload,
                prov=Provenance(
                    writer_id=role, trace_id=trace_id,
                    ts_ms=int(time.time() * 1000),
                    input_refs=input_refs or [],
                    confidence=confidence, ttl_ms=ttl_ms,
                ),
                evidence_refs=evidence_refs or [],
                scope=scope,
            )
            try:
                self.store.append(rec)
                return rec
            except RecordIdConflict:
                continue
        raise RuntimeError(
            f"could not allocate a record id for {slot}:{trace_id} after "
            f"{_MAX_ID_PROBES} attempts"
        )

    def current_view(self, trace_id: str,
                     include_persistent: bool = False) -> Dict[str, Dict[str, Any]]:
        slots: List[Slot] = ["percepts", "beliefs", "constraints", "plans",
                             "evidence", "predictions", "actions"]
        view: Dict[str, Dict[str, Any]] = {s: {} for s in slots}
        for slot in slots:
            for r in self.store.list_slot(slot):
                if r.status != "ACTIVE":
                    continue
                # include record if it matches the trace_id, or if it's
                # persistent and the caller opted in
                if r.prov.trace_id != trace_id:
                    if not (include_persistent and r.scope == "persistent"):
                        continue
                if r.mode == "COMMIT":
                    view[slot][r.kind] = r.payload
                else:
                    view[slot].setdefault("_proposals", []).append(
                        {"id": r.id, "kind": r.kind, "payload": r.payload})
        return view

    # ── belief commitment with evidence validation ──────────────────────

    def commit_belief_from_proposal(self, proposal_id: str, trace_id: str) -> Tuple[bool, str]:
        """Run belief validators in order, stopping at the first failure.

        Unlike ``decide_action`` — which runs its whole chain to completion —
        this stops at the first failing gate. That asymmetry is deliberate:
        a belief is a truth claim, where the first disqualifying reason
        settles it, while an action decision goes to a person who needs the
        full picture. Do not make this run-to-completion like the action
        chain; the short-circuit here is intentional.
        """
        with self._commit_lock:
            prop = self.store.get(proposal_id)
            if not prop or prop.status != "ACTIVE" or prop.slot != "beliefs" or prop.mode != "PROPOSE":
                return False, "INVALID_PROPOSAL"

            view = self.current_view(trace_id)
            context = ValidationContext(store=self.store, trace_id=trace_id,
                                        now_ms=int(time.time() * 1000))
            validator_results: List[Dict[str, Any]] = []
            for validator in self._belief_validators:
                try:
                    res = validator.validate_belief_commit(
                        _for_validator(prop.payload),
                        _for_validator(view["percepts"]),
                        context,
                    )
                except Exception as exc:
                    detail = (
                        f"Belief validator {validator.validator_id!r} failed: "
                        f"{type(exc).__name__}"
                    )
                    validator_results.append({
                        "validator_id": validator.validator_id,
                        "code": "VALIDATOR_ERROR",
                        "detail": detail,
                    })
                    return self._reject_belief_proposal(
                        prop, trace_id, "VALIDATOR_ERROR", detail, validator_results
                    )
                if not isinstance(res, ValidationResult):
                    detail = (
                        f"Belief validator {validator.validator_id!r} returned "
                        f"{type(res).__name__}, expected ValidationResult"
                    )
                    validator_results.append({
                        "validator_id": validator.validator_id,
                        "code": "VALIDATOR_ERROR",
                        "detail": detail,
                    })
                    return self._reject_belief_proposal(
                        prop, trace_id, "VALIDATOR_ERROR", detail, validator_results
                    )

                result_record: Dict[str, Any] = {
                    "validator_id": validator.validator_id,
                    "code": res.code,
                    "detail": res.detail,
                }
                if res.context:
                    result_record["context"] = res.context

                if not res.ok:
                    # conflict arbitration: high-confidence source overrides conflict
                    if res.code == "CONFLICTING_EVIDENCE":
                        dep_key = res.context.get("percept_key")
                        dep_rec = self.store.find_active_by_kind(
                            "percepts", dep_key, trace_id
                        ) if dep_key else None
                        if (dep_rec and dep_rec.prov.confidence is not None
                                and dep_rec.prov.confidence
                                >= self.conflict_confidence_threshold):
                            result_record["code"] = "CONFLICT_ARBITRATED"
                            validator_results.append(result_record)
                            continue
                        result_record["code"] = "UNRESOLVED_CONFLICT"
                        validator_results.append(result_record)
                        return self._reject_belief_proposal(
                            prop,
                            trace_id,
                            "UNRESOLVED_CONFLICT",
                            res.detail,
                            validator_results,
                        )
                    validator_results.append(result_record)
                    return self._reject_belief_proposal(
                        prop, trace_id, res.code, res.detail, validator_results
                    )
                validator_results.append(result_record)

            # confidence gate on dependent percepts
            for dep_kind in prop.payload.get("depends_on", []):
                dep_rec = self.store.find_active_by_kind("percepts", dep_kind, trace_id)
                if dep_rec and dep_rec.prov.confidence is not None:
                    conf = dep_rec.prov.confidence
                    # An unknown confidence is exactly what this gate is for, so
                    # NaN must fail it rather than slip through `conf < min`.
                    if math.isnan(conf) or conf < self.min_confidence:
                        detail = f"Low confidence on percept: {dep_kind}"
                        validator_results.append({
                            "validator_id": "percept_confidence",
                            "code": "LOW_CONFIDENCE",
                            "detail": detail,
                            "context": {"percept_key": dep_kind},
                        })
                        return self._reject_belief_proposal(
                            prop,
                            trace_id,
                            "LOW_CONFIDENCE",
                            detail,
                            validator_results,
                        )

            # record evidence artifact
            checks = ["existence", "staleness", "conflict"]
            for dep_kind in prop.payload.get("depends_on", []):
                dep_rec = self.store.find_active_by_kind("percepts", dep_kind, trace_id)
                if dep_rec and dep_rec.prov.confidence is not None:
                    checks.append("confidence")
                    break
            # One unit: evidence saying validation passed must not outlive the
            # belief it vouches for, and the proposal must stay retryable unless
            # the belief actually lands.
            with self.store.transaction():
                ev_rec = self.write(
                    "evidence_validator", "evidence", "COMMIT",
                    f"validation_{prop.kind}",
                    {
                        "belief": prop.kind,
                        "result": "pass",
                        "checks": checks,
                        "validators": validator_results,
                    },
                    trace_id,
                )
                self.store.invalidate(proposal_id, "SUPERSEDED_BY_COMMIT")
                self.write(
                    "kernel", "beliefs", "COMMIT", prop.kind, prop.payload, trace_id,
                    input_refs=prop.prov.input_refs, confidence=prop.prov.confidence,
                    evidence_refs=[ev_rec.id],
                )
            return True, "COMMITTED"

    # ── plan feasibility check ──────────────────────────────────────────

    def validate_plan(self, proposal_id: str, trace_id: str) -> Tuple[bool, str]:
        with self._commit_lock:
            prop = self.store.get(proposal_id)
            if not prop or prop.status != "ACTIVE" or prop.slot != "plans" or prop.mode != "PROPOSE":
                return False, "INVALID_PLAN_PROPOSAL"

            view = self.current_view(trace_id)
            committed_beliefs = view["beliefs"]
            constraints = view["constraints"]

            for step in prop.payload.get("steps", []):
                # required beliefs must be committed and truthy
                for belief_name in step.get("requires_beliefs", []):
                    belief = committed_beliefs.get(belief_name)
                    if belief is None:
                        self.store.invalidate(proposal_id, f"Plan requires missing belief: {belief_name}")
                        return False, "PLAN_MISSING_BELIEF"
                    value = belief.get("value") if isinstance(belief, dict) else belief
                    if not value:
                        self.store.invalidate(proposal_id, f"Plan requires unsatisfied belief: {belief_name}")
                        return False, "PLAN_BELIEF_NOT_SATISFIED"
                # constraint pre-check
                for cname, cval in constraints.items():
                    if not isinstance(cval, dict) or not cval.get("enabled"):
                        continue
                    blocked_field = cval.get("blocks_field")
                    if blocked_field and step.get(blocked_field) is True:
                        self.store.invalidate(proposal_id, f"Plan blocked by constraint: {cname}")
                        return False, f"PLAN_{cname.upper()}_BLOCKED"

            return True, "PLAN_FEASIBLE"

    # ── prediction commitment ───────────────────────────────────────────

    def commit_prediction(self, proposal_id: str, trace_id: str) -> Tuple[bool, str]:
        with self._commit_lock:
            prop = self.store.get(proposal_id)
            if (not prop or prop.status != "ACTIVE"
                    or prop.slot != "predictions" or prop.mode != "PROPOSE"):
                return False, "INVALID_PREDICTION_PROPOSAL"
            # validate that required beliefs exist
            for dep in prop.payload.get("requires_beliefs", []):
                if not self.store.find_active_by_kind("beliefs", dep, trace_id):
                    self.store.invalidate(proposal_id,
                                          f"Prediction requires missing belief: {dep}")
                    return False, "PREDICTION_MISSING_BELIEF"
            with self.store.transaction():
                self.store.invalidate(proposal_id, "SUPERSEDED_BY_COMMIT")
                self.write(
                    "kernel", "predictions", "COMMIT", prop.kind, prop.payload,
                    trace_id, input_refs=prop.prov.input_refs,
                    confidence=prop.prov.confidence,
                )
            return True, "COMMITTED"

    # ── action commitment with symbolic validation ──────────────────────

    def decide_action(self, proposal_id: str, trace_id: str,
                      require_prediction: bool = False) -> ActionDecision:
        """Run every action validator to completion and report all of it.

        Unlike ``commit_belief_from_proposal`` — which stops at the first
        failing gate because a belief is a truth claim and the first
        disqualifying reason settles it — this runs the *whole* chain even
        after a gate fails. An action decision goes to a person who needs
        the full picture: every reason it was refused, and every gate that
        passed only narrowly. Do not make this short-circuit like the
        belief chain; that asymmetry is intentional.
        """
        with self._commit_lock:
            prop = self.store.get(proposal_id)
            if not prop or prop.status != "ACTIVE" or prop.slot != "actions" or prop.mode != "PROPOSE":
                return ActionDecision(ok=False, code="INVALID_ACTION_PROPOSAL")
            view = self.current_view(trace_id)

            # optional prediction gate
            if require_prediction:
                action_type = prop.payload.get("type", prop.kind)
                predictions = view.get("predictions", {})
                matched = None
                for _pk, pval in predictions.items():
                    if isinstance(pval, dict) and pval.get("action_type") == action_type:
                        matched = pval
                        break
                if matched is None:
                    self.store.invalidate(proposal_id,
                                          f"No prediction for action type: {action_type}")
                    return ActionDecision(ok=False, code="NO_PREDICTION")
                if matched.get("expected_outcome", 0) < 0:
                    self.store.invalidate(proposal_id,
                                          f"Prediction negative for: {action_type}")
                    return ActionDecision(ok=False, code="NEGATIVE_PREDICTION")

            context = ValidationContext(store=self.store, trace_id=trace_id,
                                        now_ms=int(time.time() * 1000))
            results: List[ValidationResult] = []

            def concerns_so_far() -> Tuple[str, ...]:
                # A concern from a validator that already ran must survive
                # even when a later validator in the same chain aborts the
                # loop -- `ActionDecision.concerns` is collected regardless
                # of whether the overall decision succeeds.
                return tuple(r.detail for r in results if r.ok and r.marginal)

            for validator in self._action_validators:
                try:
                    result = validator.validate_action(
                        _for_validator(prop.payload),
                        _for_validator(view["beliefs"]),
                        _for_validator(view["constraints"]),
                        context,
                    )
                except Exception as exc:  # fail closed: a broken gate is a closed gate
                    detail = f"action validator {validator.validator_id!r} raised: {exc}"
                    return self._reject_action(prop, trace_id, "VALIDATOR_ERROR", detail, results,
                                               concerns=concerns_so_far())
                if not isinstance(result, ValidationResult):
                    detail = (f"action validator {validator.validator_id!r} returned "
                              f"{type(result).__name__}, not ValidationResult")
                    return self._reject_action(prop, trace_id, "VALIDATOR_ERROR", detail, results,
                                               concerns=concerns_so_far())
                results.append(result)

            failures = [r for r in results if not r.ok]
            concerns = concerns_so_far()
            if failures:
                severity: Literal["block", "review"] = (
                    "review" if any(r.severity == "review" for r in failures) else "block")
                return self._reject_action(prop, trace_id, failures[0].code,
                                           failures[0].detail, results,
                                           severity=severity, concerns=concerns)

            with self.store.transaction():
                self.store.invalidate(proposal_id, "SUPERSEDED_BY_COMMIT")
                self.write(
                    "kernel", "actions", "COMMIT", prop.kind, prop.payload, trace_id,
                    input_refs=prop.prov.input_refs, confidence=prop.prov.confidence,
                )
            return ActionDecision(ok=True, code="COMMITTED", results=tuple(results), concerns=concerns)

    def commit_action_from_proposal(self, proposal_id: str, trace_id: str,
                                    require_prediction: bool = False) -> Tuple[bool, str]:
        """Back-compatible two-tuple view of :meth:`decide_action`."""
        decision = self.decide_action(proposal_id, trace_id, require_prediction)
        return decision.ok, decision.code
