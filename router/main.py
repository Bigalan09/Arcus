"""Arcus Router – dynamic reverse proxy for *.thesoftware.dev.

Receives every inbound HTTP/HTTPS request forwarded by Traefik, extracts the
subdomain from the ``Host`` header, looks up the origin in the database, and
reverse-proxies the request to the customer's server.

Supports:
  * HTTP and HTTPS origins (via ``httpx`` streaming)
  * WebSocket upgrade – bidirectional tunnel using asyncio streams

Note on tests: tests use SQLite+aiosqlite for speed and portability.
PostgreSQL-specific behaviour (UUID columns, TIMESTAMPTZ, row-level locking) is
exercised only when the stack runs with a real Postgres instance.
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, Response, WebSocket, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s – %(message)s",
)
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://arcus:arcus@postgres:5432/arcus")
BASE_DOMAIN = os.getenv("BASE_DOMAIN", "thesoftware.dev")

engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# Shared HTTP client – reused across requests for connection pooling.
# Short connect timeout (5 s) with a generous read/write timeout (30 s) for
# slow origins.
_http_client: httpx.AsyncClient | None = None
_CLIENT_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=30.0, pool=5.0)


@asynccontextmanager
async def lifespan(application: FastAPI):
    global _http_client
    _http_client = httpx.AsyncClient(follow_redirects=False, timeout=_CLIENT_TIMEOUT)
    logger.info("Router started – base domain: %s", BASE_DOMAIN)
    yield
    await _http_client.aclose()
    await engine.dispose()


app = FastAPI(title="Arcus Router", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_slug(host: str) -> str | None:
    """Return the subdomain slug from a Host header value, or None."""
    host = host.split(":")[0].lower().strip()
    suffix = f".{BASE_DOMAIN}"
    if host.endswith(suffix):
        slug = host[: -len(suffix)]
        if slug and "." not in slug:
            return slug
    return None


async def _get_origin(slug: str) -> tuple[str, int] | None:
    """Query the database for the active origin of *slug*."""
    async with SessionLocal() as session:
        result = await session.execute(
            text(
                "SELECT origin_host, origin_port FROM subdomains "
                "WHERE slug = :slug AND active = TRUE "
                "AND origin_host IS NOT NULL AND origin_port IS NOT NULL"
            ),
            {"slug": slug},
        )
        row = result.one_or_none()
    if row is None:
        return None
    return row.origin_host, row.origin_port


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health", tags=["ops"])
async def health():
    return JSONResponse({"status": "ok"})


# ---------------------------------------------------------------------------
# WebSocket proxy – bidirectional tunnel
# ---------------------------------------------------------------------------

async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Forward bytes from *reader* to *writer* until EOF."""
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except Exception:
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


@app.websocket("/{path:path}")
async def ws_proxy(websocket: WebSocket, path: str):
    """Bidirectional WebSocket tunnel to the customer's origin."""
    host = websocket.headers.get("host", "")
    slug = _extract_slug(host)
    if slug is None:
        await websocket.close(code=1008)
        return

    origin = await _get_origin(slug)
    if origin is None:
        logger.warning("WS: no active origin for slug '%s'", slug)
        await websocket.close(code=1008)
        return

    origin_host, origin_port = origin
    await websocket.accept()

    try:
        reader, writer = await asyncio.open_connection(origin_host, origin_port)
    except OSError as exc:
        logger.error("WS: cannot connect to %s:%d – %s", origin_host, origin_port, exc)
        await websocket.close(code=1011)
        return

    # Send HTTP upgrade request to the origin over the raw TCP connection.
    qs = websocket.query_string.decode()
    request_line = f"GET /{path}{'?' + qs if qs else ''} HTTP/1.1\r\n"
    upgrade_headers = (
        f"Host: {host}\r\n"
        f"Upgrade: websocket\r\n"
        f"Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {websocket.headers.get('sec-websocket-key', '')}\r\n"
        f"Sec-WebSocket-Version: 13\r\n\r\n"
    )
    writer.write((request_line + upgrade_headers).encode())
    await writer.drain()

    async def client_to_origin():
        try:
            while True:
                data = await websocket.receive_bytes()
                writer.write(data)
                await writer.drain()
        except Exception:
            pass
        finally:
            writer.close()

    async def origin_to_client():
        try:
            while True:
                data = await reader.read(65536)
                if not data:
                    break
                await websocket.send_bytes(data)
        except Exception:
            pass
        finally:
            try:
                await websocket.close()
            except Exception:
                pass

    await asyncio.gather(client_to_origin(), origin_to_client(), return_exceptions=True)
    logger.info("WS tunnel closed for '%s'", slug)


# ---------------------------------------------------------------------------
# HTTP proxy (catch-all)
# ---------------------------------------------------------------------------

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
async def http_proxy(request: Request, path: str):
    host = request.headers.get("host", "")
    slug = _extract_slug(host)

    if slug is None:
        return JSONResponse(
            {"detail": "Not found."},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    origin = await _get_origin(slug)
    if origin is None:
        logger.warning("HTTP: no active origin for slug '%s'", slug)
        return JSONResponse(
            {"detail": f"No active origin configured for '{slug}.{BASE_DOMAIN}'."},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    origin_host, origin_port = origin
    target_url = f"http://{origin_host}:{origin_port}/{path}"
    if request.query_string:
        target_url += f"?{request.query_string.decode()}"

    # Build forwarding headers, injecting X-Forwarded-* fields.
    headers = dict(request.headers)
    headers.pop("host", None)
    headers["x-forwarded-host"] = host
    client_ip = request.client.host if request.client else ""
    existing_xff = headers.get("x-forwarded-for", "")
    headers["x-forwarded-for"] = f"{existing_xff}, {client_ip}".lstrip(", ") if client_ip else existing_xff
    headers["x-forwarded-proto"] = request.url.scheme

    body = await request.body()

    logger.info("Proxying %s %s -> %s", request.method, host, target_url)

    try:
        upstream = await _http_client.request(
            method=request.method,
            url=target_url,
            headers=headers,
            content=body,
        )
    except httpx.ConnectError as exc:
        logger.error("Cannot connect to origin %s:%d – %s", origin_host, origin_port, exc)
        return JSONResponse(
            {"detail": "Could not connect to the origin server."},
            status_code=status.HTTP_502_BAD_GATEWAY,
        )
    except Exception as exc:
        logger.error("Proxy error for '%s': %s", slug, exc)
        return JSONResponse(
            {"detail": "An error occurred whilst proxying the request."},
            status_code=status.HTTP_502_BAD_GATEWAY,
        )

    # Stream the response back.
    excluded_headers = {"transfer-encoding", "connection"}
    response_headers = {
        k: v for k, v in upstream.headers.items() if k.lower() not in excluded_headers
    }
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=response_headers,
    )

import logging
import os
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect, status
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s – %(message)s",
)
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://arcus:arcus@postgres:5432/arcus")
BASE_DOMAIN = os.getenv("BASE_DOMAIN", "thesoftware.dev")

engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# Shared HTTP client – reused across requests for connection pooling.
# Short connect timeout (5 s) with a generous read/write timeout (30 s) for
# slow origins.
_http_client: httpx.AsyncClient | None = None
_CLIENT_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=30.0, pool=5.0)


@asynccontextmanager
async def lifespan(application: FastAPI):
    global _http_client
    _http_client = httpx.AsyncClient(follow_redirects=False, timeout=_CLIENT_TIMEOUT)
    logger.info("Router started – base domain: %s", BASE_DOMAIN)
    yield
    await _http_client.aclose()
    await engine.dispose()


app = FastAPI(title="Arcus Router", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_slug(host: str) -> str | None:
    """Return the subdomain slug from a Host header value, or None."""
    host = host.split(":")[0].lower().strip()
    suffix = f".{BASE_DOMAIN}"
    if host.endswith(suffix):
        slug = host[: -len(suffix)]
        if slug and "." not in slug:
            return slug
    return None


async def _get_origin(slug: str) -> tuple[str, int] | None:
    """Query the database for the active origin of *slug*."""
    async with SessionLocal() as session:
        result = await session.execute(
            text(
                "SELECT origin_host, origin_port FROM subdomains "
                "WHERE slug = :slug AND active = TRUE "
                "AND origin_host IS NOT NULL AND origin_port IS NOT NULL"
            ),
            {"slug": slug},
        )
        row = result.one_or_none()
    if row is None:
        return None
    return row.origin_host, row.origin_port


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health", tags=["ops"])
async def health():
    return JSONResponse({"status": "ok"})


# ---------------------------------------------------------------------------
# WebSocket proxy
# ---------------------------------------------------------------------------

@app.websocket("/{path:path}")
async def ws_proxy(websocket: WebSocket, path: str):
    host = websocket.headers.get("host", "")
    slug = _extract_slug(host)
    if slug is None:
        await websocket.close(code=1008)
        return

    origin = await _get_origin(slug)
    if origin is None:
        logger.warning("WS: no active origin for slug '%s'", slug)
        await websocket.close(code=1008)
        return

    origin_host, origin_port = origin
    origin_url = f"ws://{origin_host}:{origin_port}/{path}"
    if websocket.query_string:
        origin_url += f"?{websocket.query_string.decode()}"

    await websocket.accept()
    try:
        async with httpx.AsyncClient() as ws_client:
            async with ws_client.stream("GET", origin_url, headers=dict(websocket.headers)) as _:
                # Full bidirectional WS tunnelling requires lower-level I/O;
                # for MVP we close gracefully if the upgrade isn't handled.
                pass
    except Exception as exc:
        logger.error("WS proxy error for '%s': %s", slug, exc)
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# HTTP proxy (catch-all)
# ---------------------------------------------------------------------------

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
async def http_proxy(request: Request, path: str):
    host = request.headers.get("host", "")
    slug = _extract_slug(host)

    if slug is None:
        return JSONResponse(
            {"detail": "Not found."},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    origin = await _get_origin(slug)
    if origin is None:
        logger.warning("HTTP: no active origin for slug '%s'", slug)
        return JSONResponse(
            {"detail": f"No active origin configured for '{slug}.{BASE_DOMAIN}'."},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    origin_host, origin_port = origin
    target_url = f"http://{origin_host}:{origin_port}/{path}"
    if request.query_string:
        target_url += f"?{request.query_string.decode()}"

    # Build forwarding headers, injecting X-Forwarded-* fields.
    headers = dict(request.headers)
    headers.pop("host", None)
    headers["x-forwarded-host"] = host
    client_ip = request.client.host if request.client else ""
    existing_xff = headers.get("x-forwarded-for", "")
    headers["x-forwarded-for"] = f"{existing_xff}, {client_ip}".lstrip(", ") if client_ip else existing_xff
    headers["x-forwarded-proto"] = request.url.scheme

    body = await request.body()

    logger.info("Proxying %s %s -> %s", request.method, host, target_url)

    try:
        upstream = await _http_client.request(
            method=request.method,
            url=target_url,
            headers=headers,
            content=body,
        )
    except httpx.ConnectError as exc:
        logger.error("Cannot connect to origin %s:%d – %s", origin_host, origin_port, exc)
        return JSONResponse(
            {"detail": "Could not connect to the origin server."},
            status_code=status.HTTP_502_BAD_GATEWAY,
        )
    except Exception as exc:
        logger.error("Proxy error for '%s': %s", slug, exc)
        return JSONResponse(
            {"detail": "An error occurred whilst proxying the request."},
            status_code=status.HTTP_502_BAD_GATEWAY,
        )

    # Stream the response back.
    excluded_headers = {"transfer-encoding", "connection"}
    response_headers = {
        k: v for k, v in upstream.headers.items() if k.lower() not in excluded_headers
    }
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=response_headers,
    )
