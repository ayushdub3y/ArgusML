"""Test suite for DecisionEngine (§6, §6b).

Verifies that:
1. EV values strictly match the documented §6 formulas.
2. The §6b velocity/cumulative-exposure gate strictly runs BEFORE the EV rule's accept branch.
3. Decision boundary invariants hold across all branches.
"""

import pytest
from src.decision_engine import (
    decide,
    CONTEST_P_THRESHOLD,
    ACCEPT_P_THRESHOLD,
    DEFAULT_C_CONTEST,
    DEFAULT_C_PENALTY,
    VELOCITY_MAX_COUNT,
    VELOCITY_MAX_VALUE,
)


def test_ev_values_match_the_documented_formula():
    """Verify EV_accept and EV_contest exactly match §6 mathematical specifications.

    EV_accept  = -V
    EV_contest = -(1 - p)(V + C_penalty) - C_contest
    Net contest advantage = EV_contest - EV_accept = p·V - (1 - p)·C_penalty - C_contest
    """
    v = 200000.0  # ₹2,000 in paise
    p = 0.80
    c_penalty = 15000.0  # ₹150
    c_contest = 3000.0   # ₹30

    expected_ev_accept = -v
    expected_ev_contest = -(1.0 - p) * (v + c_penalty) - c_contest
    expected_net_advantage = p * v - (1.0 - p) * c_penalty - c_contest

    action, rule, meta = decide(
        p_illegitimate=p,
        amount_paise=int(v),
        exposure_count=0,
        exposure_value_paise=0,
        c_penalty=int(c_penalty),
        c_contest=int(c_contest),
    )

    assert meta["ev_accept"] == expected_ev_accept
    assert meta["ev_contest"] == pytest.approx(expected_ev_contest, rel=1e-5)
    assert meta["net_contest_advantage"] == pytest.approx(expected_net_advantage, rel=1e-5)
    assert action == "contest"
    assert rule == "ev_positive_high_confidence"


def test_ev_values_negative_advantage_routing():
    """Verify negative EV advantage routes away from auto-contest."""
    v = 20000.0  # ₹200
    p = 0.10
    c_penalty = 15000.0
    c_contest = 3000.0

    # Net advantage = 0.10 * 20000 - 0.90 * 15000 - 3000 = 2000 - 13500 - 3000 = -14500 < 0
    action, rule, meta = decide(
        p_illegitimate=p,
        amount_paise=int(v),
        exposure_count=0,
        exposure_value_paise=0,
        c_penalty=int(c_penalty),
        c_contest=int(c_contest),
    )
    assert meta["net_contest_advantage"] < 0
    assert action == "accept"
    assert rule == "low_p_auto_accept"


def test_velocity_gate_runs_before_ev_accept_branch():
    """Non-negotiable §6b invariant: velocity gate must evaluate BEFORE the accept branch.

    Even if p is near 0 and V is tiny (a clear EV accept candidate),
    exceeding either count or cumulative value MUST divert to escalate (queue K).
    """
    # Baseline candidate: p = 0.02, V = ₹100 -> definitely an auto-accept candidate
    p_low = 0.02
    v_tiny = 10000

    # 1. Clean exposure -> accepts
    act_clean, rule_clean, _ = decide(p_low, v_tiny, exposure_count=0, exposure_value_paise=0)
    assert act_clean == "accept"

    # 2. Count limit breached (count >= 3) -> MUST escalate, NOT accept
    act_cnt, rule_cnt, meta_cnt = decide(p_low, v_tiny, exposure_count=VELOCITY_MAX_COUNT, exposure_value_paise=0)
    assert act_cnt == "escalate"
    assert rule_cnt == "velocity_cap_breached"
    assert meta_cnt["velocity_breached"] is True

    # 3. Value limit breached (value >= ₹5,000) -> MUST escalate, NOT accept
    act_val, rule_val, meta_val = decide(p_low, v_tiny, exposure_count=1, exposure_value_paise=VELOCITY_MAX_VALUE)
    assert act_val == "escalate"
    assert rule_val == "velocity_cap_breached"
    assert meta_val["velocity_breached"] is True

    # 4. Both breached -> MUST escalate
    act_both, rule_both, meta_both = decide(p_low, v_tiny, exposure_count=VELOCITY_MAX_COUNT + 1, exposure_value_paise=VELOCITY_MAX_VALUE + 5000)
    assert act_both == "escalate"
    assert rule_both == "velocity_cap_breached"


def test_mid_p_and_uncertain_confidence_escalation():
    """Verify that mid-p disputes (e.g. p=0.45) or high-V disputes that fail confidence threshold escalate."""
    # p = 0.50 is between ACCEPT_P_THRESHOLD (0.25) and CONTEST_P_THRESHOLD (0.65)
    action, rule, meta = decide(
        p_illegitimate=0.50,
        amount_paise=80000,
        exposure_count=0,
        exposure_value_paise=0,
    )
    assert action == "escalate"
    assert rule == "uncertain_ev_or_mid_p"


def test_high_amount_insufficient_p_confidence_escalation():
    """Verify high amount with positive net advantage but p below contest threshold escalates."""
    # Large V makes net advantage positive even with p = 0.55, but p < CONTEST_P_THRESHOLD (0.65)
    action, rule, meta = decide(
        p_illegitimate=0.60,
        amount_paise=1500000,  # ₹15,000
        exposure_count=0,
        exposure_value_paise=0,
    )
    assert action == "escalate"
    assert rule == "uncertain_ev_or_mid_p"
