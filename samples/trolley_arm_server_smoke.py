"""Smoke test for the Trolley Arm mock, driven over SiLA2 directly.

The trolley arm is the only server that *moves* items, so this sample is where transport
is checked in isolation. Two things are exercised:

* the rail position, a settable/readable property, moved one step and put back;
* a Pick/Place transfer, which in the world model is two hops rather than one: Pick moves
  the item from the source to the arm's own location, and Place moves it from there to the
  destination. The intermediate reading below is what makes that two-phase shape visible.

Pick, Place and SetTrolleyPosition are unobservable commands, so there is nothing to poll
to completion -- they have returned by the time the call comes back, and their effect is
confirmed by reading the world model afterwards. Only Reset is observable.

Prerequisite: the compose stack is up. Exit code 0 means the sequence passed.
"""

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

# Host-side port published by docker-compose for this server. The transfer runs between two
# plain station spots, chosen so it depends on no instrument being in any particular state;
# TROLLEY_LOCATION is the arm's own location (--laboratory-model-location in
# docker-compose.yml), i.e. the spot an item occupies while it is being carried.
DEFAULT_PORT = 50057
PICK_SOURCE = "station:1"
TROLLEY_LOCATION = "trolley-arm:1"
PLACE_DESTINATION = "station:2"


def main() -> int:
    parser = build_parser("Smoke test the Trolley Arm SiLA2 server directly.", DEFAULT_PORT)
    parser.add_argument(
        "--laboratory-model-url",
        default=DEFAULT_LABORATORY_MODEL_URL,
        help="Laboratory model base URL used to seed and inspect the transferred item",
    )
    args = parser.parse_args()

    with connect(args.host, args.port, insecure=args.insecure) as client:
        print_server_identity(client, host=args.host, port=args.port)

        # Arrange the world: wipe it, then place one item at the source so the transfer has
        # something to carry. (Done after connecting, unlike the instrument samples, only
        # because nothing here needs the world before the client exists.)
        feature = client.TrolleyArmProvider
        reset_laboratory_model(laboratory_model_url=args.laboratory_model_url)
        add_item_to_location(laboratory_model_url=args.laboratory_model_url, location=PICK_SOURCE)

        # Rail position: step off the current position and back again. Restoring it means
        # this sample leaves the arm exactly as it found it, so it can be re-run against a
        # long-lived server. The position is read back each time because SetTrolleyPosition
        # is unobservable -- the property is the only evidence it took effect.
        original_position = feature.TrolleyPosition.get()
        print(f"Original trolley position: {original_position}")

        temporary_position = original_position + 1
        feature.SetTrolleyPosition(Position=temporary_position)
        print(f"Trolley position after move: {feature.TrolleyPosition.get()}")

        feature.SetTrolleyPosition(Position=original_position)
        print(f"Trolley position restored: {feature.TrolleyPosition.get()}")

        # Pick: the source should now be empty and the item should be sitting on the arm.
        # Both ends are printed because it is the pair that shows the hop actually happened.
        feature.Pick(LocationSpecifier=PICK_SOURCE)
        print(
            "Source after pick: "
            f"{get_location_state(laboratory_model_url=args.laboratory_model_url, location=PICK_SOURCE)}"
        )
        print(
            "Trolley location after pick: "
            f"{get_location_state(laboratory_model_url=args.laboratory_model_url, location=TROLLEY_LOCATION)}"
        )

        # Place: the item leaves the arm for the destination, completing the transfer.
        feature.Place(LocationSpecifier=PLACE_DESTINATION)
        print(
            "Destination after place: "
            f"{get_location_state(laboratory_model_url=args.laboratory_model_url, location=PLACE_DESTINATION)}"
        )

        # Reset returns the arm to Idle. The item is deliberately left at the destination:
        # every sample wipes the world on entry, so there is nothing to clean up here.
        wait_for_observable(feature.Reset(), label="TrolleyArmProvider.Reset", timeout_seconds=args.timeout)
        print(f"Status after reset: {feature.Status.get()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
