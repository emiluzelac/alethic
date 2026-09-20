# Architecture

The Alethic kernel implements the **blackboard architecture pattern** as a governance layer for AI agent orchestration. Instead of letting components communicate through untyped text or loose function calls, all cognitive state lives on a shared blackboard with enforced access control, typed records, and validation gates.

The kernel contains zero domain-specific logic. Models, prompts, tools, tasks,
and application integrations live outside the Alethic package.

## The 7 Semantic Slots

Every record on the blackboard belongs to one of seven slots:

| Slot | Purpose | Typical Writer | Write Mode |
|------|---------|---------------|------------|
| `percepts` | Raw observations from tools | tool | COMMIT |
| `beliefs` | Interpreted conclusions from percepts | kernel (from planner proposals) | PROPOSE → COMMIT |
| `constraints` | Rules that gate actions | symbolic_validator | COMMIT |
| `plans` | Multi-step action proposals | planner | PROPOSE |
| `evidence` | Audit artifacts documenting validation | evidence_validator | COMMIT |
| `predictions` | Forward-looking outcome estimates | kernel (from planner/sim proposals) | PROPOSE → COMMIT |
| `actions` | Concrete operations to execute | kernel (from planner proposals) | PROPOSE → COMMIT |

Slots give the kernel semantic structure. A record in `percepts` means something different from a record in `beliefs`, and the kernel enforces different validation rules for each.

## PROPOSE / COMMIT Protocol

Records are written in one of two modes:

- **PROPOSE** — A tentative record. Proposals sit on the blackboard awaiting validation. They appear in `current_view()` under the `_proposals` key for their slot.
- **COMMIT** — A finalized record. Committed records appear directly in the view as `slot[kind] = payload`.

The lifecycle of a governed decision:

1. A planner **proposes** a belief (e.g., "refund_due")
2. The kernel **validates** the proposal (the configured belief-validator
   chain, confidence gates, and conflict arbitration)
3. On success: the proposal is **invalidated** with reason `SUPERSEDED_BY_COMMIT` and a new committed record is written
4. On failure: the proposal is **invalidated** with a specific reason code (e.g., `STALE_EVIDENCE`)

This two-phase protocol means nothing becomes "true" on the blackboard without passing validation. An LLM can generate fluent, confident proposals — the kernel decides whether the evidence supports them.

## Validation Pipelines

### Belief Commitment

When `commit_belief_from_proposal()` is called:

1. **Validator chain** — Every configured `BeliefValidator` runs in order. The
   default `EvidenceValidator` checks existence, staleness, and conflicts for
   every percept in `depends_on`. Applications can append semantic,
   deterministic, retrieval, or policy validators. Each validator receives a
   `ValidationContext` (`store`, `trace_id`, `now_ms`) alongside the belief
   payload and percepts, so a rule can consult history or the clock and not
   just the dict it was handed — see [Writing a validator](https://github.com/emiluzelac/alethic/blob/main/docs/architecture.md#writing-a-validator).
2. **Short-circuit** — The first rejection atomically records a failed
   validation evidence artifact, invalidates the proposal, and returns its
   result code. Exceptions and malformed results fail closed as
   `VALIDATOR_ERROR` through the same audited path. This is deliberate: a
   belief is a truth claim, and the first disqualifying reason settles it —
   see [Action Commitment](https://github.com/emiluzelac/alethic/blob/main/docs/architecture.md#action-commitment) for why the action chain does
   not do this.
3. **Conflict arbitration** — If the structural validator finds a conflict but
   the percept has confidence >= `conflict_confidence_threshold` (default 0.7),
   that result is recorded as `CONFLICT_ARBITRATED` and the remaining validators
   still run.
4. **Confidence gate** — Dependent percepts must have confidence >=
   `min_confidence` (default 0.5).
5. **Evidence recording** — Success and rejection artifacts record the ordered
   validator IDs, result codes, details, and optional context.
6. **Commit** — The proposal is superseded and a committed belief record is
   written.

Possible built-in return codes: `COMMITTED`, `INVALID_PROPOSAL`,
`MISSING_EVIDENCE`, `STALE_EVIDENCE`, `UNRESOLVED_CONFLICT`, `LOW_CONFIDENCE`,
and `VALIDATOR_ERROR`. Custom validator rejection codes pass through unchanged.

The kernel does not ship a semantic model. An entailment validator is an
application integration implementing the `BeliefValidator` protocol; this
keeps Alethic model- and domain-neutral while making the additional gate part
of the enforced commit path.

### Plan Validation

When `validate_plan()` is called:

1. **Belief requirements** — Every belief in each step's `requires_beliefs` must be committed and truthy
2. **Constraint pre-check** — No step may have a field that a constraint's `blocks_field` would block

Possible return codes: `PLAN_FEASIBLE`, `INVALID_PLAN_PROPOSAL`, `PLAN_MISSING_BELIEF`, `PLAN_BELIEF_NOT_SATISFIED`, `PLAN_{constraint}_BLOCKED`

### Action Commitment

When `decide_action()` is called (`commit_action_from_proposal()` is a thin
two-tuple wrapper over it — `ok, code = decision.ok, decision.code`):

1. **Prediction gate** (optional) — If `require_prediction=True`, a prediction must exist for the action type with non-negative `expected_outcome`
2. **Validator chain, run to completion** — Every configured `ActionValidator`
   runs, in order, receiving the action payload, committed beliefs,
   constraints, and a `ValidationContext`. The default `SymbolicValidator`
   checks belief requirements and constraint blocks. **Unlike the belief
   chain, a failing validator does not stop the chain** — every remaining
   validator still runs, and every result lands in
   `ActionDecision.results`. Exceptions and malformed results still fail
   closed as `VALIDATOR_ERROR`, and the chain stops there, because a crashing
   validator cannot be trusted to keep judging.
3. **Reasons and concerns** — `ActionDecision.reasons` collects the `detail`
   of every failing validator; `ActionDecision.concerns` collects the
   `detail` of every *passing* validator that set `marginal=True` on its
   result, whether or not the decision as a whole succeeded.
   `ActionDecision.severity` is `"review"` if any failing validator set
   `severity="review"` on its result, otherwise `"block"`.
4. **Commit** — On success, the proposal is superseded and a committed action record is written

This is the opposite of belief commitment's short-circuit, and deliberately
so: a belief is a truth claim, where the first disqualifying reason settles
it, so running the rest of the chain against evidence that already failed
would add nothing. An action decision is handed to a person — directly, or
through `severity="review"` — who needs every reason the action was refused
and every gate that passed only narrowly, not just whichever gate happened to
run first.

Possible `ActionDecision.code` values: `COMMITTED`, `INVALID_ACTION_PROPOSAL`,
`NO_PREDICTION`, `NEGATIVE_PREDICTION`, `VALIDATOR_ERROR`, plus whatever the
first failing validator returns (`NO_COMMITTED_BELIEF`,
`BELIEF_NOT_SATISFIED`, `{CONSTRAINT}_BLOCKED` from `SymbolicValidator`, or a
custom validator's own code).

### Prediction Commitment

When `commit_prediction()` is called:

1. **Belief requirements** — Every belief in `requires_beliefs` must exist as a committed belief
2. **Commit** — The proposal is superseded and a committed prediction record is written

Possible return codes: `COMMITTED`, `INVALID_PREDICTION_PROPOSAL`, `PREDICTION_MISSING_BELIEF`

## Writing a validator

A `BeliefValidator` or `ActionValidator` is any object with a `validator_id`
string and the matching `validate_belief_commit` / `validate_action` method —
there is no base class to subclass, only the protocol to satisfy. What makes
this worth doing rather than hand-rolling a check inline is
`ValidationContext`: it hands the validator the kernel's own `store`,
`trace_id`, and `now_ms`, so a rule can depend on history or the clock
instead of only the payload it was handed.

A cooldown is exactly the rule that was impossible to write before
`ValidationContext` existed — refusing a second action of the same kind
inside a time window requires seeing *earlier* episodes and knowing what time
it is, and a validator that only received the action's own payload had
neither. Here it is as an `ActionValidator`:

```python
from alethic import ValidationContext, ValidationResult


class CooldownValidator:
    """Refuse a second contact of the same kind inside a window."""

    validator_id = "cooldown"

    def __init__(self, window_ms: int) -> None:
        self.window_ms = window_ms

    def validate_action(self, action, committed_beliefs, constraints,
                        context: ValidationContext) -> ValidationResult:
        kind = action.get("type", "")
        # find_active_by_kind is scoped to one trace, and a cooldown must see
        # earlier episodes, so scan the slot and filter. O(n) on the shipped
        # stores; a backend built for this can index on (kind, ts_ms).
        previous = [
            r for r in context.store.list_slot("actions")
            if r.kind == kind
            and r.mode == "COMMIT"
            and r.prov.trace_id != context.trace_id
        ]
        if not previous:
            return ValidationResult(True, "OK", "no previous contact")
        last_ms = max(r.prov.ts_ms for r in previous)
        age_ms = context.now_ms - last_ms
        if age_ms < self.window_ms:
            return ValidationResult(
                False, "COOLDOWN_ACTIVE",
                f"last contact {age_ms}ms ago, window is {self.window_ms}ms",
                severity="review",
            )
        return ValidationResult(True, "OK", "outside the cooldown window")
```

Wire it in ahead of, or alongside, `SymbolicValidator`:

```python
kernel = Kernel(
    action_validators=[SymbolicValidator(), CooldownValidator(window_ms=3_600_000)],
)
```

A few things about this example that generalize to any validator:

- `context.store.list_slot(...)` is a read; validators should never write to
  the store. Only the kernel writes evidence and commits records.
- The payload, percepts, beliefs, and constraints a validator is handed are
  deep copies made for that one validator, not the live objects. Mutating
  them is pointless rather than dangerous: the kernel commits the original,
  and the next gate in the chain gets its own untouched copy. A verdict is
  the only thing a validator can change.
- `find_active_by_kind(slot, kind, trace_id)` only looks inside one
  `trace_id`, because it answers "what's active in *this* episode." A
  cooldown's whole point is to see across episodes, so this example scans
  `list_slot("actions")` — every action ever committed, across every trace —
  and filters by `kind`, `mode == "COMMIT"`, and a different `trace_id`
  itself. This is O(n) on both shipped stores; a backend built to answer this
  question at scale would index on `(kind, ts_ms)` instead.
- `severity="review"` on the refusal means this gate does not want to hard
  block the action — it wants a person to decide. In `decide_action()`, that
  bubbles up to `ActionDecision.severity` only if this is a *failing* result;
  a passing-but-close-to-the-line result belongs in `marginal=True` instead
  (surfaced through `ActionDecision.concerns`), not `severity`.
- `context.now_ms` is one clock reading shared by the whole validator chain
  for this call, not a fresh `time.time()` per validator, so two validators
  in the same chain agree on what "now" means.

## Role-Based Access Control

Six roles govern who can write what:

| Role | Allowed Writes |
|------|---------------|
| `tool` | percepts (COMMIT) |
| `planner` | beliefs (PROPOSE), plans (PROPOSE), actions (PROPOSE), predictions (PROPOSE) |
| `symbolic_validator` | constraints (COMMIT) |
| `evidence_validator` | evidence (COMMIT) |
| `sim_validator` | evidence (COMMIT), predictions (COMMIT) |
| `kernel` | beliefs (COMMIT), actions (COMMIT), predictions (COMMIT) |

A `PermissionError` is raised if a role attempts an unauthorized write. Within a
Python process, the kernel is the only role that can commit beliefs, actions, and
predictions — planners can only propose. See [API Reference](api-reference.md) for
the full permissions matrix.

> **This matrix is worker discipline, not a security boundary.** The role is
> supplied by the caller, so it is a declaration of intent rather than an
> authenticated claim. It keeps a well-behaved worker inside its lane; it does
> not defend against a caller that lies about who it is. Only grant kernel
> access to code you trust.

## Record Lifecycle

Every record has a status:

- **ACTIVE** — Current and valid
- **INVALIDATED** — Superseded or rejected, with a `reason` field explaining why
- **EXPIRED** — TTL elapsed (checked lazily on access)

Reason codes for invalidation include `SUPERSEDED_BY_COMMIT`, `STALE_EVIDENCE`, `MISSING_EVIDENCE`, `LOW_CONFIDENCE`, `UNRESOLVED_CONFLICT`, and constraint-specific codes.

Records with `ttl_ms` set on their provenance are checked on every `get()` or `list_slot()` call. If `current_time >= ts_ms + ttl_ms`, the record transitions to `EXPIRED` with reason `TTL_EXPIRED`.

## Store Abstraction

The kernel accepts any store implementing `StoreProtocol` (7 methods: `append`, `get`, `list_slot`, `find_active_by_kind`, `invalidate`, `close`, `transaction`). Two implementations ship:

- **MemoryStore** — In-process, thread-safe with `threading.RLock`. The default
  for ephemeral workloads and testing.
- **SqliteStore** — WAL-mode SQLite with indexed queries. Survives process restarts. Adds extended queries (`list_by_status`, `list_persistent`, `count_invalidated_by_reason`).

Commits are atomic on both. The evidence artifact, the proposal's invalidation
and the committed record land together or not at all, so an interruption leaves
the proposal `ACTIVE` and the episode retryable rather than leaving evidence
behind for a record that was never written. Custom stores must provide the same
transaction boundary through `StoreProtocol.transaction()`.

Pass a store to the kernel constructor:

```python
from alethic.kernel import Kernel
from alethic.sqlite_store import SqliteStore

store = SqliteStore("blackboard.db")
kernel = Kernel(store=store)
```

A third store must agree with `MemoryStore` and `SqliteStore` on the subtle
parts of `StoreProtocol` — lazy TTL expiry, insertion-ordered `list_slot`,
walking past an expired candidate in `find_active_by_kind` rather than
judging only the oldest, and re-entrant `transaction()`. `alethic.testing.store_conformance()`
checks exactly those, against a factory for the new store; see the
[API reference](https://github.com/emiluzelac/alethic/blob/main/docs/api-reference.md#alethictesting). This is not hypothetical —
those two shipped stores once silently disagreed here, with `MemoryStore`
overwriting a duplicate id that `SqliteStore` correctly refused.

## Session and Scope

Records have a `scope` field: `"episode"` (default) or `"persistent"`.

- **Episode-scoped** records belong to a single trace_id and are only visible in that episode's view.
- **Persistent-scoped** records survive across episodes and are visible when `current_view(trace_id, include_persistent=True)` is called.

The `Session` class generates unique trace IDs for each episode: `{session_id}-ep{n}-{random}`. Combined with persistent scope, this enables multi-episode learning — the `AdaptiveWorker` uses this to derive constraints from observed failure patterns across episodes.

## Design Rationale

The architectural choices — blackboard pattern, propose/commit protocol, role-based access, typed slots — are individually well-established in systems engineering and cognitive science. The contribution is their synthesis as a governance layer for LLM agent orchestration.

For the full academic treatment, threat model, formal semantics, and controlled
evaluation results, see
[From Fragile Glue to Governed Cognition](https://doi.org/10.5281/zenodo.18691808).
