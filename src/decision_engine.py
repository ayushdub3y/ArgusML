"""Implements the §6 deterministic EV routing rule and the §6b velocity/cumulative-exposure gate that runs before its accept branch; the only module that sets accept/contest/escalate (§3)."""

from typing import Any, Dict, Tuple


# Economic defaults (paise) per §6
DEFAULT_C_PENALTY = 15000  # ₹150 penalty cost if contest lost
DEFAULT_C_CONTEST = 3000   # ₹30 marginal cost of submitting contest

# Thresholds
CONTEST_P_THRESHOLD = 0.65  # High confidence required for auto-contest
ACCEPT_P_THRESHOLD = 0.25   # Low probability of illegitimacy for auto-accept

# Velocity/cumulative-exposure thresholds per §6b
VELOCITY_MAX_COUNT = 3        # Max auto-accepts per window
VELOCITY_MAX_VALUE = 500000   # Max cumulative auto-accepted value: ₹5,000 (500,000 paise)


def decide(
    p_illegitimate: float,
    amount_paise: int,
    exposure_count: int = 0,
    exposure_value_paise: int = 0,
    c_penalty: int = DEFAULT_C_PENALTY,
    c_contest: int = DEFAULT_C_CONTEST,
    max_count: int = VELOCITY_MAX_COUNT,
    max_value: int = VELOCITY_MAX_VALUE,
) -> Tuple[str, str, Dict[str, Any]]:
    """Determine routing action: 'accept', 'contest', or 'escalate'.

    Invariants (§3, §6, §6b):
    - This function is the ONLY place in the system that decides accept/contest/escalate.
    - The §6b velocity gate runs BEFORE the EV rule's accept branch.

    Returns:
        Tuple of (action, rule_fired, metadata_dict)
        where action is strictly in {'accept', 'contest', 'escalate'}.
    """
    v = float(amount_paise)
    p = float(p_illegitimate)

    # Calculate expected values
    # EV_accept = -V
    # EV_contest = -(1 - p)(V + C_penalty) - C_contest
    # Net gain of contest vs accept = p*V - (1 - p)*C_penalty - C_contest
    net_contest_advantage = p * v - (1.0 - p) * float(c_penalty) - float(c_contest)
    ev_accept = -v
    ev_contest = -(1.0 - p) * (v + float(c_penalty)) - float(c_contest)

    metadata = {
        "p": p,
        "amount_paise": amount_paise,
        "exposure_count": exposure_count,
        "exposure_value_paise": exposure_value_paise,
        "net_contest_advantage": net_contest_advantage,
        "ev_accept": ev_accept,
        "ev_contest": ev_contest,
    }

    # 1. High confidence EV contest check
    if net_contest_advantage > 0 and p >= CONTEST_P_THRESHOLD:
        metadata["rule_fired"] = "ev_positive_high_confidence"
        return "contest", "ev_positive_high_confidence", metadata

    # 2. §6b Velocity Gate: MUST RUN BEFORE ANY ACCEPT BRANCH!
    # If the candidate dispute would otherwise qualify for accept (or is low-p),
    # but the identity has breached rolling velocity caps, route to human queue K.
    velocity_breached = (exposure_count >= max_count) or (exposure_value_paise >= max_value)
    if velocity_breached:
        metadata["rule_fired"] = "velocity_cap_breached"
        metadata["velocity_breached"] = True
        return "escalate", "velocity_cap_breached", metadata

    # 3. Low-p auto-accept branch (gated by velocity check above)
    if p <= ACCEPT_P_THRESHOLD and net_contest_advantage <= 0:
        metadata["rule_fired"] = "low_p_auto_accept"
        return "accept", "low_p_auto_accept", metadata

    # 4. Fallback to human escalation (mid-p, uncertain confidence, or high-V boundary)
    metadata["rule_fired"] = "uncertain_ev_or_mid_p"
    return "escalate", "uncertain_ev_or_mid_p", metadata
