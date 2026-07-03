from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# Allows running this file directly (`python main.py` from app/, or
# `python app/main.py` from the project root) by putting the project root on
# sys.path before any `app.*` absolute import below runs. Without this, only
# `python -m uvicorn app.main:app` run from the project root works.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

import app.db.models  # noqa: F401 — registers tables on Base.metadata before create_all
from app.core.config import get_settings
from app.db.session import create_all_tables
from app.routers import calls, organizations, webhooks

settings = get_settings()
logging.basicConfig(level=settings.log_level)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


@asynccontextmanager
async def lifespan(_: FastAPI):
    await create_all_tables()
    yield


app = FastAPI(title="AI Voice Call Agent Platform", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(organizations.router)
app.include_router(calls.router)
app.include_router(webhooks.router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/")
async def onboarding_ui() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/console")
async def test_console_ui() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "console.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.host, port=settings.port, log_level=settings.log_level.lower())
