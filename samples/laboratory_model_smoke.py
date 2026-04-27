from __future__ import annotations

import argparse

from common import (
    DEFAULT_LABORATORY_MODEL_URL,
    add_item_to_location,
    expect_laboratory_model_error,
    get_laboratory_model_health,
    get_location_state,
    lock_location,
    move_item_between_locations,
    remove_item_from_location,
    reset_laboratory_model,
    unlock_location,
)


DEFAULT_SOURCE_LOCATION = "spot-1"
DEFAULT_DESTINATION_LOCATION = "station:1"


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test the laboratory model service directly.")
    parser.add_argument(
        "--laboratory-model-url",
        default=DEFAULT_LABORATORY_MODEL_URL,
        help="Laboratory model base URL",
    )
    parser.add_argument(
        "--source-location",
        default=DEFAULT_SOURCE_LOCATION,
        help="Source location used by the smoke test",
    )
    parser.add_argument(
        "--destination-location",
        default=DEFAULT_DESTINATION_LOCATION,
        help="Destination location used by the smoke test",
    )
    args = parser.parse_args()

    health = get_laboratory_model_health(laboratory_model_url=args.laboratory_model_url)
    print(f"Health: {health}")
    if health.get("status") != "healthy":
        raise RuntimeError(f"Unexpected health response: {health}")

    reset_result = reset_laboratory_model(laboratory_model_url=args.laboratory_model_url)
    print(f"Reset before test: {reset_result}")
    if reset_result.get("cleared") is not True:
        raise RuntimeError(f"Unexpected reset response: {reset_result}")

    source_before = get_location_state(
        laboratory_model_url=args.laboratory_model_url,
        location=args.source_location,
    )
    print(f"Source before add: {source_before}")
    if source_before.get("occupied") is not False or source_before.get("accessible") is not True:
        raise RuntimeError(f"Expected empty source location before add: {source_before}")

    locked_source = lock_location(
        laboratory_model_url=args.laboratory_model_url,
        location=args.source_location,
    )
    print(f"Locked source: {locked_source}")
    if locked_source.get("accessible") is not False:
        raise RuntimeError(f"Unexpected lock response: {locked_source}")

    source_after_lock = get_location_state(
        laboratory_model_url=args.laboratory_model_url,
        location=args.source_location,
    )
    print(f"Source after lock: {source_after_lock}")
    if source_after_lock.get("accessible") is not False:
        raise RuntimeError(f"Expected locked source location: {source_after_lock}")

    add_locked_status, add_locked_error = expect_laboratory_model_error(
        laboratory_model_url=args.laboratory_model_url,
        path="/items/add",
        method="POST",
        payload={"location": args.source_location},
    )
    print(f"Add while locked error: status={add_locked_status} body={add_locked_error}")
    if add_locked_status != 409 or add_locked_error["error"]["code"] != "location_locked":
        raise RuntimeError(f"Unexpected add-while-locked error: {add_locked_status}, {add_locked_error}")

    unlocked_source = unlock_location(
        laboratory_model_url=args.laboratory_model_url,
        location=args.source_location,
    )
    print(f"Unlocked source: {unlocked_source}")
    if unlocked_source.get("accessible") is not True:
        raise RuntimeError(f"Unexpected unlock response: {unlocked_source}")

    added_item = add_item_to_location(
        laboratory_model_url=args.laboratory_model_url,
        location=args.source_location,
    )
    print(f"Added item: {added_item}")
    if added_item.get("occupied") is not True or not added_item.get("item_id"):
        raise RuntimeError(f"Unexpected add response: {added_item}")
    item_id = added_item["item_id"]

    source_after_add = get_location_state(
        laboratory_model_url=args.laboratory_model_url,
        location=args.source_location,
    )
    print(f"Source after add: {source_after_add}")
    if source_after_add.get("item_id") != item_id or source_after_add.get("accessible") is not True:
        raise RuntimeError(f"Added item was not found at source location: {source_after_add}")

    moved_item = move_item_between_locations(
        laboratory_model_url=args.laboratory_model_url,
        source=args.source_location,
        destination=args.destination_location,
    )
    print(f"Moved item: {moved_item}")
    if moved_item.get("moved") is not True or moved_item.get("item_id") != item_id:
        raise RuntimeError(f"Unexpected move response: {moved_item}")

    source_after_move = get_location_state(
        laboratory_model_url=args.laboratory_model_url,
        location=args.source_location,
    )
    destination_after_move = get_location_state(
        laboratory_model_url=args.laboratory_model_url,
        location=args.destination_location,
    )
    print(f"Source after move: {source_after_move}")
    print(f"Destination after move: {destination_after_move}")
    if source_after_move.get("occupied") is not False:
        raise RuntimeError(f"Expected empty source location after move: {source_after_move}")
    if destination_after_move.get("item_id") != item_id or destination_after_move.get("accessible") is not True:
        raise RuntimeError(f"Moved item was not found at destination location: {destination_after_move}")

    locked_destination = lock_location(
        laboratory_model_url=args.laboratory_model_url,
        location=args.destination_location,
    )
    print(f"Locked destination: {locked_destination}")
    if locked_destination.get("accessible") is not False:
        raise RuntimeError(f"Unexpected destination lock response: {locked_destination}")

    destination_after_lock = get_location_state(
        laboratory_model_url=args.laboratory_model_url,
        location=args.destination_location,
    )
    print(f"Destination after lock: {destination_after_lock}")
    if destination_after_lock.get("item_id") != item_id or destination_after_lock.get("accessible") is not False:
        raise RuntimeError(f"Expected locked destination location with item present: {destination_after_lock}")

    remove_locked_status, remove_locked_error = expect_laboratory_model_error(
        laboratory_model_url=args.laboratory_model_url,
        path="/items/remove",
        method="DELETE",
        payload={"location": args.destination_location},
    )
    print(f"Remove while locked error: status={remove_locked_status} body={remove_locked_error}")
    if remove_locked_status != 409 or remove_locked_error["error"]["code"] != "location_locked":
        raise RuntimeError(f"Unexpected remove-while-locked error: {remove_locked_status}, {remove_locked_error}")

    unlocked_destination = unlock_location(
        laboratory_model_url=args.laboratory_model_url,
        location=args.destination_location,
    )
    print(f"Unlocked destination: {unlocked_destination}")
    if unlocked_destination.get("accessible") is not True:
        raise RuntimeError(f"Unexpected destination unlock response: {unlocked_destination}")

    lock_location(
        laboratory_model_url=args.laboratory_model_url,
        location=args.destination_location,
    )
    move_locked_status, move_locked_error = expect_laboratory_model_error(
        laboratory_model_url=args.laboratory_model_url,
        path="/items/move",
        method="POST",
        payload={"source": args.source_location, "destination": args.destination_location},
    )
    print(f"Move to locked destination error: status={move_locked_status} body={move_locked_error}")
    if move_locked_status != 409 or move_locked_error["error"]["code"] != "destination_locked":
        raise RuntimeError(
            f"Unexpected move-to-locked-destination error: {move_locked_status}, {move_locked_error}"
        )
    unlock_location(
        laboratory_model_url=args.laboratory_model_url,
        location=args.destination_location,
    )

    removed_item = remove_item_from_location(
        laboratory_model_url=args.laboratory_model_url,
        location=args.destination_location,
    )
    print(f"Removed item: {removed_item}")
    if removed_item.get("removed") is not True or removed_item.get("item_id") != item_id:
        raise RuntimeError(f"Unexpected remove response: {removed_item}")

    destination_after_remove = get_location_state(
        laboratory_model_url=args.laboratory_model_url,
        location=args.destination_location,
    )
    print(f"Destination after remove: {destination_after_remove}")
    if destination_after_remove.get("occupied") is not False or destination_after_remove.get("accessible") is not True:
        raise RuntimeError(f"Expected empty destination location after remove: {destination_after_remove}")

    reset_after_test = reset_laboratory_model(laboratory_model_url=args.laboratory_model_url)
    print(f"Reset after test: {reset_after_test}")
    if reset_after_test.get("cleared") is not True:
        raise RuntimeError(f"Unexpected final reset response: {reset_after_test}")

    print("Laboratory model smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
