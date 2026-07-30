"""Unit tests for the world model itself (`app.state`), with no HTTP involved.

Each test builds its own `LaboratoryModelState`, so these cover the rules in isolation from the
API layer: what the store allows, what it refuses, and with which error code. The codes are
asserted rather than just the exception type because they are the stable part of the contract --
the API layer maps them to HTTP statuses and callers switch on them.

Three themes run through the file and are worth naming, because they are the properties the
device-centric model exists to have:

* the topology is **declared**, so an undeclared device or spot is an error rather than
  something the request brings into being;
* `accessible` is a **per-spot, enforced** property -- the store refuses to reach into a closed
  spot, and a device with several spots has several independent doors as far as it is concerned;
* device `state` is **opaque** -- it is stored verbatim and no rule here reads it. The tests for
  that last point are deliberately about what does *not* happen.
"""

from __future__ import annotations

import pytest

from app.state import LaboratoryModelError, LaboratoryModelState


@pytest.fixture
def world() -> LaboratoryModelState:
    # A private world per test, declared with the same shape the API tests use: one single-spot
    # device, one two-spot device. Nothing here touches the process-wide instance the API layer
    # uses.
    state = LaboratoryModelState()
    state.declare_devices([("centrifuge", ["deck"]), ("station", ["slot1", "slot2"])])
    return state


# --- Topology. ---


def test_declared_devices_are_listed_sorted(world: LaboratoryModelState) -> None:
    assert world.list_devices() == ["centrifuge", "station"]


def test_a_declared_spot_starts_empty_and_accessible(world: LaboratoryModelState) -> None:
    # The default state of a place nothing has touched: there, reachable, and holding nothing.
    spot = world.get_location("station.slot1")

    assert spot.device == "station"
    assert spot.spot == "slot1"
    assert spot.location == "station.slot1"
    assert spot.occupied is False
    assert spot.item_id is None
    assert spot.accessible is True


def test_an_undeclared_spot_is_unknown_rather_than_empty(world: LaboratoryModelState) -> None:
    # The central difference from the previous model, where any string read as an empty
    # accessible location. A spot that was never declared does not exist, and saying so is what
    # turns "move the plate to a place that is not there" into a reported failure.
    with pytest.raises(LaboratoryModelError) as error:
        world.get_location("station.slot3")

    assert error.value.code == "unknown_location"
    assert error.value.details == {"location": "station.slot3"}


def test_an_undeclared_device_reports_the_same_code(world: LaboratoryModelState) -> None:
    # An unknown device and an unknown spot collapse into one code on purpose: to a caller both
    # mean "that place does not exist", and the location it asked for is in the details.
    with pytest.raises(LaboratoryModelError) as error:
        world.get_location("dispenser.deck")

    assert error.value.code == "unknown_location"


def test_declaring_a_device_twice_is_refused(world: LaboratoryModelState) -> None:
    # Accepting it would silently drop the earlier spot set, so the store refuses to pick a
    # winner.
    with pytest.raises(LaboratoryModelError) as error:
        world.declare_devices([("centrifuge", ["deck"]), ("centrifuge", ["tray"])])

    assert error.value.code == "duplicate_device"


def test_declaring_a_spot_twice_on_one_device_is_refused(world: LaboratoryModelState) -> None:
    with pytest.raises(LaboratoryModelError) as error:
        world.declare_devices([("dispenser", ["deck", "deck"])])

    assert error.value.code == "duplicate_spot"


def test_a_failed_declaration_leaves_the_previous_world_intact(world: LaboratoryModelState) -> None:
    # The swap happens only once every declaration validated, so a bad declaration cannot leave
    # the world half-built.
    with pytest.raises(LaboratoryModelError):
        world.declare_devices([("dispenser", ["deck"]), ("dispenser", ["tube"])])

    assert world.list_devices() == ["centrifuge", "station"]


def test_a_device_may_be_declared_with_no_spots() -> None:
    # Something that only carries state and never holds an item is a legitimate thing to model.
    state = LaboratoryModelState()
    state.declare_devices([("controller", [])])

    assert state.get_device("controller").spots == []


# --- Item placement. ---


def test_add_item_occupies_the_spot_with_a_fresh_id(world: LaboratoryModelState) -> None:
    record = world.add_item("station.slot1")

    assert record.location == "station.slot1"
    stored = world.get_location("station.slot1")
    assert stored.occupied is True
    assert stored.item_id == record.item_id


def test_add_item_mints_a_distinct_id_per_item(world: LaboratoryModelState) -> None:
    # Ids are the world's own occupancy tokens, so two plates are never confusable.
    first = world.add_item("station.slot1")
    second = world.add_item("station.slot2")

    assert first.item_id != second.item_id


def test_add_item_rejects_an_undeclared_spot(world: LaboratoryModelState) -> None:
    with pytest.raises(LaboratoryModelError) as error:
        world.add_item("station.slot3")

    assert error.value.code == "unknown_location"


def test_add_item_rejects_an_occupied_spot(world: LaboratoryModelState) -> None:
    world.add_item("station.slot1")

    with pytest.raises(LaboratoryModelError) as error:
        world.add_item("station.slot1")

    assert error.value.code == "destination_occupied"


def test_add_item_rejects_a_locked_spot(world: LaboratoryModelState) -> None:
    # A closed door is not something you can put a plate through.
    world.lock_location("centrifuge.deck")

    with pytest.raises(LaboratoryModelError) as error:
        world.add_item("centrifuge.deck")

    assert error.value.code == "location_locked"


# --- Moves. ---


def test_move_item_carries_the_identity_and_empties_the_source(world: LaboratoryModelState) -> None:
    # A move is the same item changing place, not a destroy plus a create -- this is what makes
    # tracking one plate across a workflow meaningful.
    added = world.add_item("station.slot1")

    moved = world.move_item("station.slot1", "centrifuge.deck")

    assert moved.item_id == added.item_id
    assert world.get_location("station.slot1").occupied is False
    assert world.get_location("centrifuge.deck").item_id == added.item_id


def test_move_item_works_between_two_spots_of_one_device(world: LaboratoryModelState) -> None:
    # Spots of a single device are independent places; a move within a device is an ordinary
    # move, not a special case.
    added = world.add_item("station.slot1")

    moved = world.move_item("station.slot1", "station.slot2")

    assert moved.item_id == added.item_id
    assert world.get_location("station.slot2").occupied is True


def test_move_item_rejects_a_degenerate_move(world: LaboratoryModelState) -> None:
    world.add_item("station.slot1")

    with pytest.raises(LaboratoryModelError) as error:
        world.move_item("station.slot1", "station.slot1")

    assert error.value.code == "same_source_and_destination"


def test_move_item_reports_an_undeclared_source_before_anything_else(world: LaboratoryModelState) -> None:
    # Existence is settled before occupancy or accessibility, so a typo in a location name is
    # reported as a typo rather than as "the source is empty".
    with pytest.raises(LaboratoryModelError) as error:
        world.move_item("station.slot3", "centrifuge.deck")

    assert error.value.code == "unknown_location"
    assert error.value.details == {"location": "station.slot3"}


def test_move_item_reports_an_undeclared_destination(world: LaboratoryModelState) -> None:
    world.add_item("station.slot1")

    with pytest.raises(LaboratoryModelError) as error:
        world.move_item("station.slot1", "dispenser.deck")

    assert error.value.code == "unknown_location"
    assert error.value.details == {"location": "dispenser.deck"}


def test_move_item_rejects_an_empty_source(world: LaboratoryModelState) -> None:
    with pytest.raises(LaboratoryModelError) as error:
        world.move_item("station.slot1", "centrifuge.deck")

    assert error.value.code == "source_empty"


def test_move_item_rejects_an_occupied_destination(world: LaboratoryModelState) -> None:
    world.add_item("station.slot1")
    world.add_item("centrifuge.deck")

    with pytest.raises(LaboratoryModelError) as error:
        world.move_item("station.slot1", "centrifuge.deck")

    assert error.value.code == "destination_occupied"


def test_move_item_rejects_a_locked_source(world: LaboratoryModelState) -> None:
    world.add_item("station.slot1")
    world.lock_location("station.slot1")

    with pytest.raises(LaboratoryModelError) as error:
        world.move_item("station.slot1", "centrifuge.deck")

    assert error.value.code == "source_locked"


def test_move_item_checks_accessibility_before_occupancy(world: LaboratoryModelState) -> None:
    # Both ends are wrong here: the source has nothing to give AND the destination is locked.
    # The reported code pins down the checking order -- reachability of both ends is settled
    # before occupancy is looked at -- which is what lets a caller trust that a `source_empty`
    # really means the doors were fine.
    world.lock_location("centrifuge.deck")

    with pytest.raises(LaboratoryModelError) as error:
        world.move_item("station.slot1", "centrifuge.deck")

    assert error.value.code == "destination_locked"


def test_move_item_leaves_the_world_untouched_when_it_fails(world: LaboratoryModelState) -> None:
    # A rejected move must not half-apply: the plate stays where it was.
    added = world.add_item("station.slot1")
    world.add_item("centrifuge.deck")

    with pytest.raises(LaboratoryModelError):
        world.move_item("station.slot1", "centrifuge.deck")

    assert world.get_location("station.slot1").item_id == added.item_id


# --- Removal. ---


def test_remove_item_rejects_a_locked_spot(world: LaboratoryModelState) -> None:
    # The plate is right there, but a closed door blocks taking it out as well as putting one in.
    world.add_item("centrifuge.deck")
    world.lock_location("centrifuge.deck")

    with pytest.raises(LaboratoryModelError) as error:
        world.remove_item("centrifuge.deck")

    assert error.value.code == "location_locked"


def test_remove_item_rejects_an_empty_spot(world: LaboratoryModelState) -> None:
    with pytest.raises(LaboratoryModelError) as error:
        world.remove_item("station.slot1")

    assert error.value.code == "source_empty"


def test_remove_item_leaves_the_spot_declared_and_accessible(world: LaboratoryModelState) -> None:
    # Removing takes the item, not the spot.
    world.add_item("station.slot1")

    world.remove_item("station.slot1")

    assert world.get_location("station.slot1").occupied is False
    assert world.get_location("station.slot1").accessible is True


# --- Accessibility, which is per spot. ---


def test_locking_keeps_the_item_in_place(world: LaboratoryModelState) -> None:
    # "Occupied and inaccessible" is a closed instrument holding a plate, so it has to be
    # expressible: locking hides nothing and evicts nothing.
    added = world.add_item("centrifuge.deck")

    locked = world.lock_location("centrifuge.deck")

    assert locked.accessible is False
    assert locked.occupied is True
    assert locked.item_id == added.item_id


def test_locking_one_spot_leaves_the_other_spots_of_the_device_open(world: LaboratoryModelState) -> None:
    # Accessibility is a property of a spot, not of a device. A lid that covers several spots is
    # expressed by its server locking each one, which keeps "what does this lid cover" in the
    # server that knows the instrument rather than in the store.
    world.lock_location("station.slot1")

    assert world.get_location("station.slot1").accessible is False
    assert world.get_location("station.slot2").accessible is True


def test_lock_and_unlock_are_idempotent(world: LaboratoryModelState) -> None:
    # Doors get closed twice in real workflows (and by a re-run of a script); repeating either
    # call is a no-op rather than an error.
    world.lock_location("station.slot1")
    assert world.lock_location("station.slot1").accessible is False

    world.unlock_location("station.slot1")
    assert world.unlock_location("station.slot1").accessible is True


def test_locking_an_undeclared_spot_is_refused(world: LaboratoryModelState) -> None:
    with pytest.raises(LaboratoryModelError) as error:
        world.lock_location("station.slot3")

    assert error.value.code == "unknown_location"


# --- Opaque device state. These tests are mostly about what does NOT happen. ---


def test_device_state_starts_empty(world: LaboratoryModelState) -> None:
    assert world.get_device_state("centrifuge") == {}


def test_device_state_round_trips_scalars_verbatim(world: LaboratoryModelState) -> None:
    # Values are kept as given, with no coercion: the server that wrote a key is the only thing
    # that knows what it means, so changing the value would change that meaning.
    world.set_device_state(device="centrifuge", key="door", value="open")
    world.set_device_state(device="centrifuge", key="cycles", value=3)
    world.set_device_state(device="centrifuge", key="ready", value=True)
    world.set_device_state(device="centrifuge", key="last_error", value=None)

    assert world.get_device_state("centrifuge") == {
        "door": "open",
        "cycles": 3,
        "ready": True,
        "last_error": None,
    }


def test_device_state_does_not_affect_any_world_rule(world: LaboratoryModelState) -> None:
    # The point of the whole separation: a key that looks like it should close the door does not
    # close it. `accessible` is the only thing the store enforces, and nothing writes it but
    # lock/unlock.
    world.set_device_state(device="centrifuge", key="door", value="closed")
    world.set_device_state(device="centrifuge", key="up", value=False)

    assert world.get_location("centrifuge.deck").accessible is True
    # And an add still succeeds, which it would not if the store read `door`.
    assert world.add_item("centrifuge.deck").location == "centrifuge.deck"


def test_device_state_is_per_device(world: LaboratoryModelState) -> None:
    world.set_device_state(device="centrifuge", key="door", value="open")

    assert world.get_device_state("station") == {}


def test_reading_device_state_returns_a_copy(world: LaboratoryModelState) -> None:
    # Otherwise a caller could mutate the world just by holding on to the result.
    world.set_device_state(device="centrifuge", key="door", value="open")

    world.get_device_state("centrifuge")["door"] = "closed"

    assert world.get_device_state("centrifuge") == {"door": "open"}


def test_unsetting_a_key_removes_it(world: LaboratoryModelState) -> None:
    world.set_device_state(device="centrifuge", key="door", value="open")

    world.unset_device_state(device="centrifuge", key="door")

    assert world.get_device_state("centrifuge") == {}


def test_unsetting_a_key_that_is_not_set_is_refused(world: LaboratoryModelState) -> None:
    # Absent and never-set are the same thing for an opaque bag, so a caller asking to remove a
    # key that is not there believed something about the world that is not so.
    with pytest.raises(LaboratoryModelError) as error:
        world.unset_device_state(device="centrifuge", key="door")

    assert error.value.code == "unknown_state_key"


def test_device_state_on_an_undeclared_device_is_refused(world: LaboratoryModelState) -> None:
    with pytest.raises(LaboratoryModelError) as error:
        world.set_device_state(device="dispenser", key="door", value="open")

    assert error.value.code == "unknown_device"


def test_replacing_device_state_swaps_the_whole_bag(world: LaboratoryModelState) -> None:
    # Used by the seed loader, which knows the complete t=0 state and should not have to clear
    # and re-add key by key.
    world.set_device_state(device="centrifuge", key="door", value="open")

    world.replace_device_state(device="centrifuge", state={"lid": "closed"})

    assert world.get_device_state("centrifuge") == {"lid": "closed"}


# --- Snapshot and reset. ---


def test_snapshot_lists_every_declared_device_and_spot_sorted(world: LaboratoryModelState) -> None:
    # No longer sparse: with the topology declared there is no "untouched and therefore absent"
    # case to reason about, so a snapshot is the whole world.
    world.add_item("station.slot2")
    world.set_device_state(device="centrifuge", key="door", value="open")

    snapshot = world.snapshot()

    assert [device.device for device in snapshot] == ["centrifuge", "station"]
    assert [spot.spot for spot in snapshot[1].spots] == ["slot1", "slot2"]
    assert snapshot[0].state == {"door": "open"}
    assert snapshot[1].spots[1].occupied is True
    assert snapshot[1].spots[1].location == "station.slot2"


def test_reset_keeps_the_topology(world: LaboratoryModelState) -> None:
    # The property that makes reset usable as a between-tests wipe: dropping the topology would
    # leave every location unknown and nothing able to run.
    world.add_item("station.slot1")

    world.reset()

    assert world.list_devices() == ["centrifuge", "station"]
    assert world.get_location("station.slot1").occupied is False


def test_reset_clears_items_accessibility_and_device_state(world: LaboratoryModelState) -> None:
    world.add_item("station.slot1")
    world.lock_location("station.slot2")
    world.set_device_state(device="centrifuge", key="door", value="closed")

    world.reset()

    assert world.get_location("station.slot1").occupied is False
    # Back to the default, not merely absent.
    assert world.get_location("station.slot2").accessible is True
    assert world.get_device_state("centrifuge") == {}
