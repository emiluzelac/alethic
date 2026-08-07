"""Regression tests for the public package namespace."""

from __future__ import annotations

import importlib.util
from typing import get_args

from alethic import BeliefValidator, Kernel, Slot, ValidationResult, __version__


def test_primary_api_is_available_at_the_package_root() -> None:
    assert Kernel.__module__ == "alethic.kernel"
    assert "percepts" in get_args(Slot)
    assert BeliefValidator.__module__ == "alethic.validators"
    assert ValidationResult.__module__ == "alethic.validators"


def test_no_compatibility_namespace_is_shipped() -> None:
    assert importlib.util.find_spec("alethic_kernel") is None


def test_package_reports_the_release_version() -> None:
    assert __version__ == "0.4.0"
