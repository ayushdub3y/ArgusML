"""Test suite for EscalationQueue (§2 node K, Task 4)."""

import pytest
from src.human_review.escalation_queue import EscalationQueue


@pytest.fixture
def queue(tmp_path):
    """Provide an isolated EscalationQueue backed by temporary SQLite DB."""
    db_path = str(tmp_path / "test_escalations.db")
    return EscalationQueue(db_path=db_path)


def test_escalation_queue_add_get_pop(queue):
    """Verify add, get, and pop operations."""
    item = {"dispute_id": "disp_001", "respond_by": 1735600000, "amount": 50000}
    queue.add(item)

    # get without removing
    retrieved = queue.get("disp_001")
    assert retrieved == item
    assert queue.get("non_existent") is None

    # pop removes from queue
    popped = queue.pop("disp_001")
    assert popped == item
    assert queue.get("disp_001") is None
    assert queue.pop("disp_001") is None


def test_escalation_queue_all_pending_sorting(queue):
    """Verify all_pending() sorts by respond_by ascending."""
    queue.add({"dispute_id": "disp_late", "respond_by": 1735700000})
    queue.add({"dispute_id": "disp_early", "respond_by": 1735500000})
    queue.add({"dispute_id": "disp_mid", "respond_by": 1735600000})

    pending = queue.all_pending()
    assert len(pending) == 3
    assert [p["dispute_id"] for p in pending] == ["disp_early", "disp_mid", "disp_late"]


def test_escalation_queue_seconds_remaining(queue):
    """Verify seconds_remaining() never returns a negative number."""
    now_ts = 1735600000
    queue.add({"dispute_id": "disp_future", "respond_by": now_ts + 120})
    queue.add({"dispute_id": "disp_expired", "respond_by": now_ts - 500})

    assert queue.seconds_remaining("disp_future", now_ts=now_ts) == 120
    # Overdue deadline must clamp to 0, never negative
    assert queue.seconds_remaining("disp_expired", now_ts=now_ts) == 0

    with pytest.raises(KeyError):
        queue.seconds_remaining("unknown_dispute", now_ts=now_ts)


def test_escalation_queue_persistence_across_restart(tmp_path):
    """Verify items in EscalationQueue survive simulated process restart."""
    db_path = str(tmp_path / "restart_escalations.db")
    q1 = EscalationQueue(db_path=db_path)
    item = {"dispute_id": "disp_persist_01", "respond_by": 1735690000, "amount": 35000}
    q1.add(item)

    # Simulated restart: instantiate fresh instance against same db file
    q2 = EscalationQueue(db_path=db_path)
    assert q2.get("disp_persist_01") == item
    pending = q2.all_pending()
    assert len(pending) == 1
    assert pending[0]["dispute_id"] == "disp_persist_01"
