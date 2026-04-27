from __future__ import annotations

from common import (
    DEFAULT_LABORATORY_MODEL_URL,
    add_item_to_location,
    build_parser,
    connect,
    get_location_state,
    print_server_identity,
    reset_laboratory_model,
    wait_for_observable,
)


DEFAULT_PORT = 50057
PICK_SOURCE = "station:1"
TROLLEY_LOCATION = "trolley-arm:1"
PLACE_DESTINATION = "station:2"


def main() -> int:
    parser = build_parser("Smoke test the Trolley Arm SiLA2 server directly.", DEFAULT_PORT)
    args = parser.parse_args()

    with connect(args.host, args.port, insecure=args.insecure) as client:
        print_server_identity(client, host=args.host, port=args.port)

        feature = client.TrolleyArmProvider
        reset_laboratory_model(laboratory_model_url=DEFAULT_LABORATORY_MODEL_URL)
        add_item_to_location(laboratory_model_url=DEFAULT_LABORATORY_MODEL_URL, location=PICK_SOURCE)

        original_position = feature.TrolleyPosition.get()
        print(f"Original trolley position: {original_position}")

        temporary_position = original_position + 1
        feature.SetTrolleyPosition(Position=temporary_position)
        print(f"Trolley position after move: {feature.TrolleyPosition.get()}")

        feature.SetTrolleyPosition(Position=original_position)
        print(f"Trolley position restored: {feature.TrolleyPosition.get()}")

        feature.Pick(LocationSpecifier=PICK_SOURCE)
        print(f"Source after pick: {get_location_state(laboratory_model_url=DEFAULT_LABORATORY_MODEL_URL, location=PICK_SOURCE)}")
        print(
            "Trolley location after pick: "
            f"{get_location_state(laboratory_model_url=DEFAULT_LABORATORY_MODEL_URL, location=TROLLEY_LOCATION)}"
        )

        feature.Place(LocationSpecifier=PLACE_DESTINATION)
        print(
            "Destination after place: "
            f"{get_location_state(laboratory_model_url=DEFAULT_LABORATORY_MODEL_URL, location=PLACE_DESTINATION)}"
        )

        wait_for_observable(feature.Reset(), label="TrolleyArmProvider.Reset", timeout_seconds=args.timeout)
        print(f"Status after reset: {feature.Status.get()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
