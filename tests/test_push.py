"""Tests for ``src/integrations/push.py``.

Focus on the parts that don't hit the network: subscription model parsing,
file-backed dedup, and removal semantics. End-to-end push delivery against
a real push service is left for manual smoke testing via /api/push/test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.integrations import push as push_mod
from src.integrations.push import (
    FileSubscriptionStore,
    PushSubscription,
    list_subscriptions,
    remove_subscription,
    upsert_subscription,
)


VALID_SUB = {
    "endpoint": "https://fcm.googleapis.com/fcm/send/abcdef12345",
    "keys": {
        "p256dh": "BNxKtPlT8w1iV2YwQ5h0iY7Vd7H5q4p4n3m5r6s7t8u9v0w1x2y3z4a5b6c7d8e9f0",
        "auth": "AbCdEfGhIjKlMnOpQr",
    },
}


# --- Model parsing ----------------------------------------------------------


def test_push_subscription_parses_browser_json() -> None:
    sub = PushSubscription.model_validate(VALID_SUB)
    assert sub.endpoint == VALID_SUB["endpoint"]
    assert sub.keys.p256dh == VALID_SUB["keys"]["p256dh"]
    assert sub.keys.auth == VALID_SUB["keys"]["auth"]
    # cache_key is the endpoint URL
    assert sub.cache_key() == VALID_SUB["endpoint"]


def test_push_subscription_accepts_label() -> None:
    sub = PushSubscription.model_validate({**VALID_SUB, "label": "my phone"})
    assert sub.label == "my phone"


def test_to_pywebpush_shape() -> None:
    sub = PushSubscription.model_validate(VALID_SUB)
    d = sub.to_pywebpush()
    assert set(d.keys()) == {"endpoint", "keys"}
    assert set(d["keys"].keys()) == {"p256dh", "auth"}


# --- FileSubscriptionStore --------------------------------------------------


def test_file_store_roundtrip(tmp_path: Path) -> None:
    store = FileSubscriptionStore(tmp_path / "subs.json")
    assert store.load() == []

    sub = PushSubscription.model_validate(VALID_SUB)
    store.save([sub])
    loaded = store.load()
    assert len(loaded) == 1
    assert loaded[0].endpoint == sub.endpoint


def test_file_store_skips_invalid_entries(tmp_path: Path) -> None:
    path = tmp_path / "subs.json"
    path.write_text('[{"endpoint": "x"}, ' + str(VALID_SUB).replace("'", '"') + "]", encoding="utf-8")
    # First entry is missing keys; should be silently dropped.
    loaded = FileSubscriptionStore(path).load()
    # The second entry, which is well-formed, should survive.
    assert all(s.endpoint and s.keys for s in loaded)


# --- High-level ops with monkeypatched store -------------------------------


def test_upsert_dedupes_on_endpoint(tmp_path: Path, monkeypatch) -> None:
    store = FileSubscriptionStore(tmp_path / "subs.json")
    monkeypatch.setattr(push_mod, "get_subscription_store", lambda: store)

    sub1 = PushSubscription.model_validate({**VALID_SUB, "label": "first"})
    upsert_subscription(sub1)
    assert len(list_subscriptions()) == 1

    sub2 = PushSubscription.model_validate({**VALID_SUB, "label": "second"})
    upsert_subscription(sub2)
    loaded = list_subscriptions()
    # Same endpoint → one row, latest wins
    assert len(loaded) == 1
    assert loaded[0].label == "second"


def test_remove_subscription_returns_false_when_unknown(
    tmp_path: Path, monkeypatch
) -> None:
    store = FileSubscriptionStore(tmp_path / "subs.json")
    monkeypatch.setattr(push_mod, "get_subscription_store", lambda: store)
    assert remove_subscription("https://nothing-here.example.com/foo") is False


def test_remove_subscription_removes_existing(tmp_path: Path, monkeypatch) -> None:
    store = FileSubscriptionStore(tmp_path / "subs.json")
    monkeypatch.setattr(push_mod, "get_subscription_store", lambda: store)
    upsert_subscription(PushSubscription.model_validate(VALID_SUB))
    assert remove_subscription(VALID_SUB["endpoint"]) is True
    assert list_subscriptions() == []
