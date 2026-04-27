from __future__ import annotations

from common import build_parser, connect, print_server_identity, wait_for_observable


DEFAULT_PORT = 50053


def main() -> int:
    parser = build_parser("Smoke test the PlateLoc SiLA2 server directly.", DEFAULT_PORT)
    args = parser.parse_args()

    with connect(args.host, args.port, insecure=args.insecure) as client:
        print_server_identity(client, host=args.host, port=args.port)

        feature = client.PlateLocController
        print(f"Initial sealing temperature: {feature.SealingTemperature.get()}")
        print(f"Initial sealing time: {feature.SealingTime.get()}")
        print(f"Profiles: {feature.EnumerateProfiles()}")

        feature.SetSealingTemperature(SealingTemperature=180)
        feature.SetSealingTime(SealingTime=2.0)
        print(f"Updated sealing temperature: {feature.SealingTemperature.get()}")
        print(f"Updated sealing time: {feature.SealingTime.get()}")

        wait_for_observable(
            feature.StartCycle(),
            label="PlateLocController.StartCycle",
            timeout_seconds=args.timeout,
        )
        print(f"Cycle count after StartCycle: {feature.CycleCount.get()}")

        wait_for_observable(
            feature.Reset(),
            label="PlateLocController.Reset",
            timeout_seconds=args.timeout,
        )
        print(f"Cycle count after reset: {feature.CycleCount.get()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
