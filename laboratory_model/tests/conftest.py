"""Fixtures shared by the laboratory model tests.

These tests run the service **in process** -- no container, no network -- by importing
`app.main.create_app()` and driving it through FastAPI's TestClient. That is the difference
from `samples/laboratory_model_smoke.py`, which checks the same rules over HTTP against a
running stack: the sample proves the deployed service works, these prove the rules themselves,
fast enough to run on every edit.

Two things need care for every test and are handled here:

* the world is a single process-wide instance (`app.main.state`) shared by every app object, so
  it has to be wiped between tests or they would leak into each other;
* an app seeds itself from the file named by LABORATORY_MODEL_SEED_FILE, so the variable is
  cleared from the environment unless a test sets it deliberately.

`declared` is the fixture most tests start from. With a declared topology there is no such
thing as a location springing into existence on use, so a test that wants to place an item has
to say first which devices and spots exist. It writes a seed file and points the app at it
rather than calling the store directly, because that is the path a real container takes.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from app.main import SEED_FILE_VARIABLE, create_app, state

# The topology most tests use: two single-spot instruments and one two-slot station. Small
# enough to assert on whole, and it covers the cases that differ -- a device with one spot, a
# device with several, and (via `state`) a device carrying opaque state.
DEFAULT_SEED: dict[str, object] = {
    "devices": [
        {"id": "centrifuge", "spots": ["deck"], "state": {"door": "open"}},
        {"id": "station", "spots": ["slot1", "slot2"]},
        {"id": "thermal-cycler", "spots": ["block"], "state": {"lid": "open"}},
    ]
}


@pytest.fixture(autouse=True)
def clean_world(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Give every test an empty world and a seed-free environment.

    Autouse, and therefore ordered before the fixtures below, so the environment is already
    clean by the time an app's lifespan runs. `declare_devices(())` rather than `reset()`
    because a leftover topology would let a test address a device it never declared."""
    monkeypatch.delenv(SEED_FILE_VARIABLE, raising=False)
    state.declare_devices(())
    yield
    # Wipe on the way out too, so a failing test cannot poison the next one.
    state.declare_devices(())


@pytest.fixture
def write_seed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[[object], str]:
    """Materialise a seed document as a real YAML file and point the app at it.

    Returns the path as well as setting the variable, so a test that loads the file directly
    (rather than through an app) can use the same helper."""

    def _write(document: object) -> str:
        file_path = tmp_path / "seed.yaml"
        file_path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
        monkeypatch.setenv(SEED_FILE_VARIABLE, str(file_path))
        return str(file_path)

    return _write


@pytest.fixture
def client(write_seed: Callable[[object], str]) -> Iterator[TestClient]:
    """An HTTP client bound to a fresh app seeded with `DEFAULT_SEED`.

    Entered as a context manager on purpose: TestClient only runs the lifespan inside `with`,
    and the seeding step is part of what is under test."""
    write_seed(DEFAULT_SEED)
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def unseeded_client() -> Iterator[TestClient]:
    """A client for an app with no seed file configured, i.e. a world with no devices at all.
    Used for the cases that are about the absence of a topology rather than its contents."""
    with TestClient(create_app()) as test_client:
        yield test_client
