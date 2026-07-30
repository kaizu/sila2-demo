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
  Startup configuration such as the initial laboratory model state file.
- `external/`
  Reference code and external sources that are not the direct development target.

## Laboratory model

The `laboratory_model` service is shared by all SiLA2 servers in Docker Compose.

- Each location is identified by a string such as `station:1` or `centrifuge:1`.
- A location can hold at most one item.
- Each location also has an `accessible` flag.
- Some instrument commands require an item to be present at the configured location.
- Thermal cycler lid open/close and centrifuge door open/close update location accessibility.
- Trolley arm `Pick` and `Place` are modeled as moves through the trolley arm's own location.

The service loads startup state from `config/laboratory_model.initial_state.json`.

## Unit tests

Component-level tests that need no Docker: they exercise the code in process and finish in
under a second. Run them from the repository root.

```bash
uv run pytest
```

They currently cover `laboratory_model` only (world rules, HTTP contract, startup seeding).
Tests live next to the component they cover, in `laboratory_model/tests/`; the dependencies
and pytest configuration are in the root `pyproject.toml`.

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

`run_roundabout.py` prepares one item at `station:1`, then moves it through:

- `seal-remover:1`
- `plateloc:1`
- `thermal-cycler:1`
- `centrifuge:1`
- back to `station:1`

The movement itself is done through the SiLA2 servers directly. The laboratory model is used only for initial setup and final verification.

## Note on container networking

From the host, reach each SiLA2 server on its published port (`localhost:50052`–`50057`) and the laboratory model on `localhost:8001`. For container-to-container access inside Docker Compose, use the service's container name and its internal port (`50052` for SiLA2 servers, `8001` for `laboratory-model`); the host-published ports `50053`–`50057` are for host access and are not meant to be used verbatim from inside another container.
