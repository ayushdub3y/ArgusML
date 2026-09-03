"""Implements drift monitoring stub for Model A prediction distribution (§10 P2 stretch).

Tracks rolling window of predicted p_illegitimate scores and flags distribution drift
against baseline training distribution using Kolmogorov-Smirnov statistic or mean shift.
"""

from typing import Any, Dict, List, Optional
import numpy as np


class DriftMonitor:
    """Monitors model output distribution drift over time."""

    def __init__(
        self,
        baseline_scores: Optional[List[float]] = None,
        window_size: int = 200,
        drift_threshold: float = 0.15,
    ):
        self.baseline_scores = np.array(baseline_scores or [0.5] * 100, dtype=np.float32)
        self.baseline_mean = float(np.mean(self.baseline_scores))
        self.window_size = window_size
        self.drift_threshold = drift_threshold
        self._current_window: List[float] = []

    def record_prediction(self, p_illegitimate: float) -> None:
        """Record an incoming prediction score into the rolling window."""
        self._current_window.append(float(p_illegitimate))
        if len(self._current_window) > self.window_size:
            self._current_window.pop(0)

    def check_drift(self) -> Dict[str, Any]:
        """Check whether the current window exhibits statistical drift from baseline."""
        if len(self._current_window) < 10:
            return {
                "drift_detected": False,
                "status": "insufficient_data",
                "sample_count": len(self._current_window),
                "mean_shift": 0.0,
            }

        current_arr = np.array(self._current_window, dtype=np.float32)
        current_mean = float(np.mean(current_arr))
        mean_shift = abs(current_mean - self.baseline_mean)

        drift_detected = mean_shift > self.drift_threshold

        return {
            "drift_detected": drift_detected,
            "status": "drift_warning" if drift_detected else "stable",
            "baseline_mean": self.baseline_mean,
            "current_mean": current_mean,
            "mean_shift": round(mean_shift, 4),
            "threshold": self.drift_threshold,
            "sample_count": len(self._current_window),
        }

    def clear(self) -> None:
        """Clear current window."""
        self._current_window.clear()
