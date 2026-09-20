# API Reference

Complete reference for all public classes and methods in the `alethic` package.

## Kernel

`alethic.kernel.Kernel` — The central orchestrator. Manages the blackboard, enforces permissions, and runs validation pipelines.

### Constructor

```python
Kernel(
    min_confidence: float = 0.5,
    conflict_confidence_threshold: float = 0.7,
    store: Optional[StoreProtocol] = None,
    *,
    belief_validators: Optional[Sequence[BeliefValidator]] = None,
    action_validators: Optional[Sequence[ActionValidator]] = None,
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `min_confidence` | `float` | `0.5` | Minimum confidence on dependent percepts for belief commitment |
| `conflict_confidence_threshold` | `float` | `0.7` | Confidence threshold above which conflicts are arbitrated |
| `store` | `Optional[StoreProtocol]` | `None` | Backing store; defaults to `MemoryStore()` if not provided |
| `belief_validators` | `Optional[Sequence[BeliefValidator]]` | `None` | Ordered fail-closed chain; defaults to one `EvidenceValidator()` |
| `action_validators` | `Optional[Sequence[ActionValidator]]` | `None` | Ordered run-to-completion chain; defaults to one `SymbolicValidator()` |

`belief_validators` and `action_validators` must each be non-empty, and
validator IDs must be unique within their own chain. The kernel copies each
sequence into an immutable tuple. `kernel.evidence_validator` and
`kernel.symbolic_validator` are compatibility properties that get or replace
only the first validator in the belief and action chains respectively,
without removing the rest of the chain.

### Methods

#### `write()`

```python
write(
    role: Role,
    slot: Slot,
    mode: WriteMode,
    kind: str,
    payload: Dict[str, Any],
    trace_id: str,
    input_refs: Optional[List[str]] = None,
    confidence: Optional[float] = None,
    ttl_ms: Optional[int] = None,
    evidence_refs: Optional[List[str]] = None,
    scope: Literal["episode", "persistent"] = "episode",
) -> Record
```

Write a record to the blackboard. Raises `PermissionError` if the role is not authorized for the given slot+mode combination.

| Parameter | Type | Description |
|-----------|------|-------------|
| `role` | `Role` | Writer's role (determines permissions) |
| `slot` | `Slot` | Target slot |
| `mode` | `WriteMode` | `"PROPOSE"` or `"COMMIT"` |
| `kind` | `str` | Record kind (e.g., `"charge"`, `"refund_due"`) |
| `payload` | `Dict[str, Any]` | Record data |
| `trace_id` | `str` | Episode trace identifier |
| `input_refs` | `Optional[List[str]]` | IDs of records this depends on |
| `confidence` | `Optional[float]` | Confidence score (0.0 to 1.0) |
| `ttl_ms` | `Optional[int]` | Time-to-live in milliseconds |
| `evidence_refs` | `Optional[List[str]]` | IDs of evidence records |
| `scope` | `Literal["episode", "persistent"]` | Record scope |

Returns the created `Record`.

#### `current_view()`

```python
current_view(
    trace_id: str,
    include_persistent: bool = False,
) -> Dict[str, Dict[str, Any]]
```

Returns a snapshot of the blackboard for a given trace. The result maps each slot name to its contents. Committed records appear as `slot[kind] = payload`. Proposals appear under `slot["_proposals"]`.

| Parameter | Type | Description |
|-----------|------|-------------|
| `trace_id` | `str` | Episode trace identifier |
| `include_persistent` | `bool` | Include persistent-scoped records from other episodes |

#### `commit_belief_from_proposal()`

```python
commit_belief_from_proposal(
    proposal_id: str,
    trace_id: str,
) -> Tuple[bool, str]
```

Validate and commit a belief proposal. Runs the ordered belief-validator chain,
confidence checks, and conflict arbitration. Each validator receives a
`ValidationContext` (`store`, `trace_id`, `now_ms`) alongside the belief
payload and percepts. The first validator rejection short-circuits the chain
and its code is returned unchanged — a belief is a truth claim, so the first
disqualifying reason settles it and the rest of the chain does not run. See
[`decide_action()`](https://github.com/emiluzelac/alethic/blob/main/docs/api-reference.md#decide_action) for why the action chain does the
opposite.

| Return | Description |
|--------|-------------|
| `(True, "COMMITTED")` | Belief committed successfully |
| `(False, "INVALID_PROPOSAL")` | Proposal not found, inactive, wrong slot, or wrong mode |
| `(False, "MISSING_EVIDENCE")` | Dependent percept does not exist |
| `(False, "STALE_EVIDENCE")` | Dependent percept is stale |
| `(False, "UNRESOLVED_CONFLICT")` | Dependent percept has conflict, below arbitration threshold |
| `(False, "LOW_CONFIDENCE")` | Dependent percept confidence below `min_confidence` |
| `(False, "VALIDATOR_ERROR")` | A validator raised an exception or returned something other than `ValidationResult` |
| `(False, "<CUSTOM_CODE>")` | A custom validator rejected the proposal; its code passes through unchanged |

#### `validate_plan()`

```python
validate_plan(
    proposal_id: str,
    trace_id: str,
) -> Tuple[bool, str]
```

Pre-flight feasibility check on a plan proposal.

| Return | Description |
|--------|-------------|
| `(True, "PLAN_FEASIBLE")` | All plan steps are feasible |
| `(False, "INVALID_PLAN_PROPOSAL")` | Proposal not found, inactive, wrong slot, or wrong mode |
| `(False, "PLAN_MISSING_BELIEF")` | A required belief is not committed |
| `(False, "PLAN_BELIEF_NOT_SATISFIED")` | A required belief is committed but falsy |
| `(False, "PLAN_{C}_BLOCKED")` | A constraint blocks a plan step |

#### `commit_prediction()`

```python
commit_prediction(
    proposal_id: str,
    trace_id: str,
) -> Tuple[bool, str]
```

Validate and commit a prediction proposal.

| Return | Description |
|--------|-------------|
| `(True, "COMMITTED")` | Prediction committed successfully |
| `(False, "INVALID_PREDICTION_PROPOSAL")` | Proposal not found, inactive, wrong slot, or wrong mode |
| `(False, "PREDICTION_MISSING_BELIEF")` | A required belief is not committed |

#### `decide_action()`

```python
decide_action(
    proposal_id: str,
    trace_id: str,
    require_prediction: bool = False,
) -> ActionDecision
```

Validate an action proposal against the whole ordered `action_validators`
chain, optionally gated on predictions first. Each validator receives a
`ValidationContext` alongside the action payload, committed beliefs, and
constraints. Unlike the belief chain, **every validator runs to completion**
even after one fails: the returned `ActionDecision.results` holds one
`ValidationResult` per validator, in order, so a person reviewing a refusal
sees every reason the action was refused (`reasons`) and every gate that
passed only narrowly (`concerns`), not just whichever gate happened to run
first. This is deliberate — see [CHANGELOG.md](https://github.com/emiluzelac/alethic/blob/main/CHANGELOG.md)
for why the two chains disagree on this.

| Parameter | Type | Description |
|-----------|------|-------------|
| `require_prediction` | `bool` | If `True`, requires a committed prediction with non-negative `expected_outcome` |

| Return (`ActionDecision.code`) | `ok` | Description |
|-------|------|-------------|
| `"COMMITTED"` | `True` | Action committed; every validator passed |
| `"INVALID_ACTION_PROPOSAL"` | `False` | Proposal not found, inactive, wrong slot, or wrong mode |
| `"NO_PREDICTION"` | `False` | `require_prediction=True` but no matching prediction found |
| `"NEGATIVE_PREDICTION"` | `False` | Matching prediction has negative `expected_outcome` |
| `"VALIDATOR_ERROR"` | `False` | A validator raised an exception or returned something other than `ValidationResult` |
| `"<CUSTOM_CODE>"` | `False` | The first failing validator's code (e.g. `NO_COMMITTED_BELIEF`, `BELIEF_NOT_SATISFIED`, `{CONSTRAINT}_BLOCKED` from `SymbolicValidator`); custom validator codes pass through unchanged |

`ActionDecision.severity` is `"review"` if any failing validator returned
`severity="review"`, otherwise `"block"`. `ActionDecision.concerns` collects
the `detail` of every validator that passed with `marginal=True`, whether or
not the overall decision succeeded.

#### `commit_action_from_proposal()`

```python
commit_action_from_proposal(
    proposal_id: str,
    trace_id: str,
    require_prediction: bool = False,
) -> Tuple[bool, str]
```

Back-compatible two-tuple wrapper over [`decide_action()`](https://github.com/emiluzelac/alethic/blob/main/docs/api-reference.md#decide_action):
`return decision.ok, decision.code`. Prefer `decide_action()` for new code —
it is the only way to see every validator's result, the per-gate `concerns`,
and `severity`.

| Return | Description |
|--------|-------------|
| `(True, "COMMITTED")` | Action committed successfully |
| `(False, "INVALID_ACTION_PROPOSAL")` | Proposal not found, inactive, wrong slot, or wrong mode |
| `(False, "NO_PREDICTION")` | `require_prediction=True` but no matching prediction found |
| `(False, "NEGATIVE_PREDICTION")` | Matching prediction has negative `expected_outcome` |
| `(False, "VALIDATOR_ERROR")` | A validator raised an exception or returned something other than `ValidationResult` |
| `(False, "NO_COMMITTED_BELIEF")` | A required belief is not committed |
| `(False, "BELIEF_NOT_SATISFIED")` | A required belief is committed but falsy |
| `(False, "{CONSTRAINT}_BLOCKED")` | A constraint blocks the action |
| `(False, "<CUSTOM_CODE>")` | A custom validator rejected the proposal; its code passes through unchanged |

---

## Schema

### `Record`

`alethic.schema.Record` — A single entry on the blackboard.

```python
@dataclass
class Record:
    id: str                                              # Auto-generated: "{slot}:{trace_id}:{n}"
    slot: Slot                                           # Target slot
    mode: WriteMode                                      # "PROPOSE" or "COMMIT"
    kind: str                                            # Record kind identifier
    payload: Dict[str, Any]                              # Arbitrary data
    prov: Provenance                                     # Provenance metadata
    evidence_refs: List[str] = []                        # IDs of evidence records
    status: Literal["ACTIVE", "INVALIDATED", "EXPIRED"] = "ACTIVE"
    reason: Optional[str] = None                         # Why invalidated/expired
    scope: Literal["episode", "persistent"] = "episode"  # Lifetime scope
```

### `Provenance`

`alethic.schema.Provenance` — Metadata attached to every record.

```python
@dataclass
class Provenance:
    writer_id: str                          # Role that wrote the record
    trace_id: str                           # Episode trace identifier
    ts_ms: int                              # Timestamp (milliseconds since epoch)
    input_refs: List[str] = []              # IDs of input records
    confidence: Optional[float] = None      # Confidence score (0.0 to 1.0)
    ttl_ms: Optional[int] = None            # Time-to-live in milliseconds
```

### Type Aliases

```python
Slot = Literal["percepts", "beliefs", "constraints", "plans", "evidence", "predictions", "actions"]
WriteMode = Literal["PROPOSE", "COMMIT"]
```

---

## Stores

### `StoreProtocol`

`alethic.store_protocol.StoreProtocol` — Interface that any backing store must satisfy. Decorated with `@runtime_checkable`.

| Method | Signature | Description |
|--------|-----------|-------------|
| `append` | `(rec: Record) -> None` | Add a record to the store |
| `get` | `(rec_id: str) -> Optional[Record]` | Retrieve by ID (checks TTL) |
| `list_slot` | `(slot: Slot) -> List[Record]` | All records in a slot, in append order (checks TTL) |
| `find_active_by_kind` | `(slot: Slot, kind: str, trace_id: str) -> Optional[Record]` | Find active record by kind+trace |
| `invalidate` | `(rec_id: str, reason: str) -> None` | Mark record as INVALIDATED |
| `transaction` | `() -> ContextManager[None]` | Make a validation-and-commit sequence atomic |
| `close` | `() -> None` | Release resources (e.g., close database connection) |

### `MemoryStore`

`alethic.store.MemoryStore` — In-process thread-safe store. Implements `StoreProtocol`. Uses `threading.RLock` for concurrency.

Constructor: `MemoryStore()` — no parameters.

### `SqliteStore`

`alethic.sqlite_store.SqliteStore` — SQLite-backed persistent store. WAL mode, indexed queries.

Constructor:

```python
SqliteStore(path: str = "blackboard.db")
```

Implements all `StoreProtocol` methods plus:

| Method | Signature | Description |
|--------|-----------|-------------|
| `list_by_status` | `(status: str) -> List[Record]` | All records with given status, in append order |
| `list_persistent` | `(slot: Optional[str] = None) -> List[Record]` | All persistent-scope records, in append order |
| `count_invalidated_by_reason` | `() -> Dict[str, int]` | `{reason: count}` for invalidated records |
| `close` | `() -> None` | Close the database connection |

---

## Validators

### `ValidationContext`

`alethic.context.ValidationContext` — What a validator may consult besides
the payload it is judging. Passed as the last positional argument to every
`BeliefValidator` and `ActionValidator` call. Frozen: a validator cannot
retarget the kernel mid-run.

```python
@dataclass(frozen=True)
class ValidationContext:
    store: StoreProtocol  # the kernel's backing store, for read-only queries
    trace_id: str          # the episode this proposal belongs to
    now_ms: int            # the kernel's notion of "now" for this call
```

| Field | Type | Description |
|-------|------|-------------|
| `store` | `StoreProtocol` | The kernel's own store. Validators may call `list_slot`, `find_active_by_kind`, etc., but should not write. |
| `trace_id` | `str` | The proposal's episode. `find_active_by_kind` is scoped to this one trace — a validator that needs history *across* traces (e.g. a cooldown) must scan `list_slot` and filter itself; see [Writing a validator](https://github.com/emiluzelac/alethic/blob/main/docs/architecture.md#writing-a-validator). |
| `now_ms` | `int` | Milliseconds since epoch, captured once per `commit_belief_from_proposal()` / `decide_action()` call so every validator in the chain sees the same clock reading. |

The other arguments — the belief payload or action, and the percepts,
beliefs, and constraints views — are deep copies made for that one validator,
not the kernel's live objects. A validator that mutates them changes nothing:
the kernel commits the original, and the next gate in the chain receives its
own untouched copy.

Without this, a validator sees only dicts, which makes every history- or
time-dependent rule impossible to express. Do not confuse this with
`ValidationResult.context`, an unrelated `Dict[str, Any]` field a validator
uses to attach arbitrary supporting data to its own result.

### `BeliefValidator`

`alethic.validators.BeliefValidator` — Structural protocol for a synchronous
belief-commitment gate.

```python
class BeliefValidator(Protocol):
    validator_id: str

    def validate_belief_commit(
        self,
        belief_payload: Dict[str, Any],
        percepts: Dict[str, Any],
        context: ValidationContext,
    ) -> ValidationResult: ...
```

`validator_id` must be non-empty and unique within a kernel. Validators run in
configuration order and should return an affirmative `ValidationResult` only
when their own check passes. Exceptions and malformed return values fail
closed. Successful and rejected results—including optional `context` such as
supporting evidence spans or verifier votes—are written into validation
evidence artifacts.

### `ValidationResult`

`alethic.validators.ValidationResult` — Result of a validation check.

```python
@dataclass
class ValidationResult:
    ok: bool                                # Whether validation passed
    code: str                               # Result code (e.g., "OK", "STALE_EVIDENCE")
    detail: str                             # Human-readable description
    context: Dict[str, Any] = {}            # Additional context (e.g., {"percept_key": "charge"})
    marginal: bool = False                  # True on a pass that nearly didn't; surfaced as a `concern`
    severity: Literal["block", "review"] = "block"  # Meaningful only when ok=False
```

`marginal` and `severity` are both defaulted, so existing
`ValidationResult(...)` construction is unaffected. `severity` is only
consulted when `ok=False`: `"block"` is a hard stop, `"review"` means the
gate refuses but the decision belongs to a person — `Kernel.decide_action()`
raises `ActionDecision.severity` to `"review"` if any failing validator in
the chain says so.

### `EvidenceValidator`

`alethic.validators.EvidenceValidator` — The default structural validator. It
checks the presence and condition of cited percepts; it does not determine
whether natural-language evidence semantically entails a claim.

| Method | Signature | Description |
|--------|-----------|-------------|
| `validate_belief_commit` | `(belief_payload: Dict, percepts: Dict, context: ValidationContext) -> ValidationResult` | Checks existence, staleness, and conflicts on dependent percepts |

Codes: `OK`, `MISSING_EVIDENCE`, `STALE_EVIDENCE`, `CONFLICTING_EVIDENCE`

### `ActionValidator`

`alethic.validators.ActionValidator` — Structural protocol for a synchronous
action-commitment gate. Implementations live outside the kernel;
`validator_id` is recorded in the validation evidence for every decision the
chain contributes to.

```python
class ActionValidator(Protocol):
    validator_id: str

    def validate_action(
        self,
        action: Dict[str, Any],
        committed_beliefs: Dict[str, Any],
        constraints: Dict[str, Any],
        context: ValidationContext,
    ) -> ValidationResult: ...
```

Unlike the belief chain, every configured `ActionValidator` runs even after
an earlier one fails — see [`decide_action()`](https://github.com/emiluzelac/alethic/blob/main/docs/api-reference.md#decide_action).

### `SymbolicValidator`

`alethic.validators.SymbolicValidator` — Checks whether actions satisfy beliefs and constraints. The default first member of `action_validators`.

| Method | Signature | Description |
|--------|-----------|-------------|
| `validate_action` | `(action: Dict, committed_beliefs: Dict, constraints: Dict, context: ValidationContext) -> ValidationResult` | Checks belief requirements and constraint blocks |

Codes: `OK`, `NO_COMMITTED_BELIEF`, `BELIEF_NOT_SATISFIED`, `{CONSTRAINT}_BLOCKED`

### `ActionDecision`

`alethic.decision.ActionDecision` — The outcome of running an action proposal
past every gate in the `action_validators` chain. Returned by
[`decide_action()`](https://github.com/emiluzelac/alethic/blob/main/docs/api-reference.md#decide_action); `commit_action_from_proposal()` reduces
it to `(ok, code)`.

```python
@dataclass(frozen=True)
class ActionDecision:
    ok: bool
    code: str
    results: Tuple[ValidationResult, ...] = ()
    reasons: Tuple[str, ...] = ()
    concerns: Tuple[str, ...] = ()
    severity: Literal["block", "review"] = "block"
```

| Field | Type | Description |
|-------|------|-------------|
| `ok` | `bool` | Whether the action committed |
| `code` | `str` | `"COMMITTED"`; `"VALIDATOR_ERROR"` if a validator raised or returned garbage (the chain stops there, even if an earlier gate already failed); otherwise the first failing validator's own code |
| `results` | `Tuple[ValidationResult, ...]` | One result per configured validator, in chain order |
| `reasons` | `Tuple[str, ...]` | `detail` of every failing gate — why it was refused |
| `concerns` | `Tuple[str, ...]` | `detail` of every passing gate with `marginal=True` |
| `severity` | `Literal["block", "review"]` | `"review"` if any failing gate asked for a person, otherwise `"block"` |

---

## Permissions

### `Role`

```python
Role = Literal["kernel", "tool", "planner", "symbolic_validator", "evidence_validator", "sim_validator"]
```

### `PERMISSIONS`

`alethic.permissions.PERMISSIONS` — Maps each role to its allowed slot+mode combinations.

| Role | percepts | beliefs | constraints | plans | evidence | predictions | actions |
|------|----------|---------|-------------|-------|----------|-------------|---------|
| tool | COMMIT | — | — | — | — | — | — |
| planner | — | PROPOSE | — | PROPOSE | — | PROPOSE | PROPOSE |
| symbolic_validator | — | — | COMMIT | — | — | — | — |
| evidence_validator | — | — | — | — | COMMIT | — | — |
| sim_validator | — | — | — | — | COMMIT | COMMIT | — |
| kernel | — | COMMIT | — | — | — | COMMIT | COMMIT |

---

## Session

`alethic.session.Session` — Groups multiple episodes under a single persistent context.

```python
@dataclass
class Session:
    session_id: str          # Auto-generated 12-char hex
    metadata: Dict[str, Any] # Arbitrary session metadata
```

| Method | Signature | Description |
|--------|-----------|-------------|
| `episode_trace_id` | `() -> str` | Generate unique trace_id: `"{session_id}-ep{n}-{random}"` |

---

## `alethic.testing`

Public conformance suite for `StoreProtocol` implementations, ships as
`alethic/testing.py`. A third-party backend author has no other way to prove
their store honours the subtle parts of the contract: lazy TTL expiry,
walking candidates past an expired one rather than judging only the oldest,
and re-entrant transactions. `MemoryStore` and `SqliteStore` once diverged on
exactly this — `MemoryStore` silently overwrote a record that `SqliteStore`
refused — which is why this suite exists.

### `store_conformance()`

```python
store_conformance(store_factory: Callable[[], StoreProtocol]) -> None
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `store_factory` | `Callable[[], StoreProtocol]` | Called (possibly more than once) to produce a fresh, empty store instance |

Raises `AssertionError` on the first contract violation, naming what failed.
Raises nothing if the store agrees with the shipped stores on every checked
behaviour. Closes every store instance it creates, including on failure.

```python
from alethic.testing import store_conformance

store_conformance(lambda: MyStore(...))
```
