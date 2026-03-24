from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routes import health, sila_discovery


def create_app() -> FastAPI:
    app = FastAPI(title="Station API", version="0.1.0")
    app.include_router(health.router)
    app.include_router(sila_discovery.router, prefix="/sila", tags=["sila"])
    return app


app = create_app()
app.add_middleware(
    CORSMiddleware,
    allow_origins = ['http://localhost:5173'],
    allow_credentials = True,
    allow_methods = ["*"],
    allow_headers = ["*"],
)

@app.get("/")
def read_root():
    return {"status": "ok"}
