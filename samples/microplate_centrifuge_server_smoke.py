from __future__ import annotations

from common import (
    DEFAULT_LABORATORY_MODEL_URL,
    build_parser,
    connect,
    ensure_item_at_location,
    print_server_identity,
    wait_for_observable,
)


DEFAULT_PORT = 50052
DEFAULT_LOCATION = "centrifuge:1"


def main() -> int:
    parser = build_parser("Smoke test the Microplate Centrifuge SiLA2 server directly.", DEFAULT_PORT)
    parser.add_argument(
        "--laboratory-model-url",
        default=DEFAULT_LABORATORY_MODEL_URL,
        help="Laboratory model base URL used to seed required test items",
    )
    parser.add_argument(
        "--laboratory-model-location",
        default=DEFAULT_LOCATION,
        help="Laboratory model location required by the centrifuge server",
    )
    args = parser.parse_args()

    seeded_item = ensure_item_at_location(
        laboratory_model_url=args.laboratory_model_url,
        location=args.laboratory_model_location,
    )
    print(f"Seeded laboratory model item: {seeded_item}")

    with connect(args.host, args.port, insecure=args.insecure) as client:
        print_server_identity(client, host=args.host, port=args.port)

        feature = client.MicroplateCentrifugeController
        print(f"Hardware version: {feature.HardwareVersion.get()}")
        print(f"Firmware version: {feature.FirmwareVersion.get()}")
        print(f"Profiles: {feature.EnumerateProfiles()}")

        wait_for_observable(
            feature.OpenDoor(BucketNumber=1),
            label="MicroplateCentrifugeController.OpenDoor",
            timeout_seconds=args.timeout,
        )
        wait_for_observable(
            feature.CloseDoor(),
            label="MicroplateCentrifugeController.CloseDoor",
            timeout_seconds=args.timeout,
        )
        wait_for_observable(
            feature.SpinCycle(
                VelocityPercent=50.0,
                AccelerationPercent=50.0,
                DecelerationPercent=50.0,
                TimerMode=1,
                Time=1,
                BucketNumberToLoad=1,
                BucketNumberToUnload=1,
                GripperOffsetToLoad=8.0,
                GripperOffsetToUnload=8.0,
                PlateHeightToLoad=15.0,
                PlateHeightToUnload=15.0,
                SpeedToLoad=1,
                SpeedToUnload=1,
                OptionsToLoad=0,
                OptionsToUnload=0,
            ),
            label="MicroplateCentrifugeController.SpinCycle",
            timeout_seconds=args.timeout,
        )
        wait_for_observable(
            feature.Reset(),
            label="MicroplateCentrifugeController.Reset",
            timeout_seconds=args.timeout,
        )

        print(f"Status after reset: {feature.Status.get()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
