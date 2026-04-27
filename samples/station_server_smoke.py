from __future__ import annotations

from common import build_parser, connect, print_server_identity, wait_for_observable


DEFAULT_PORT = 50056


def main() -> int:
    parser = build_parser("Smoke test the Station SiLA2 server directly.", DEFAULT_PORT)
    args = parser.parse_args()

    with connect(args.host, args.port, insecure=args.insecure) as client:
        print_server_identity(client, host=args.host, port=args.port)

        feature = client.StationProvider
        status_before = feature.Status.get()
        print(f"Status before reset: {status_before}")

        wait_for_observable(feature.Reset(), label="StationProvider.Reset", timeout_seconds=args.timeout)

        status_after = feature.Status.get()
        print(f"Status after reset: {status_after}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
