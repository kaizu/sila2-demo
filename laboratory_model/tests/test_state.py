"""Unit tests for the world model itself (`app.state`), with no HTTP involved.

Each test builds its own `LaboratoryModelState`, so these cover the rules in isolation
from the API layer: what the store allows, what it refuses, and with which error code.
The codes are asserted rather than just the exception type because they are the stable
part of the contract -- the API layer maps them to HTTP statuses and callers switch on
them.
"""

from __future__ import annotations

import pytest

from app.state import LaboratoryModelError, LaboratoryModelState


@pytest.fixture
def world() -> LaboratoryModelState:
    # A private world per test: nothing here touches the process-wide instance the API
    # layer uses.
    return LaboratoryModelState()


def test_unknown_location_reads_empty_and_accessible(world: LaboratoryModelState) -> None:
    # The location universe is not pre-declared: any string is readable, and a location
    # nothing has touched is empty and reachable.
    location_state = world.get_location("never-touched")

    assert location_state.location == "never-touched"
    assert location_state.occupied is False
    assert location_state.item_id is None
    assert location_state.accessible is True


def test_add_item_occupies_the_location_with_a_fresh_id(world: LaboratoryModelState) -> None:
    record = world.add_item("spot-1")

    assert record.location == "spot-1"
    stored = world.get_location("spot-1")
    assert stored.occupied is True
    assert stored.item_id == record.item_id


def test_add_item_mints_a_distinct_id_per_item(world: LaboratoryModelState) -> None:
    # Ids are the world's own occupancy tokens, so two plates are never confusable.
    first = world.add_item("spot-1")
    second = world.add_item("spot-2")

    assert first.item_id != second.item_id


def test_add_item_rejects_an_occupied_location(world: LaboratoryModelState) -> None:
    world.add_item("spot-1")

    with pytest.raises(LaboratoryModelError) as error:
        world.add_item("spot-1")

    assert error.value.code == "destination_occupied"


def test_add_item_rejects_a_locked_location(world: LaboratoryModelState) -> None:
    # A closed door is not something you can put a plate through.
    world.lock_location("spot-1")

    with pytest.raises(LaboratoryModelError) as error:
        world.add_item("spot-1")

    assert error.value.code == "location_locked"


def test_move_item_carries_the_identity_and_empties_the_source(world: LaboratoryModelState) -> None:
    # A move is the same item changing place, not a destroy plus a create -- this is what
    # makes tracking one plate across a workflow meaningful.
    added = world.add_item("spot-1")

    moved = world.move_item("spot-1", "spot-2")

    assert moved.item_id == added.item_id
    assert world.get_location("spot-1").occupied is False
    assert world.get_location("spot-2").item_id == added.item_id


def test_move_item_rejects_a_degenerate_move(world: LaboratoryModelState) -> None:
    world.add_item("spot-1")

    with pytest.raises(LaboratoryModelError) as error:
        world.move_item("spot-1", "spot-1")

    assert error.value.code == "same_source_and_destination"


def test_move_item_rejects_an_empty_source(world: LaboratoryModelState) -> None:
    with pytest.raises(LaboratoryModelError) as error:
        world.move_item("spot-1", "spot-2")

    assert error.value.code == "source_empty"


def test_move_item_rejects_an_occupied_destination(world: LaboratoryModelState) -> None:
    world.add_item("spot-1")
    world.add_item("spot-2")

    with pytest.raises(LaboratoryModelError) as error:
        world.move_item("spot-1", "spot-2")

    assert error.value.code == "destination_occupied"


def test_move_item_rejects_a_locked_source(world: LaboratoryModelState) -> None:
    world.add_item("spot-1")
    world.lock_location("spot-1")

    with pytest.raises(LaboratoryModelError) as error:
        world.move_item("spot-1", "spot-2")

    assert error.value.code == "source_locked"


def test_move_item_checks_accessibility_before_occupancy(world: LaboratoryModelState) -> None:
    # Both ends are wrong here: the source has nothing to give AND the destination is
    # locked. The reported code pins down the checking order -- reachability of both ends
    # is settled before occupancy is looked at -- which is what lets a caller trust that a
    # `source_empty` really means the doors were fine.
    world.lock_location("spot-2")

    with pytest.raises(LaboratoryModelError) as error:
        world.move_item("spot-1", "spot-2")

    assert error.value.code == "destination_locked"


def test_move_item_leaves_the_world_untouched_when_it_fails(world: LaboratoryModelState) -> None:
    # A rejected move must not half-apply: the plate stays where it was.
    added = world.add_item("spot-1")
    world.add_item("spot-2")

    with pytest.raises(LaboratoryModelError):
        world.move_item("spot-1", "spot-2")

    assert world.get_location("spot-1").item_id == added.item_id


def test_remove_item_rejects_a_locked_location(world: LaboratoryModelState) -> None:
    # The plate is right there, but a closed door blocks taking it out as well as putting
    # one in.
    world.add_item("spot-1")
    world.lock_location("spot-1")

    with pytest.raises(LaboratoryModelError) as error:
        world.remove_item("spot-1")

    assert error.value.code == "location_locked"


def test_remove_item_rejects_an_empty_location(world: LaboratoryModelState) -> None:
    with pytest.raises(LaboratoryModelError) as error:
        world.remove_item("spot-1")

    assert error.value.code == "source_empty"


def test_remove_item_leaves_the_location_accessible(world: LaboratoryModelState) -> None:
    # Removing takes the item, not the spot.
    world.add_item("spot-1")

    world.remove_item("spot-1")

    assert world.get_location("spot-1").occupied is False
    assert world.get_location("spot-1").accessible is True


def test_locking_keeps_the_item_in_place(world: LaboratoryModelState) -> None:
    # "Occupied and inaccessible" is a closed instrument holding a plate, so it has to be
    # expressible: locking hides nothing and evicts nothing.
    added = world.add_item("spot-1")

    locked = world.lock_location("spot-1")

    assert locked.accessible is False
    assert locked.occupied is True
    assert locked.item_id == added.item_id


def test_lock_and_unlock_are_idempotent(world: LaboratoryModelState) -> None:
    # Doors get closed twice in real workflows (and by a re-run of a script); repeating
    # either call is a no-op rather than an error.
    world.lock_location("spot-1")
    assert world.lock_location("spot-1").accessible is False

    world.unlock_location("spot-1")
    assert world.unlock_location("spot-1").accessible is True


def test_snapshot_lists_touched_locations_in_order(world: LaboratoryModelState) -> None:
    # The snapshot is sparse and sorted: it reports locations that are occupied or whose
    # accessibility has been set, and merely reading a location does not register it.
    world.add_item("spot-2")
    world.lock_location("spot-1")
    world.get_location("spot-3")

    snapshot = world.snapshot()

    assert [entry.location for entry in snapshot] == ["spot-1", "spot-2"]
    assert snapshot[0].accessible is False
    assert snapshot[1].occupied is True


def test_reset_clears_items_and_lock_states(world: LaboratoryModelState) -> None:
    world.add_item("spot-1")
    world.lock_location("spot-2")

    world.reset()

    assert world.snapshot() == []
    # And the cleared locations are back to their defaults, not merely absent.
    assert world.get_location("spot-2").accessible is True
