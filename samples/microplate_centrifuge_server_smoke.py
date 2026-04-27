from __future__ import annotations

from common import build_parser, connect, print_server_identity, wait_for_observable


DEFAULT_PORT = 50052


def main() -> int:
    parser = build_parser("Smoke test the Microplate Centrifuge SiLA2 server directly.", DEFAULT_PORT)
    args = parser.parse_args()

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
                GripperOffsetToLoad=0.0,
                GripperOffsetToUnload=0.0,
                PlateHeightToLoad=0.0,
                PlateHeightToUnload=0.0,
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
