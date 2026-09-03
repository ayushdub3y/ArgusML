"""Test suite for ExposureStore compound key and rolling window tracking (§4, §6b)."""

import pytest
from src.exposure_store import ExposureStore


def test_exposure_store_compound_key(tmp_path):
    """Verify exposure tracking uses the compound key of vpa_hash + device_fingerprint_hash."""
    db_path = str(tmp_path / "exposure.db")
    store = ExposureStore(db_path=db_path, window_days=30)

    vpa1 = "vpa_abc"
    dev1 = "dev_123"
    dev2 = "dev_456"

    now = 1735600000

    # Record 1 accept for vpa1 on dev1
    store.record_accept(vpa1, dev1, amount=10000, timestamp=now)

    # vpa1 + dev1 should have count=1, value=10000
    cnt, val = store.get_exposure(vpa1, dev1, now_ts=now)
    assert cnt == 1
    assert val == 10000

    # vpa1 + dev2 (different device) should be separate compound identity
    cnt2, val2 = store.get_exposure(vpa1, dev2, now_ts=now)
    assert cnt2 == 0
    assert val2 == 0


def test_exposure_store_multiple_accepts_accumulation(tmp_path):
    """Verify multiple accepts accumulate both count and value correctly."""
    db_path = str(tmp_path / "exposure_accum.db")
    store = ExposureStore(db_path=db_path, window_days=30)

    vpa = "vpa_multi"
    dev = "dev_multi"
    now = 1735600000

    store.record_accept(vpa, dev, amount=15000, timestamp=now - 2000)
    store.record_accept(vpa, dev, amount=25000, timestamp=now - 1000)
    store.record_accept(vpa, dev, amount=10000, timestamp=now)

    cnt, val = store.get_exposure(vpa, dev, now_ts=now)
    assert cnt == 3
    assert val == 50000


def test_exposure_store_rolling_window_expiry(tmp_path):
    """Verify events outside the 30-day window expire from rolling exposure."""
    db_path = str(tmp_path / "exposure_expiry.db")
    store = ExposureStore(db_path=db_path, window_days=30)

    now = 1735600000
    vpa = "vpa_test"
    dev = "dev_test"

    # Old event: 35 days ago (outside 30-day window)
    old_ts = now - (35 * 86400)
    store.record_accept(vpa, dev, amount=50000, timestamp=old_ts)

    # Recent event: 5 days ago
    recent_ts = now - (5 * 86400)
    store.record_accept(vpa, dev, amount=20000, timestamp=recent_ts)

    cnt, val = store.get_exposure(vpa, dev, now_ts=now)
    # Only recent event should count
    assert cnt == 1
    assert val == 20000


def test_exposure_store_clear(tmp_path):
    """Verify clear() removes all tracking data."""
    db_path = str(tmp_path / "exposure_clr.db")
    store = ExposureStore(db_path=db_path)
    store.record_accept("v", "d", 10000)
    assert store.get_exposure("v", "d")[0] == 1
    store.clear()
    assert store.get_exposure("v", "d")[0] == 0
