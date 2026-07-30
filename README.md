[![CI](https://github.com/kaizu/sila2-demo/actions/workflows/ci.yml/badge.svg)](https://github.com/kaizu/sila2-demo/actions/workflows/ci.yml)

## Overview

This repository contains a set of mock SiLA2 instrument servers and a shared `laboratory_model` service used to simulate world state across the servers.

The current Docker Compose setup starts:

- `laboratory-model` on `localhost:8001`
- `sila2-server-1` Microplate Centrifuge on `localhost:50052`
- `sila2-server-2` PlateLoc on `localhost:50053`
- `sila2-server-3` Automated Plate Seal Remover on `localhost:50054`
- `sila2-server-4` Automated Thermal Cycler on `localhost:50055`
- `sila2-server-5` Station on `localhost:50056`
- `trolley-arm-server-1` Trolley Arm on `localhost:50057`

All SiLA2 servers are started with `--insecure` and `--verbose`.

## Start and stop

Prerequisites: Docker and Docker Compose.

Build and start all services:

```bash
docker compose up --build -d
```

Stop all services:

```bash
docker compose down
```

Check running containers:

```bash
docker compose ps
```

Inspect server logs:

```bash
docker compose logs --tail=120
```

## Project layout

- `servers/`
  SiLA2 server packages for each mock instrument.
- `laboratory_model/`
  Shared state service that tracks whether locations contain an item and whether each location is accessible.
- `samples/`
  Direct client scripts that use `sila-python`.
- `specs/`
  Source SiLA feature XML definitions.
- `config/`
  Startup configuration, notably the laboratory model's seed file.
- `external/`
  Reference code and external sources that are not the direct development target.

## Laboratory model

The `laboratory_model` service is shared by all SiLA2 servers in Docker Compose.

The world is organised around devices, each holding a fixed set of spots plus an opaque bag
of state.

- A location is always `device.spot`, such as `station.slot1` or `centrifuge.deck`. There is
  no shorthand where a device name stands in for its only spot.
- The topology is declared by the seed and does not grow at runtime: addressing a device or
  spot that was never declared is a 404, not an empty location.
- A spot can hold at most one item, and has its own `accessible` flag. The model refuses to
  reach into a spot that is not accessible.
- Device `state` is stored verbatim and read by no rule in the service; keys like `lid` mean
  something only to the server that wrote them.
- Some instrument commands require an item to be present at the configured location.
- Thermal cycler lid open/close and centrifuge door open/close update spot accessibility.
- Trolley arm `Pick` and `Place` are modeled as moves through the trolley arm's own spot.

The service reads its t=0 world -- topology, resting device state and initial occupancy --
from `config/laboratory_model.seed.yaml`. `POST /reseed` rereads it; `POST /reset` empties the
world but keeps the topology. See `docs/LABORATORY_MODEL.md`.

## Unit tests

Component-level tests that need no Docker: they exercise the code in process and finish in
under a second. Run them from the repository root.

```bash
uv run pytest
```

They cover `laboratory_model` (world rules, HTTP contract, seeding) and the shared
`laboratory-client` (its HTTP transport and configuration). Tests live next to the component
they cover, in `<component>/tests/`; the dependencies and pytest configuration are in the root
`pyproject.toml`. See `docs/RULES.md` for the policy.

## Lint and type checking

```bash
uv run ruff check .
uv run mypy
```

Both are configured in the root `pyproject.toml` and cover the hand-written code only: the
`generated/` trees and each server's `__main__.py` belong to the sila2 code generator and
are excluded. See `docs/RULES.md` for the policy.

## Direct samples

The scripts below talk to a running stack over the network, so they check the deployment
rather than the rules. Bring the stack up first.

Run all direct smoke tests:

```bash
.venv/bin/python samples/run_all_smoke_tests.py
```

Run the laboratory model smoke test:

```bash
.venv/bin/python samples/laboratory_model_smoke.py
```

Run the trolley arm smoke test:

```bash
.venv/bin/python samples/trolley_arm_server_smoke.py
```

Run the roundabout integration sample:

```bash
.venv/bin/python samples/run_roundabout.py
```

`run_roundabout.py` prepares one item at `station.slot1`, then moves it through:

- `seal-remover.stage`
- `plateloc.stage`
- `thermal-cycler.block`
- `centrifuge.deck`
- back to `station.slot1`

The movement itself is done through the SiLA2 servers directly. The laboratory model is used only for initial setup and final verification.

## Note on container networking

From the host, reach each SiLA2 server on its published port (`localhost:50052`–`50057`) and the laboratory model on `localhost:8001`. For container-to-container access inside Docker Compose, use the service's container name and its internal port (`50052` for SiLA2 servers, `8001` for `laboratory-model`); the host-published ports `50053`–`50057` are for host access and are not meant to be used verbatim from inside another container.
