# Alethic

**A governed cognitive substrate for AI systems.**

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.18691808.svg)](https://doi.org/10.5281/zenodo.18691808)

Models propose. Alethic decides what may enter state and what may become action.

Alethic places a small, enforceable kernel between reasoning components and
external effects. It maintains typed state, links beliefs to evidence, applies
declarative constraints, and records why each proposal was committed or
invalidated. The kernel contains no model, prompt, tool, task, or domain logic.

## Install

The Python distribution is named `alethic-kernel`; its single import namespace
is `alethic`.

```bash
pip install alethic-kernel
```

## Use

```python
from alethic import Kernel

kernel = Kernel()
trace = "episode-001"

kernel.write(
    "tool",
    "percepts",
    "COMMIT",
    "observation",
    {"value": 42, "stale": False, "conflict": False},
    trace,
    confidence=0.9,
)

proposal = kernel.write(
    "planner",
    "beliefs",
    "PROPOSE",
    "threshold_reached",
    {"value": True, "depends_on": ["observation"]},
    trace,
    input_refs=["observation"],
)

committed, reason = kernel.commit_belief_from_proposal(proposal.id, trace)
print(committed, reason)
```

### Pluggable belief validation

The default `EvidenceValidator` checks that dependent percepts exist and are
not stale or conflicted. Applications may add stricter synchronous validators
without adding a model or domain dependency to Alethic itself:

```python
from typing import Any

from alethic import EvidenceValidator, Kernel, ValidationResult


class EntailmentValidator:
    validator_id = "semantic_entailment"

    def validate_belief_commit(
        self,
        belief_payload: dict[str, Any],
        percepts: dict[str, Any],
    ) -> ValidationResult:
        # Call a deterministic, NLI, retrieval, or domain-specific verifier.
        entailed = verify_claim(belief_payload, percepts)
        if not entailed:
            return ValidationResult(
                False,
                "INSUFFICIENT_EVIDENCE",
                "The cited evidence does not entail the proposed belief",
            )
        return ValidationResult(True, "ENTAILED", "The claim is supported")


kernel = Kernel(
    belief_validators=[EvidenceValidator(), EntailmentValidator()],
)
```

Validators run in order and short-circuit on the first rejection. Exceptions
and invalid return values fail closed as `VALIDATOR_ERROR`. Successful and
rejected results are recorded in validation evidence artifacts.

Every worker can propose. Only the kernel can commit. State lives in seven
semantic slots: percepts, beliefs, constraints, plans, evidence, predictions,
and actions.

### Writing a store

Any object satisfying
[`StoreProtocol`](https://github.com/emiluzelac/alethic/blob/main/docs/architecture.md#store-abstraction)
can back the kernel in place of `MemoryStore` or `SqliteStore`. The subtle
parts of that contract — lazy TTL expiry, walking candidates past an expired
one instead of judging only the oldest, and re-entrant transactions — are
exactly where a third backend can quietly diverge from the two that ship.
`alethic.testing.store_conformance` runs the same checks the shipped stores
are held to, against a factory for your store:

```python
from alethic.testing import store_conformance

store_conformance(lambda: MyStore(...))
```

It raises `AssertionError` on the first violation, naming what failed. See
[`src/testing.py`](https://github.com/emiluzelac/alethic/blob/main/src/testing.py)
for the full list of assertions.

## What belongs here

This repository contains only the domain-neutral Alethic substrate:

- the governed blackboard kernel and typed record schema;
- evidence, confidence, conflict, constraint, and prediction validation;
- in-memory and SQLite stores;
- worker orchestration, sessions, simulation, and adaptive constraints;
- tests, architectural documentation, and a domain-neutral example.

The controlled study, results, and verification artifacts live separately in
[governed-cognition](https://github.com/emiluzelac/governed-cognition).

## Documentation

- [Architecture](docs/architecture.md)
- [API reference](docs/api-reference.md)
- [Workers](docs/workers.md)
- [Research paper](https://doi.org/10.5281/zenodo.18691808)

## Source layout

The repository name is Alethic exactly once. Setuptools maps `src/` directly to
the installed `alethic` namespace.

```text
src/
  __init__.py
  kernel.py
  schema.py
  permissions.py
  validators.py
  store.py
  sqlite_store.py
  worker.py
  orchestrator.py
  session.py
  sim_worker.py
  adaptive_worker.py
```

## Development

```bash
python -m pip install -e ".[dev]"
pytest
mypy --strict src
```

## License

MIT © Emil Uzelac
