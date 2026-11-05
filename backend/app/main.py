from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session

from . import llm
from .config import get_settings
from .db import engine, init_db
from .nexconn import nexconn
from .routers import auth, chat, dev, market, requests, support, voice
from .services import bootstrap

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("mandilink")
settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    with Session(engine) as session:
        await bootstrap(session)
    mode = "DEMO MODE (no Nexconn credentials)" if nexconn.demo_mode else f"Nexconn {settings.nexconn_api_host}"
    log.info("MandiLink ready · chat: %s · AI: %s", mode, settings.llm_provider if llm.enabled() else "templates")
    yield
    await nexconn.close()


app = FastAPI(title="MandiLink API", version="2.0.0", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (auth.router, market.router, requests.router, chat.router, support.router, voice.router, dev.router):
    app.include_router(r)


@app.get("/api/health")
def health():
    return {"ok": True, "demoMode": nexconn.demo_mode, "ai": llm.enabled(), "aiProvider": settings.llm_provider}


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception):
    log.exception("Unhandled error: %s", exc)
    return JSONResponse(status_code=500, content={"detail": "Something went wrong. Please try again."})


# ---- Serve the built frontend (single-service deploy). /api/* stays the API.
DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        candidate = DIST / full_path
        if full_path and candidate.is_file() and DIST in candidate.resolve().parents:
            return FileResponse(candidate)
        return FileResponse(DIST / "index.html")
