"""Test suite for data/synthetic_generator.py verifying determinism and seed sensitivity (Task 1)."""

import pytest
from data.synthetic_generator import generate


def test_synthetic_generator_deterministic_same_seed():
    """generate(n=200, seed=42) called twice in the same process returns bit-identical records."""
    run1 = generate(n=200, seed=42)
    run2 = generate(n=200, seed=42)

    assert len(run1) == 200
    assert len(run2) == 200
    assert run1 == run2, "Repeated generation with identical seed must produce bit-identical records"


def test_synthetic_generator_seed_sensitivity():
    """generate(n=200, seed=1) and generate(n=200, seed=2) return different records."""
    run_seed1 = generate(n=200, seed=1)
    run_seed2 = generate(n=200, seed=2)

    assert len(run_seed1) == 200
    assert len(run_seed2) == 200
    assert run_seed1 != run_seed2, "Generations with different seeds must produce different records"
