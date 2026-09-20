# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0] - 2026-08-07

### Added

- Added the typed `BeliefValidator` protocol and the ordered
  `Kernel(..., belief_validators=[...])` validation chain.
- Added fail-closed `VALIDATOR_ERROR` handling for validator exceptions and
  malformed return values.
- Added per-validator result codes, details, and context to successful and
  rejected belief-validation evidence artifacts.
- Exported `BeliefValidator` and `ValidationResult` from the public `alethic`
  namespace.
- Added `ValidationContext` (`store`, `trace_id`, `now_ms`), passed to every
  belief and action validator so a rule can consult history or the clock —
  the case a cooldown or a freshness check needs and could not express
  before. Exported from `alethic`.
- Added the typed `ActionValidator` protocol and the ordered
  `Kernel(..., action_validators=[...])` validation chain, mirroring
  `belief_validators`. `SymbolicValidator` is the default first member.
  Exported from `alethic`.
- Added `Kernel.decide_action()`, which runs the *whole* action-validator
  chain to completion and returns an `ActionDecision` carrying every
  validator's `ValidationResult`, every failing gate's reason in `reasons`,
  every passing-but-`marginal` gate's detail in `concerns`, and an overall
  `severity`. Exported `ActionDecision` from `alethic`.
- Added `alethic.testing.store_conformance()`, a public conformance suite for
  `StoreProtocol` implementations. It asserts the subtle parts of the
  contract — append-only ids, insertion-ordered `list_slot`, walking past an
  expired candidate in `find_active_by_kind` rather than judging only the
  oldest, and re-entrant `transaction()` — the exact place `MemoryStore` and
  `SqliteStore` once silently disagreed. Ships as `alethic/testing.py`.

### Fixed

- `SqliteStore.list_slot()` now orders by `rowid`, making the append order
  `StoreProtocol` publishes a guarantee rather than a planner decision. Both
  `idx_slot` and `idx_slot_kind_trace` can serve `WHERE slot=?` and the two
  return rows in different orders, so which COMMIT superseded which in
  `Kernel.current_view()` depended on which index SQLite happened to pick.
  `list_persistent()` and `list_by_status()` are ordered the same way, for
  the same reason: an append-only audit trail read back in an arbitrary order
  is not an audit trail.
- Action validation evidence is now written under the record kind
  `validation_action_{kind}` rather than `validation_{kind}`. Both chains
  wrote the latter, and `current_view()` keys the evidence slot by kind, so a
  belief and an action sharing a name produced two artifacts under one key
  and the action's shadowed the belief's. Both always survived in
  `list_slot("evidence")`; only the view was lossy. Code that reads action
  validation evidence out of `current_view()` by key must use the new name.
- `alethic.testing.store_conformance()`'s append-order check now uses records
  of differing `kind`. It previously appended three records sharing one kind,
  the single shape where kind order and append order agree, so it asserted a
  contract it could not fail a store for breaking.

### Changed

- Validators are now handed deep copies of the payload and the percept,
  belief, and constraint views, one set per validator, instead of the
  kernel's live objects. A validator that mutated an argument previously
  changed what was committed — the audit trail recorded the mutated payload
  as if it had been proposed — and could disarm gates that run after the
  chain, such as emptying `depends_on` so the percept-confidence gate had
  nothing to check. It also means no gate can rewrite what a later gate in
  the same chain judges. A validator returns a verdict; that is all it can
  change. No migration needed unless a validator relied on mutating its
  arguments, which was never supported.
- **Breaking:** `BeliefValidator.validate_belief_commit()` now takes a third
  positional argument, `context: ValidationContext`. Migration: add the
  parameter to every custom validator's method signature; the kernel now
  always passes it.
- **Breaking:** `ActionValidator.validate_action()` (formerly documented
  informally as `SymbolicValidator`'s shape) now takes a fourth positional
  argument, `context: ValidationContext`. Migration: add the parameter to
  every custom validator's method signature.
- `ValidationResult` gained two fields, `marginal: bool = False` and
  `severity: Literal["block", "review"] = "block"`. Both are defaulted, so
  existing `ValidationResult(...)` construction is unaffected. `severity` is
  only meaningful when `ok=False`; `"review"` means the gate refuses but
  wants a person to decide rather than a hard stop. `marginal=True` on a
  passing result surfaces its detail as a `concern` even though the gate let
  the proposal through.
- `Kernel.commit_action_from_proposal()` is now a thin wrapper over
  `decide_action()` — `ok, code = decide_action(...).ok, decide_action(...).code`
  — kept only for the existing two-tuple call sites. No migration needed;
  its signature and return type are unchanged.
- `EvidenceValidator` is now the default first member of the belief-validator
  chain and identifies itself as `structural_evidence`.
- The existing `kernel.evidence_validator` attribute remains a compatibility
  property that replaces only the first validator in the configured chain.
  `kernel.symbolic_validator` is the equivalent compatibility property for
  the action-validator chain, added alongside `action_validators`.

### Why the action chain runs to completion and the belief chain does not

`commit_belief_from_proposal()` still stops at the first validator that
rejects. `decide_action()` deliberately does not: it runs every configured
`ActionValidator` and reports all of it. A belief is a truth claim — the
first disqualifying reason is enough to settle whether it may enter state,
and running further checks against evidence that has already failed adds
nothing. An action decision is different: it is handed to a person (directly,
or through `severity="review"`), and that person needs every reason the
action was refused and every gate that passed only narrowly, not just
whichever gate happened to run first. This asymmetry is intentional and is
not expected to converge — do not "fix" one chain to match the other.

## [0.3.0] - 2026-07-18

### Changed

- Renamed the sole public Python namespace from `alethic_kernel` to `alethic`.
- Mapped the repository's `src/` directory directly to the installed `alethic`
  package, eliminating the repeated source-directory name without adding a
  compatibility copy.
- Reduced the distribution to the domain-neutral governed cognitive substrate.
  Benchmark agents, Stripe tasks, LLM prompts, the evaluation harness, and the
  development HTTP service are no longer shipped in the Alethic wheel.
- Moved canonical repository metadata to `emiluzelac/alethic`.

### Removed

- Removed the `alethic_kernel` compatibility namespace. Import from `alethic`.
- Removed the benchmark CLI and application-server extras from the runtime
  distribution.

## [0.2.0] - 2026-07-18

### Changed

- Flattened the public Python namespace from `alethic_kernel.alethic` to
  `alethic_kernel`.
- Moved the installable package into the conventional `src/alethic_kernel`
  layout.
- Renamed the source repository to `alethicdev/alethic-kernel` so the GitHub,
  PyPI, and Python package names describe the same artifact.

## [0.1.0] - 2026-07-16

### Added

- **Blackboard Kernel** — Core governed cognition substrate with 7 semantic slots (percepts, beliefs, constraints, plans, evidence, predictions, actions)
- **PROPOSE/COMMIT Protocol** — Two-phase validation ensuring all decisions pass evidence quality checks before commitment
- **Validation Pipelines**
  - Evidence validation (staleness, missing percepts, conflict detection)
  - Confidence thresholds (0.5 default minimum confidence)
  - Conflict arbitration (high-confidence sources override conflicts)
  - Constraint-based action gating
  - Prediction-gated actions (optional forward validation)
- **Role-Based Access Control** — 6 roles with explicit permission model (tool, planner, symbolic_validator, evidence_validator, sim_validator, kernel)
- **Store Abstraction**
  - `MemoryStore` — Thread-safe in-memory store (default)
  - `SqliteStore` — WAL-mode SQLite with persistent records and indexed queries
- **Worker Protocol** — Extensible worker framework for cognitive components
  - `SimulatorWorker` — Rule-based forward simulator with declarative conditions
  - `AdaptiveWorker` — Learns constraints from failure patterns across episodes
  - `Orchestrator` — Generic round-robin scheduler with dependency ordering
- **Four Reference Agents**
  - `StringGlue` — Baseline (always acts, no validation)
  - `JsonGlue` — Confidence tracking but no validation
  - `AlethicAgent` — Full kernel with deterministic planner
  - `LLMAgent` — Full kernel with LLM-based planner (OpenAI-compatible)
- **Evaluation Framework**
  - Task loader for YAML/JSON task definitions
  - Benchmark harness (1,200 episodes: 6 tasks × 50 seeds × 4 agents)
  - 5 metrics: task success, unsafe actions, unsupported beliefs, traceability, evidence taint
  - Perturbation system (staleness, conflicts, low confidence, tool failures)
  - Markdown report generation
- **Example Domain: Stripe Refunds**
  - 6 refund tasks exercising different failure modes
  - Constraints: no duplicate refunds, no partial refunds without evidence
  - Perturbation scenarios validating governance under adversarial conditions
- **HTTP API**
  - FastAPI server with `/v1/write`, `/v1/commit/*`, `/v1/validate/*` endpoints
  - OpenTelemetry support for distributed tracing
  - OpenAPI documentation at `/docs`
  - Docker and docker-compose deployment
- **Comprehensive Documentation**
  - Architecture guide with semantic slots and validation pipelines
  - API reference for all public classes and methods
  - Worker protocol and custom worker examples
  - HTTP API specification
  - Benchmark methodology and CLI reference
  - Deployment guide with store selection and environment variables
- **Type Safety** — Strict mypy configuration across all modules
- **Test Suite** — 349 unit and integration tests with pytest

### Benchmark Results

In a controlled evaluation of 1,200 episodes:

| Agent | Task Success | Unsafe Actions | Unsupported Beliefs | Traceability |
|-------|-------------|----------------|---------------------|--------------|
| StringGlue | 61.3% | 38.7% | 26.0% | 0.10 |
| JsonGlue | 57.0% | 43.0% | 31.0% | 0.30 |
| **Alethic** | **100%** | **0%** | **0%** | **1.00** |
| **LLM+Alethic** | **99.0%** | **0%** | **0%** | **1.00** |

- Kernel-backed agents achieve zero unsafe actions across all perturbation scenarios
- Baseline agents produce unsafe actions 39-43% of the time on stale/conflicting/low-confidence data
- LLM agent demonstrates that governance generalizes regardless of planner implementation

### Known Limitations

- Example domain currently limited to Stripe refund tasks (kernel itself is domain-agnostic)
- LLM planner sometimes declines to act conservatively, reducing task success vs. deterministic agent
- Local LLM inference requires OpenAI-compatible endpoint (defaults to Ollama on localhost:11434)

### Paper & Attribution

Alethic is the reference implementation of [From Fragile Glue to Governed Cognition](https://doi.org/10.5281/zenodo.18691808), a controlled study of blackboard kernels for modular AI systems.
