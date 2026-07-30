"""Fixtures shared by the laboratory model tests.

These tests run the service **in process** -- no container, no network -- by importing
`app.main.create_app()` and driving it through FastAPI's TestClient. That is the main
difference from `samples/laboratory_model_smoke.py`, which checks the same rules over HTTP
against a running stack: the sample proves the deployed service works, these prove the
rules themselves, fast enough to run on every edit.

Two things need care for every test and are handled here:

* the world is a single process-wide instance (`app.main.state`) shared by every app
  object, so it has to be wiped between tests or they would leak into each other;
* `create_app()` seeds that world from the file named by
  LABORATORY_MODEL_INITIAL_STATE_FILE, so the variable is cleared from the environment
  unless a test sets it deliberately.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import create_app, state


@pytest.fixture(autouse=True)
def clean_world(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Give every test an empty world and a seed-free environment.

    Autouse, and therefore ordered before the `client` fixture below, so the environment
    is already clean by the time an app's startup handler runs."""
    monkeypatch.delenv("LABORATORY_MODEL_INITIAL_STATE_FILE", raising=False)
    state.reset()
    yield
    # Wipe on the way out too, so a failing test cannot poison the next one.
    state.reset()


@pytest.fixture
def client() -> Iterator[TestClient]:
    """An HTTP client bound to a fresh app instance.

    Entered as a context manager on purpose: TestClient only runs the startup handler
    inside `with`, and that handler (the seeding step) is part of what is under test."""
    with TestClient(create_app()) as test_client:
        yield test_client
