## Run the SiLA2 server with Docker Compose

Prerequisites: Docker and Docker Compose.

Build and start the server:
```bash
docker compose up --build
```

The server listens on `0.0.0.0:50052` by default. To change the port, edit `docker-compose.yml` (`ports` mapping and `--port` argument).

Stop the server:
```bash
docker compose down
```

## Discover reachable SiLA2 servers

Use the helper script to list servers via SiLA discovery:
```bash
python list_sila_servers.py --timeout 5 --insecure
```
- `--timeout <seconds>` controls how long to listen before printing (0 = immediate).
- Use `--insecure` if servers are started with `--insecure` (as in the default compose setup).

The script prints each discovered server’s name, type, UUID, and address:port, or “No SiLA2 servers found.” if none are discovered. Ensure your servers are running with discovery enabled (do not use `--disable-discovery`).
