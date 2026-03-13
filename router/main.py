"""Arcus Router – dynamic reverse proxy for managed subdomains.

Role-based routing:
* normal – Arcus-branded interstitial; cookie (_arcus_pass) or ?_arcus_skip=1 bypasses it.
* pro / admin – proxied directly, no interstitial.

Supports HTTP/HTTPS and WebSocket (bidirectional asyncio tunnel).

Note on tests: SQLite+aiosqlite is used in the test suite for speed/portability.
"""

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, Response, WebSocket, status
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s – %(message)s",
)
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://arcus:arcus@postgres:5432/arcus")
BASE_DOMAIN = os.getenv("BASE_DOMAIN", "bigalan.dev")


def _load_configured_domains() -> list[str]:
    """Return the list of managed domains.

    Reads from the DOMAINS env var (JSON array of objects with a "domain" key)
    when set; falls back to BASE_DOMAIN for single-domain deployments.
    """
    domains_json = os.getenv("DOMAINS", "").strip()
    if domains_json:
        parsed: list[dict] = json.loads(domains_json)
        return [d["domain"] for d in parsed]
    return [BASE_DOMAIN]


CONFIGURED_DOMAINS: list[str] = _load_configured_domains()

engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

_http_client: httpx.AsyncClient | None = None
_CLIENT_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=30.0, pool=5.0)

_PASS_COOKIE = "_arcus_pass"
_SKIP_PARAM  = "_arcus_skip"


@asynccontextmanager
async def lifespan(application: FastAPI):
    global _http_client
    _http_client = httpx.AsyncClient(follow_redirects=False, timeout=_CLIENT_TIMEOUT)
    logger.info("Router started – configured domains: %s", CONFIGURED_DOMAINS)
    yield
    await _http_client.aclose()
    await engine.dispose()


app = FastAPI(title="Arcus Router", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_slug(host: str) -> tuple[str, str] | None:
    """Return ``(slug, domain)`` for a recognised subdomain host, else ``None``.

    Checks against all configured domains so multi-domain deployments work
    transparently.
    """
    host = host.split(":")[0].lower().strip()
    for base_domain in CONFIGURED_DOMAINS:
        suffix = f".{base_domain}"
        if host.endswith(suffix):
            slug = host[: -len(suffix)]
            if slug and "." not in slug:
                return slug, base_domain
    return None


async def _get_origin(slug: str, domain: str) -> tuple[str, int, str] | None:
    """Return (origin_host, origin_port, role) or None."""
    async with SessionLocal() as session:
        result = await session.execute(
            text(
                "SELECT s.origin_host, s.origin_port, u.role "
                "FROM subdomains s "
                "JOIN users u ON u.id = s.user_id "
                "WHERE s.slug = :slug AND s.domain = :domain AND s.active = TRUE "
                "AND s.origin_host IS NOT NULL AND s.origin_port IS NOT NULL"
            ),
            {"slug": slug, "domain": domain},
        )
        row = result.one_or_none()
    if row is None:
        return None
    return row.origin_host, row.origin_port, row.role


# ---------------------------------------------------------------------------
# Interstitial
# ---------------------------------------------------------------------------

_INTERSTITIAL_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Hosted on Arcus \u2013 {base_domain}</title>
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
          background:#0f172a;color:#e2e8f0;min-height:100vh;
          display:flex;align-items:center;justify-content:center}}
    .card{{background:#1e293b;border-radius:12px;padding:2.5rem;
           max-width:440px;width:90%;text-align:center;
           box-shadow:0 25px 50px rgba(0,0,0,.4)}}
    .logo{{font-size:2.5rem;font-weight:800;color:#38bdf8;letter-spacing:-1px}}
    .tagline{{color:#94a3b8;font-size:.875rem;margin-top:.25rem}}
    .msg{{margin:1.5rem 0;line-height:1.7;color:#cbd5e1}}
    .slug{{color:#38bdf8;font-weight:600}}
    .cta{{display:inline-block;background:#38bdf8;color:#0f172a;
          font-weight:700;padding:.75rem 2rem;border-radius:8px;
          text-decoration:none;margin-top:.5rem;transition:background .2s}}
    .cta:hover{{background:#7dd3fc}}
    .note{{margin-top:1.5rem;font-size:.78rem;color:#475569}}
    .note a{{color:#38bdf8;text-decoration:none}}
  </style>
</head>
<body>
  <div class="card">
    <div class="logo">Arcus</div>
    <div class="tagline">{base_domain}</div>
    <div class="msg">
      <strong class="slug">{slug}.{base_domain}</strong> is hosted on Arcus.<br>
      You are about to be redirected to this site.
    </div>
    <a href="?{skip_param}=1" class="cta">Continue to site &rarr;</a>
    <div class="note">
      Want to remove this notice?
      <a href="https://{base_domain}">Upgrade to Pro</a>
    </div>
  </div>
</body>
</html>
"""


def _interstitial(slug: str, base_domain: str) -> HTMLResponse:
    html = _INTERSTITIAL_TEMPLATE.format(
        slug=slug, base_domain=base_domain, skip_param=_SKIP_PARAM,
    )
    return HTMLResponse(content=html, status_code=200)


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
    result = _extract_slug(host)
    if result is None:
        await websocket.close(code=1008)
        return

    slug, domain = result
    row = await _get_origin(slug, domain)
    if row is None:
        await websocket.close(code=1008)
        return

    origin_host, origin_port, _role = row
    await websocket.accept()

    try:
        reader, writer = await asyncio.open_connection(origin_host, origin_port)
    except OSError as exc:
        logger.error("WS connect failed %s:%d – %s", origin_host, origin_port, exc)
        await websocket.close(code=1011)
        return

    qs = websocket.query_string.decode()
    request_line = f"GET /{path}{'?' + qs if qs else ''} HTTP/1.1\r\n"
    upgrade_headers = (
        f"Host: {host}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {websocket.headers.get('sec-websocket-key', '')}\r\n"
        f"Sec-WebSocket-Version: 13\r\n\r\n"
    )
    writer.write((request_line + upgrade_headers).encode())
    await writer.drain()

    async def _c2o():
        try:
            while True:
                data = await websocket.receive_bytes()
                writer.write(data)
                await writer.drain()
        except Exception:
            pass
        finally:
            writer.close()

    async def _o2c():
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

    await asyncio.gather(_c2o(), _o2c(), return_exceptions=True)


# ---------------------------------------------------------------------------
# HTTP proxy (catch-all)
# ---------------------------------------------------------------------------

@app.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
)
async def http_proxy(request: Request, path: str):
    host = request.headers.get("host", "")
    result = _extract_slug(host)

    if result is None:
        return JSONResponse({"detail": "Not found."}, status_code=status.HTTP_404_NOT_FOUND)

    slug, domain = result
    row = await _get_origin(slug, domain)
    if row is None:
        return JSONResponse(
            {"detail": f"No active origin configured for '{slug}.{domain}'."},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    origin_host, origin_port, role = row

    skip_via_param  = _SKIP_PARAM in request.query_params
    skip_via_cookie = request.cookies.get(_PASS_COOKIE) == slug

    if role == "normal" and not skip_via_cookie and not skip_via_param:
        return _interstitial(slug, domain)

    # Strip the internal skip param before forwarding upstream.
    query_parts = [
        f"{k}={v}"
        for k, v in request.query_params.multi_items()
        if k != _SKIP_PARAM
    ]
    qs = "&".join(query_parts)
    target_url = f"http://{origin_host}:{origin_port}/{path}"
    if qs:
        target_url += f"?{qs}"

    headers = dict(request.headers)
    headers.pop("host", None)
    headers["x-forwarded-host"] = host
    client_ip = request.client.host if request.client else ""
    existing_xff = headers.get("x-forwarded-for", "")
    headers["x-forwarded-for"] = (
        f"{existing_xff}, {client_ip}".lstrip(", ") if client_ip else existing_xff
    )
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
        logger.error("Connect error %s:%d – %s", origin_host, origin_port, exc)
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

    excluded = {"transfer-encoding", "connection"}
    response_headers = {
        k: v for k, v in upstream.headers.items() if k.lower() not in excluded
    }

    # Set the pass cookie when the visitor used the skip param.
    if skip_via_param and role == "normal":
        response_headers["set-cookie"] = (
            f"{_PASS_COOKIE}={slug}; Path=/; Max-Age=3600; SameSite=Lax"
        )

    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=response_headers,
    )
