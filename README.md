## Run the SiLA2 server with Docker Compose

Prerequisites: Docker and Docker Compose.

Build and start the server:
```bash
docker compose up --build -d
```

Services:
- SiLA2 server: `0.0.0.0:50052` by default. To change the port, edit `docker-compose.yml` (`ports` mapping and `--port` argument).
- FastAPI: `0.0.0.0:8000`.

Stop the server:
```bash
docker compose down
```

## FastAPI endpoints

- Health: `curl http://localhost:8000/health`
- Root: `curl http://localhost:8000/`

- Discover SiLA2 servers (default timeout 5s):  
  `curl "http://localhost:8000/sila/discover"`
  - Customize: `curl "http://localhost:8000/sila/discover?timeout=3&insecure=true"`

- Trigger Reset on a specific SiLA2 server by IP and port (returns immediately after invoking):  
  `curl -X POST "http://localhost:8000/sila/reset?ip=127.0.0.1&port=50052"`  
  - Optional: `insecure=true|false`
