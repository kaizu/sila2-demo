## Overview

This repository contains a set of mock SiLA2 instrument servers, a small FastAPI helper application, and a shared `laboratory_model` service used to simulate world state across the servers.

The current Docker Compose setup starts:

- `laboratory-model` on `localhost:8001`
- `fastapi` on `localhost:8000`
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
- `fastapi_app/`
  Helper API for health checks, SiLA discovery, reset, feature definition lookup, and trolley position access.
- `samples/`
  Direct client scripts that use `sila-python` without going through FastAPI.
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

## Direct samples

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

## FastAPI endpoints

Health:

```bash
curl http://localhost:8000/health
```

Root:

```bash
curl http://localhost:8000/
```

Discover servers:

```bash
curl "http://localhost:8000/sila/discover?timeout=3&insecure=true"
```

Trigger reset on a specific server:

```bash
curl -X POST "http://localhost:8000/sila/reset?ip=127.0.0.1&port=50057&insecure=true"
```

Get feature definitions from a specific server:

```bash
curl "http://localhost:8000/sila/feature-definitions?ip=127.0.0.1&port=50057&insecure=true"
```

Get trolley position:

```bash
curl "http://localhost:8000/sila/trolley-position?ip=127.0.0.1&port=50057&insecure=true"
```

Set trolley position:

```bash
curl -X POST "http://localhost:8000/sila/trolley-position?ip=127.0.0.1&port=50057&position=3&insecure=true"
```

## Note on container networking

When FastAPI accesses SiLA2 servers from inside Docker Compose, `127.0.0.1` refers to the FastAPI container itself, not the host-mapped service port. For container-to-container access, use the service's container address and internal port, or rely on discovery results from inside the Compose network.
