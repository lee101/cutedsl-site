"""Idle eviction must never interrupt an active forecast."""

import contextlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import server


@pytest.mark.parametrize("batch", [False, True])
def test_forecast_pins_model_until_completion(monkeypatch, batch):
    active = []

    @contextlib.contextmanager
    def use(name):
        active.append(name)
        try:
            yield
        finally:
            active.pop()

    monkeypatch.setattr(server.model_manager, "use", use)

    def predict(req):
        assert active == ["chronos2"]
        return "result"

    name = "_forecast_batch_loaded_sync" if batch else "_forecast_loaded_sync"
    monkeypatch.setattr(server, name, predict)
    fn = server._forecast_batch_sync if batch else server._forecast_sync
    assert fn(None) == "result"
    assert not active


def test_idle_eviction_skips_active_model(monkeypatch):
    manager = server.ModelManager()
    manager._loaded = {"chronos2"}
    manager._last_access["chronos2"] = server.time.time() - 21
    manager._in_use["chronos2"] = 1
    monkeypatch.setattr(server, "MODEL_IDLE_TIMEOUT", 20)
    dropped = []
    monkeypatch.setattr(manager, "_drop_locked", dropped.append)
    manager._unload_idle()
    manager._idle_timer.cancel()
    assert not dropped
    manager._in_use["chronos2"] = 0
    manager._unload_idle()
    assert dropped == ["chronos2"]
