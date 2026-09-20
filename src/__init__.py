"""Alethic's public Python API."""

from importlib.metadata import PackageNotFoundError, version as _version

from .kernel import Kernel
from .schema import Provenance, Record, RecordIdConflict, Slot, WriteMode
from .store import MemoryStore
from .store_protocol import StoreProtocol
from .sqlite_store import SqliteStore
from .permissions import PERMISSIONS, Role
from .validators import BeliefValidator, EvidenceValidator, SymbolicValidator, ValidationResult
from .worker import Worker, BaseWorker
from .orchestrator import Orchestrator, OrchestratorResult
from .session import Session
from .sim_worker import SimulatorWorker, SimRule, evaluate_rule
from .adaptive_worker import AdaptiveWorker

try:
    __version__ = _version("alethic-kernel")
except PackageNotFoundError:  # running from a source tree, not installed
    __version__ = "0.0.0.dev0"

__all__ = [
    "AdaptiveWorker",
    "BaseWorker",
    "BeliefValidator",
    "EvidenceValidator",
    "Kernel",
    "MemoryStore",
    "Orchestrator",
    "OrchestratorResult",
    "PERMISSIONS",
    "Provenance",
    "Record",
    "RecordIdConflict",
    "Role",
    "Session",
    "SimRule",
    "SimulatorWorker",
    "Slot",
    "SqliteStore",
    "StoreProtocol",
    "SymbolicValidator",
    "ValidationResult",
    "Worker",
    "WriteMode",
    "__version__",
    "evaluate_rule",
]
