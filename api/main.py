"""Arcus API – application entry point."""

import logging

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from api.routes import admin, auth, credits, frontend, subdomains, tokens, users, webhooks

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s – %(message)s",
)

app = FastAPI(
    title="Arcus",
    description="Subdomain-as-a-Service platform",
    version="2.0.0",
)

# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------
app.mount("/static", StaticFiles(directory="api/static"), name="static")

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(frontend.router)
app.include_router(auth.router)
app.include_router(tokens.router)
app.include_router(users.router)
app.include_router(credits.router)
app.include_router(subdomains.router)
app.include_router(admin.router)
app.include_router(webhooks.router)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/health", tags=["ops"], summary="Health check")
async def health():
    """Returns 200 OK when the service is running."""
    return JSONResponse({"status": "ok"})
