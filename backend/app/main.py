"""FastAPI Application Entry Point.

Configures the app, lifespan, CORS, and includes all route modules.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import close_db, init_db
from .temporal_adapter import close_temporal_client, init_temporal_client

# Ensure node types are registered at import time
import workflow.nodes.base  # noqa: F401
import workflow.nodes.agents  # noqa: F401

logger = logging.getLogger("workflow.app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage Temporal client and database lifecycle."""
    await init_db()
    await init_temporal_client()

    # Warn about optional integrations
    from workflow.config import FIGMA_TOKEN
    if not FIGMA_TOKEN:
        logger.warning(
            "FIGMA_TOKEN not set — /api/v2/design/run-spec endpoint will be unavailable. "
            "Set FIGMA_TOKEN in .env or environment to enable Figma integration."
        )

    yield
    await close_temporal_client()
    await close_db()


app = FastAPI(title="工作流操作台 API", version="2.0.0", lifespan=lifespan)

# CORS configuration — configurable via CORS_ORIGINS env var (comma-separated)
_default_origins = "http://localhost:3000,http://127.0.0.1:3000"
CORS_ORIGINS = [
    o.strip() for o in os.getenv("CORS_ORIGINS", _default_origins).split(",") if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
from .sse import router as sse_router  # noqa: E402
from .routes.workflows import router as workflows_router  # noqa: E402
from .routes.execution import router as execution_router  # noqa: E402
from .routes.validation import router as validation_router  # noqa: E402
from .routes.templates import router as templates_router  # noqa: E402
from .routes.batch import router as batch_router  # noqa: E402
from .routes.jira import router as jira_router  # noqa: E402
from .routes.filesystem import router as filesystem_router  # noqa: E402
from .routes.workspace import router as workspace_router  # noqa: E402
from .routes.design import router as design_router  # noqa: E402

app.include_router(sse_router)
app.include_router(workflows_router)
app.include_router(execution_router)
app.include_router(validation_router)
app.include_router(templates_router)
app.include_router(batch_router)
app.include_router(jira_router)
app.include_router(filesystem_router)
app.include_router(workspace_router)
app.include_router(design_router)


@app.get("/health")
async def health_check():
    """Health check endpoint for container orchestration."""
    return {"status": "ok"}
