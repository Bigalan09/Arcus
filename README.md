# Arcus

Arcus is a minimal, production-sensible subdomain-as-a-service platform.  
Users purchase subdomains under **thesoftware.dev** using credits, point them at their own origin server, and all traffic is transparently reverse-proxied through the platform.

---

## Architecture

```
┌────────────┐    HTTPS    ┌──────────┐   HTTP    ┌──────────────┐
│  Browser   │────────────▶│ Traefik  │──────────▶│   Router     │
└────────────┘             │ (TLS)    │           │  (FastAPI)   │
                           └──────────┘           └──────┬───────┘
                                                         │  DB lookup
                                                    ┌────▼────────┐
                                                    │  PostgreSQL  │
                                                    └─────────────┘
                                                         │  origin
                                                    ┌────▼────────┐
                                                    │ Customer's  │
                                                    │   server    │
                                                    └─────────────┘
```

| Service    | Description                                      |
|------------|--------------------------------------------------|
| `postgres` | Stores users, credits, and subdomain records     |
| `api`      | REST API – user/credit/subdomain management      |
| `router`   | Reverse proxy – routes `*.thesoftware.dev` traffic |
| `traefik`  | Edge load balancer with automatic TLS            |

---

## Prerequisites

- Docker ≥ 24 and Docker Compose V2
- A Cloudflare account with `thesoftware.dev` configured
- A Cloudflare API token with **Zone:DNS:Edit** permission

---

## Environment variables

| Variable               | Required | Default            | Description                          |
|------------------------|----------|--------------------|--------------------------------------|
| `CLOUDFLARE_API_TOKEN` | ✅        | –                  | Cloudflare API token (DNS edit)      |
| `CLOUDFLARE_ZONE_ID`   | ✅        | –                  | Zone ID for `thesoftware.dev`        |
| `BASE_DOMAIN`          | ❌        | `thesoftware.dev`  | Root domain                          |
| `API_SECRET_KEY`       | ❌        | `changeme`         | Signing key (extend for auth)        |
| `POSTGRES_PASSWORD`    | ❌        | `arcus`            | PostgreSQL password                  |

---

## Cloudflare DNS setup

1. Log into the [Cloudflare dashboard](https://dash.cloudflare.com).
2. Select your `thesoftware.dev` zone.
3. Add a **wildcard A record** pointing to your server's public IP:

   | Type | Name               | Content        | Proxy status |
   |------|--------------------|----------------|--------------|
   | A    | `*.thesoftware.dev`| `<your IP>`    | Proxied ✅   |

4. Obtain your **Zone ID** from the zone overview page (right-hand sidebar).
5. Create an API token with *Zone › DNS › Edit* permission.

> Alternatively, leave `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ZONE_ID` set – Arcus will create per-subdomain CNAME records automatically on each purchase.

---

## Setup and deployment

```bash
# 1. Clone and enter the project
git clone https://github.com/Bigalan09/Arcus.git
cd Arcus

# 2. Configure environment
cp .env.example .env
# Edit .env and fill in CLOUDFLARE_API_TOKEN and CLOUDFLARE_ZONE_ID

# 3. Start the full stack
docker compose up -d

# 4. Check everything is healthy
docker compose ps
```

The API is reachable at `https://api.thesoftware.dev` once DNS propagates.  
For local testing, map `127.0.0.1 api.thesoftware.dev` in `/etc/hosts` and use `http://localhost:8000`.

---

## Running tests

Tests use **red/green TDD** and run entirely in-process with a SQLite database – no external dependencies required.

```bash
# Install test dependencies
pip install -r api/requirements.txt
pip install pytest==8.3.2 pytest-asyncio==0.23.8 httpx asgi-lifespan aiosqlite

# Run all tests
pytest
```

---

## API usage

### Create a user

```bash
curl -s -X POST http://localhost:8000/users \
  -H "Content-Type: application/json" \
  -d '{"email": "alice@example.com"}' | jq
```

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "email": "alice@example.com",
  "created_at": "2024-01-01T12:00:00Z"
}
```

---

### Grant credits

```bash
curl -s -X POST http://localhost:8000/credits/grant \
  -H "Content-Type: application/json" \
  -d '{"user_id": "<user_id>", "amount": 5}' | jq
```

```json
{
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "balance": 5
}
```

---

### Purchase a subdomain

```bash
curl -s -X POST http://localhost:8000/subdomains/purchase \
  -H "Content-Type: application/json" \
  -d '{"user_id": "<user_id>", "slug": "myapp"}' | jq
```

```json
{
  "id": "...",
  "user_id": "...",
  "slug": "myapp",
  "origin_host": null,
  "origin_port": null,
  "active": true,
  "created_at": "2024-01-01T12:00:00Z"
}
```

---

### Set the origin server

```bash
curl -s -X POST http://localhost:8000/subdomains/myapp/origin \
  -H "Content-Type: application/json" \
  -d '{"origin_host": "203.0.113.10", "origin_port": 8080}' | jq
```

```json
{
  "id": "...",
  "slug": "myapp",
  "origin_host": "203.0.113.10",
  "origin_port": 8080,
  "active": true,
  ...
}
```

After this, `https://myapp.thesoftware.dev` will proxy traffic to `http://203.0.113.10:8080`.

---

### List your subdomains

```bash
curl -s "http://localhost:8000/subdomains?user_id=<user_id>" | jq
```

---

## Database schema

```
users       – id, email, created_at
credits     – id, user_id (1:1 with users), balance
subdomains  – id, user_id, slug, origin_host, origin_port, active, created_at
```

Migrations are applied automatically by PostgreSQL at first start via `db/migrations/001_initial.sql`.

---

## Security notes

- Private IP ranges (`10.x`, `192.168.x`, `127.x`, `169.254.x`, `172.16–31.x`) are **blocked** as origin hosts.
- All DNS hostnames are resolved at set-time; any address resolving to a private range is rejected.
- Traefik enforces a rate limit of 100 req/s (burst 50) at the edge.
- TLS is terminated by Traefik using Let's Encrypt DNS-01 challenge via Cloudflare.
