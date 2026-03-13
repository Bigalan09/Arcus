"""Arcus API – application entry point."""

import logging

from fastapi import FastAPI
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from api.routes import admin, credits, subdomains, users

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s – %(message)s",
)

app = FastAPI(
    title="Arcus",
    description="Subdomain-as-a-Service platform for thesoftware.dev",
    version="1.0.0",
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(users.router)
app.include_router(credits.router)
app.include_router(subdomains.router)
app.include_router(admin.router)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/health", tags=["ops"], summary="Health check")
async def health():
    """Returns 200 OK when the service is running."""
    return JSONResponse({"status": "ok"})
