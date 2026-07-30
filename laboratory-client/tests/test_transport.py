"""Tests for the shared laboratory-model transport (`laboratory_client.transport`).

Every mock SiLA2 server reaches the world model through this one module, so the details it
gets right or wrong are the same for all of them: how a base URL and a path are joined,
whether a read stays a read, whether a location name survives being put in a path, and
whether an unreachable model looks like one exception type or four.

`urlopen` is replaced rather than a real server started: the point here is the request that
gets built and how a failure is translated, both of which are visible at that seam. The
sample scripts cover the same calls against a live stack.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError

import pytest

from laboratory_client import transport


class FakeResponse:
    """The tiny slice of `urlopen`'s return value the transport actually uses: a context
    manager whose body `json.load` can read."""

    def __init__(self, payload: Any) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def read(self, *args: int) -> bytes:
        # json.load calls read() once with no argument; returning everything then leaving
        # the buffer empty is enough for a single decode.
        body, self._body = self._body, b""
        return body

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Capture the Request objects the transport builds, and answer each with an empty body.

    Returns the list the fake appends to, so a test can assert on what was sent."""
    requests: list[Any] = []

    def fake_urlopen(request: Any, timeout: float | None = None) -> FakeResponse:
        requests.append((request, timeout))
        return FakeResponse({})

    monkeypatch.setattr(transport, "urlopen", fake_urlopen)
    return requests


def test_joins_base_url_and_path_tolerantly(captured: list[Any]) -> None:
    # Callers pass base URLs and paths from config and from literals, so both a trailing
    # and a leading slash have to be absorbed rather than producing a doubled one.
    transport.request_laboratory_model(base_url="http://lab:8001/", path="/health")

    request, _ = captured[0]
    assert request.full_url == "http://lab:8001/health"


def test_joins_when_neither_side_has_a_slash(captured: list[Any]) -> None:
    transport.request_laboratory_model(base_url="http://lab:8001", path="health")

    request, _ = captured[0]
    assert request.full_url == "http://lab:8001/health"


def test_a_read_sends_no_body_and_no_content_type(captured: list[Any]) -> None:
    # Without a payload the call must stay a plain GET: sending an empty body or a JSON
    # content-type on a read would misrepresent it to the server.
    transport.request_laboratory_model(base_url="http://lab:8001", path="/state")

    request, _ = captured[0]
    assert request.get_method() == "GET"
    assert request.data is None
    assert request.get_header("Content-type") is None


def test_a_write_sends_the_payload_as_json(captured: list[Any]) -> None:
    transport.request_laboratory_model(
        base_url="http://lab:8001",
        path="/items/add",
        method="POST",
        payload={"location": "station:1"},
    )

    request, _ = captured[0]
    assert request.get_method() == "POST"
    assert json.loads(request.data.decode("utf-8")) == {"location": "station:1"}
    assert request.get_header("Content-type") == "application/json"


def test_the_default_timeout_is_applied(captured: list[Any]) -> None:
    # The deadline is part of the contract, not an incidental default: a world model that
    # cannot answer promptly has to fail the command rather than stall it.
    transport.request_laboratory_model(base_url="http://lab:8001", path="/health")

    _, timeout = captured[0]
    assert timeout == transport.DEFAULT_TIMEOUT_SECONDS


def test_returns_the_decoded_body(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(transport, "urlopen", lambda request, timeout=None: FakeResponse({"occupied": True}))

    result = transport.request_laboratory_model(base_url="http://lab:8001", path="/locations/station:1")

    assert result == {"occupied": True}


def test_get_location_percent_encodes_the_name(captured: list[Any]) -> None:
    # Real location names contain a colon, and dotted labcode spot names are coming, so the
    # name goes into the path encoded -- getting this wrong addresses the wrong location.
    transport.get_location(base_url="http://lab:8001", location="centrifuge:1")

    request, _ = captured[0]
    assert request.full_url == "http://lab:8001/locations/centrifuge%3A1"


@pytest.mark.parametrize(
    "raised",
    [
        HTTPError("http://lab:8001/health", 500, "Server Error", {}, None),  # type: ignore[arg-type]
        URLError("connection refused"),
        TimeoutError("timed out"),
        json.JSONDecodeError("not json", "", 0),
    ],
)
def test_every_failure_mode_collapses_into_one_error(monkeypatch: pytest.MonkeyPatch, raised: Exception) -> None:
    # An error status, an unreachable host, a deadline and an unreadable body all mean the
    # same thing to a caller: the call did not happen. Collapsing them is what lets each
    # server catch one type and re-raise with its own command-scoped message.
    def fake_urlopen(request: Any, timeout: float | None = None) -> FakeResponse:
        raise raised

    monkeypatch.setattr(transport, "urlopen", fake_urlopen)

    with pytest.raises(transport.LaboratoryModelRequestError) as error:
        transport.request_laboratory_model(base_url="http://lab:8001", path="/health")

    # The URL is in the message because a server's own message names the command but not
    # the endpoint it failed to reach.
    assert "http://lab:8001/health" in str(error.value)
    assert error.value.__cause__ is raised
