import sys
from pathlib import Path

# Add backend directory to Python path when running directly
if __name__ == "__main__":
    backend_dir = Path(__file__).parent.parent
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1 import tasks_endpoints, strategy_endpoints, backtesting, common
from app.core.config import CORS_ORIGINS, CORS_ALLOW_METHODS, CORS_ALLOW_HEADERS
from app.core.startup import startup, shutdown


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown events"""
    # Startup - blocks until complete, no requests processed until finished
    startup()
    yield
    # Shutdown
    shutdown()


app = FastAPI(
    title="R2D2 API",
    description="R2D2 Backend API",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware with environment-based configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=CORS_ALLOW_METHODS,
    allow_headers=CORS_ALLOW_HEADERS,
)

# Include routers
app.include_router(tasks_endpoints.router)
app.include_router(strategy_endpoints.router)
app.include_router(backtesting.router)
app.include_router(common.router)


@app.get("/")
async def root():
    return {"message": "Hello from R2D2 API"}


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8202,
        reload=True
    )

