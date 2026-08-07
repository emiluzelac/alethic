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
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `min_confidence` | `float` | `0.5` | Minimum confidence on dependent percepts for belief commitment |
| `conflict_confidence_threshold` | `float` | `0.7` | Confidence threshold above which conflicts are arbitrated |
| `store` | `Optional[StoreProtocol]` | `None` | Backing store; defaults to `MemoryStore()` if not provided |
| `belief_validators` | `Optional[Sequence[BeliefValidator]]` | `None` | Ordered fail-closed chain; defaults to one `EvidenceValidator()` |

`belief_validators` must be non-empty and validator IDs must be unique. The
kernel copies the sequence into an immutable tuple. The
`kernel.evidence_validator` compatibility property gets or replaces the first
validator without removing the rest of the chain.

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
confidence checks, and conflict arbitration. The first validator rejection
short-circuits the chain and its code is returned unchanged.

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

#### `commit_action_from_proposal()`

```python
commit_action_from_proposal(
    proposal_id: str,
    trace_id: str,
    require_prediction: bool = False,
) -> Tuple[bool, str]
```

Validate and commit an action proposal. Optionally gates on predictions.

| Parameter | Type | Description |
|-----------|------|-------------|
| `require_prediction` | `bool` | If `True`, requires a committed prediction with non-negative `expected_outcome` |

| Return | Description |
|--------|-------------|
| `(True, "COMMITTED")` | Action committed successfully |
| `(False, "INVALID_ACTION_PROPOSAL")` | Proposal not found, inactive, wrong slot, or wrong mode |
| `(False, "NO_PREDICTION")` | `require_prediction=True` but no matching prediction found |
| `(False, "NEGATIVE_PREDICTION")` | Matching prediction has negative `expected_outcome` |
| `(False, "NO_COMMITTED_BELIEF")` | A required belief is not committed |
| `(False, "BELIEF_NOT_SATISFIED")` | A required belief is committed but falsy |
| `(False, "{CONSTRAINT}_BLOCKED")` | A constraint blocks the action |

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
| `list_slot` | `(slot: Slot) -> List[Record]` | All records in a slot (checks TTL) |
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
| `list_by_status` | `(status: str) -> List[Record]` | All records with given status |
| `list_persistent` | `(slot: Optional[str] = None) -> List[Record]` | All persistent-scope records |
| `count_invalidated_by_reason` | `() -> Dict[str, int]` | `{reason: count}` for invalidated records |
| `close` | `() -> None` | Close the database connection |

---

## Validators

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
```

### `EvidenceValidator`

`alethic.validators.EvidenceValidator` — The default structural validator. It
checks the presence and condition of cited percepts; it does not determine
whether natural-language evidence semantically entails a claim.

| Method | Signature | Description |
|--------|-----------|-------------|
| `validate_belief_commit` | `(belief_payload: Dict, percepts: Dict) -> ValidationResult` | Checks existence, staleness, and conflicts on dependent percepts |

Codes: `OK`, `MISSING_EVIDENCE`, `STALE_EVIDENCE`, `CONFLICTING_EVIDENCE`

### `SymbolicValidator`

`alethic.validators.SymbolicValidator` — Checks whether actions satisfy beliefs and constraints.

| Method | Signature | Description |
|--------|-----------|-------------|
| `validate_action` | `(action: Dict, committed_beliefs: Dict, constraints: Dict) -> ValidationResult` | Checks belief requirements and constraint blocks |

Codes: `OK`, `NO_COMMITTED_BELIEF`, `BELIEF_NOT_SATISFIED`, `{CONSTRAINT}_BLOCKED`

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
