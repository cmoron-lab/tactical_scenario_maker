# tests/test_lotusim_futures.py — contrat de transport, sans rclpy ni lotusim_msgs
import pytest

from tsm.lotusim.futures import require_result


class _FakeFuture:
    def __init__(self, done=True, exception=None, result=None):
        self._done = done
        self._exception = exception
        self._result = result

    def done(self):
        return self._done

    def exception(self):
        return self._exception

    def result(self):
        return self._result


class _FakeSetWaypointsResponse:
    def __init__(self, success):
        self.success = success


def test_require_result_raises_on_timeout():
    with pytest.raises(RuntimeError, match="set_waypoints: timeout"):
        require_result(_FakeFuture(done=False), "set_waypoints")


def test_require_result_raises_on_exception():
    with pytest.raises(RuntimeError, match="set_waypoints: boom"):
        require_result(_FakeFuture(exception=RuntimeError("boom")), "set_waypoints")


def test_require_result_returns_response_even_when_success_is_false():
    response = _FakeSetWaypointsResponse(success=False)
    result = require_result(_FakeFuture(result=response), "set_waypoints")
    assert result.success is False
