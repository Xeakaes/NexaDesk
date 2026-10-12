import threading
import time

from core.agent.cancellation import CancellationToken
from core.agent.runtime import _LinkedToken


def test_linked_token_wait_observes_parent_cancel_promptly():
    # B38: the child must not block for the full timeout when the PARENT is
    # cancelled mid-wait — tool spawn/cancel loops poll this.
    parent = CancellationToken()
    child = _LinkedToken(parent)
    threading.Timer(0.1, parent.cancel).start()
    t0 = time.perf_counter()
    assert child.wait(5.0) is True
    assert time.perf_counter() - t0 < 2.0
    assert child.cancelled


def test_linked_token_wait_own_cancel_returns_true():
    parent = CancellationToken()
    child = _LinkedToken(parent)
    child.cancel()
    assert child.wait(1.0) is True


def test_linked_token_wait_timeout_returns_false():
    parent = CancellationToken()
    child = _LinkedToken(parent)
    assert child.wait(0.05) is False
    assert not child.cancelled
