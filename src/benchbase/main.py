"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send
from fastapi import FastAPI, Request

logging.basicConfig(level=logging.INFO)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from benchbase.api.routes import benchmarks, models, results, settings, arena
from benchbase.db.session import init_db
from benchbase.mcp_server import setup_mcp

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"

OPENAPI_TAGS = [
    {
        "name": "benchmarks",
        "description": "Create, start, cancel, and batch benchmark runs; list suites.",
    },
    {
        "name": "models",
        "description": "Discover and health-check LiteLLM models; manage model registry.",
    },
    {
        "name": "results",
        "description": "Query run results, compare runs, and model scorecards.",
    },
    {
        "name": "settings",
        "description": "LiteLLM connection, sample sizes, and UI preferences.",
    },
    {
        "name": "arena",
        "description": "Send the same prompt to multiple models (chat or SSE stream).",
    },
]


class SPAStaticFiles(StaticFiles):
    """Serve static files with SPA fallback to index.html."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await super().__call__(scope, receive, send)
            return

        path = scope.get("path", "/")
        if path.startswith("/api"):
            response = JSONResponse({"detail": "Not Found"}, status_code=404)
            await response(scope, receive, send)
            return

        if scope["method"] == "GET":
            try:
                await super().__call__(scope, receive, send)
                return
            except Exception:
                scope["path"] = "/"
                await super().__call__(scope, receive, send)
                return

        response = Response(status_code=405)
        await response(scope, receive, send)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from benchbase.run_controller import reset_all_run_tracking

    reset_all_run_tracking()
    await init_db()
    yield


app = FastAPI(
    title="BenchBase",
    description=(
        "Local LLM Benchmark Dashboard API. Orchestrates speed, coding, tool-use, "
        "and reasoning benchmarks against LiteLLM-backed models. MCP tools are "
        "available at /mcp (Streamable HTTP)."
    ),
    version="0.1.0",
    lifespan=lifespan,
    openapi_tags=OPENAPI_TAGS,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(benchmarks.router, prefix="/api/benchmarks", tags=["benchmarks"])
app.include_router(results.router, prefix="/api/results", tags=["results"])
app.include_router(models.router, prefix="/api/models", tags=["models"])
app.include_router(settings.router, prefix="/api/settings", tags=["settings"])
app.include_router(arena.router, prefix="/api/arena", tags=["arena"])

setup_mcp(app)

if FRONTEND_DIR.is_dir():
    app.mount("/", SPAStaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
