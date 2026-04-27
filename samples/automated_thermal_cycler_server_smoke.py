from __future__ import annotations

from common import build_parser, connect, print_server_identity, wait_for_observable


DEFAULT_PORT = 50055


def main() -> int:
    parser = build_parser("Smoke test the Automated Thermal Cycler SiLA2 server directly.", DEFAULT_PORT)
    args = parser.parse_args()

    with connect(args.host, args.port, insecure=args.insecure) as client:
        print_server_identity(client, host=args.host, port=args.port)

        feature = client.AutomatedThermalCyclerController
        print(f"Initial instrument state: {feature.GetInstrumentState()}")

        wait_for_observable(
            feature.Load(ProtocolFileData=b"mock protocol"),
            label="AutomatedThermalCyclerController.Load",
            timeout_seconds=args.timeout,
        )
        wait_for_observable(
            feature.Validate(MaxSampleVolume=10.0),
            label="AutomatedThermalCyclerController.Validate",
            timeout_seconds=args.timeout,
        )
        wait_for_observable(
            feature.OpenLid(),
            label="AutomatedThermalCyclerController.OpenLid",
            timeout_seconds=args.timeout,
        )
        wait_for_observable(
            feature.CloseLid(),
            label="AutomatedThermalCyclerController.CloseLid",
            timeout_seconds=args.timeout,
        )
        wait_for_observable(
            feature.StartRun(),
            label="AutomatedThermalCyclerController.StartRun",
            timeout_seconds=args.timeout,
        )
        print(f"Instrument state after StartRun: {feature.GetInstrumentState()}")
        print(f"Remaining time: {feature.RemainingTime.get()}")

        wait_for_observable(
            feature.StopRun(),
            label="AutomatedThermalCyclerController.StopRun",
            timeout_seconds=args.timeout,
        )
        print(f"Instrument state after StopRun: {feature.GetInstrumentState()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
