"""FastAPI application entry point."""

import logging
from contextlib import AsyncExitStack, asynccontextmanager
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
from benchbase.mcp_server import mcp, setup_mcp

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
        if path.startswith("/api") or path.startswith("/mcp") or path.startswith("/sse"):
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
    import asyncio

    from benchbase.batch_scheduler import resume_queue
    from benchbase.controls import ensure_control_models, get_scorer_status_map, run_controls
    from benchbase.db.models import RunTier
    from benchbase.db.session import get_session_factory
    from benchbase.run_controller import reset_all_run_tracking

    async with AsyncExitStack() as stack:
        await stack.enter_async_context(mcp.session_manager.run())
        reset_all_run_tracking()
        await init_db()
        factory = get_session_factory()
        async with factory() as db:
            await ensure_control_models(db)
            await db.commit()
            status = await get_scorer_status_map(db)
            needs = any(v == "unknown" for k, v in status.items() if k != "speed")

        async def _boot_controls() -> None:
            if not needs:
                return
            logging.getLogger(__name__).info(
                "No control results for current suite versions — running null/random/echo (smoke)"
            )
            try:
                async with factory() as db:
                    await run_controls(db, tier=RunTier.SMOKE)
            except Exception:
                logging.getLogger(__name__).exception("Boot-time controls failed")

        asyncio.create_task(_boot_controls())
        await resume_queue()
        from benchbase.litellm_watch import start_sticky_watch, stop_sticky_watch

        start_sticky_watch()
        try:
            yield
        finally:
            await stop_sticky_watch()


app = FastAPI(
    title="BenchBase",
    description=(
        "Local LLM Benchmark Dashboard API. Orchestrates speed, coding, tool-use, "
        "and reasoning benchmarks against LiteLLM-backed models. MCP tools are "
        "available at /mcp (dual-era Streamable HTTP) and /sse (legacy HTTP+SSE)."
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
    expose_headers=["Mcp-Session-Id"],
)

app.include_router(benchmarks.router, prefix="/api/benchmarks", tags=["benchmarks"])
app.include_router(results.router, prefix="/api/results", tags=["results"])
app.include_router(models.router, prefix="/api/models", tags=["models"])
app.include_router(settings.router, prefix="/api/settings", tags=["settings"])
app.include_router(arena.router, prefix="/api/arena", tags=["arena"])

setup_mcp(app)

if FRONTEND_DIR.is_dir():
    app.mount("/", SPAStaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
