"""Smoke test for the Station mock, driven over SiLA2 directly.

The Station is the minimal Provider of the six: no physical effect on the laboratory
model (so nothing to seed here) and only a Status property plus a Reset command. What it
does exercise is the error-recovery path -- the mock deliberately boots into Error (3) as
a debugging fixture, so a client can practise recovering without having to provoke a real
failure. This sample walks exactly that path: read the status, Reset, read it again.

Because Reset is what clears the boot Error, the "before" reading is Error (3) only on the
first run against a freshly started server; on a repeat run against the same container it
already reads Idle (1). Both are expected -- the sample asserts nothing about it, it just
prints the two readings.

Prerequisite: the compose stack is up. Exit code 0 means the sequence passed.
"""

from __future__ import annotations

from common import build_parser, connect, print_server_identity, wait_for_observable

# Host-side port published by docker-compose for this server. No laboratory model options:
# this server does not touch the world.
DEFAULT_PORT = 50056


def main() -> int:
    parser = build_parser("Smoke test the Station SiLA2 server directly.", DEFAULT_PORT)
    args = parser.parse_args()

    with connect(args.host, args.port, insecure=args.insecure) as client:
        print_server_identity(client, host=args.host, port=args.port)

        # Reading before the reset: Error (3) on a freshly started server (see above).
        feature = client.StationProvider
        status_before = feature.Status.get()
        print(f"Status before reset: {status_before}")

        # The recovery step under test.
        wait_for_observable(feature.Reset(), label="StationProvider.Reset", timeout_seconds=args.timeout)

        # Reading after the reset: expected to be Idle (1) regardless of where it started.
        status_after = feature.Status.get()
        print(f"Status after reset: {status_after}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
