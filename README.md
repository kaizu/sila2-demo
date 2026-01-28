## Run the SiLA2 server with Docker Compose

Prerequisites: Docker and Docker Compose.

Build and start the server:
```bash
docker compose up --build
```

Services:
- SiLA2 server: `0.0.0.0:50052` by default. To change the port, edit `docker-compose.yml` (`ports` mapping and `--port` argument).
- FastAPI: `0.0.0.0:8000`.

Stop the server:
```bash
docker compose down
```

### Check FastAPI is running
- Health: `curl http://localhost:8000/health`
- Root: `curl http://localhost:8000/`

## FastAPI endpoints

- Discover SiLA2 servers (default timeout 5s):  
  `curl "http://localhost:8000/sila/discover"`
  - Customize: `curl "http://localhost:8000/sila/discover?timeout=3&insecure=true"`

- Trigger Reset on a specific SiLA2 server by name or UUID (returns immediately after invoking):  
  `curl -X POST "http://localhost:8000/sila/reset?server_name=MySila2Server-1"`  
  or  
  `curl -X POST "http://localhost:8000/sila/reset?server_uuid=<UUID>"`  
  - Optional: `timeout` (seconds), `insecure=true|false`
