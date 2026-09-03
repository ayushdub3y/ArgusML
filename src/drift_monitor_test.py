"""Test suite for DriftMonitor (§10 P2 stretch)."""

import pytest
from src.drift_monitor import DriftMonitor


def test_drift_monitor_insufficient_data():
    """Verify monitor reports insufficient_data when window has fewer than 10 points."""
    monitor = DriftMonitor(baseline_scores=[0.5] * 50)
    for _ in range(5):
        monitor.record_prediction(0.5)

    status = monitor.check_drift()
    assert status["drift_detected"] is False
    assert status["status"] == "insufficient_data"


def test_drift_monitor_stable_distribution():
    """Verify monitor detects no drift when incoming predictions match baseline distribution."""
    baseline = [0.48, 0.52, 0.50, 0.49, 0.51] * 20
    monitor = DriftMonitor(baseline_scores=baseline, drift_threshold=0.10)

    for p in [0.50, 0.51, 0.49, 0.50, 0.52] * 10:
        monitor.record_prediction(p)

    status = monitor.check_drift()
    assert status["drift_detected"] is False
    assert status["status"] == "stable"
    assert status["mean_shift"] < 0.10


def test_drift_monitor_detects_distribution_drift():
    """Verify monitor flags drift_warning when predictions shift significantly."""
    baseline = [0.20, 0.22, 0.18, 0.25, 0.21] * 20
    monitor = DriftMonitor(baseline_scores=baseline, drift_threshold=0.15)

    # Influx of high-risk scores shifting mean from ~0.20 to ~0.80
    for p in [0.80, 0.85, 0.78, 0.82, 0.88] * 10:
        monitor.record_prediction(p)

    status = monitor.check_drift()
    assert status["drift_detected"] is True
    assert status["status"] == "drift_warning"
    assert status["mean_shift"] > 0.15
