# Arcus

[![CI](https://github.com/Bigalan09/Arcus/actions/workflows/ci.yml/badge.svg)](https://github.com/Bigalan09/Arcus/actions/workflows/ci.yml)

Arcus is an open-source subdomain-as-a-service platform.
It lets you sell and manage customer subdomains on your own base domain, then proxy traffic to each customer origin.

## Features

- Credit-based subdomain purchases
- Per-subdomain origin routing
- JWT auth, API tokens, admin endpoints, and webhooks
- Cloudflare DNS integration
- Traefik edge TLS with Let's Encrypt

## Stack

- `api`: FastAPI control plane
- `router`: FastAPI reverse proxy for wildcard subdomains
- `postgres`: data store
- `traefik`: edge ingress and TLS termination

## Quick start

### 1) Prerequisites

- Docker 24+
- Docker Compose V2
- Cloudflare zone + token (`Zone:DNS:Edit`)

### 2) Configure environment

```bash
cp .env.example .env
```

Set at least:

- `CLOUDFLARE_API_TOKEN`
- `CLOUDFLARE_ZONE_ID`
- `BASE_DOMAIN`
- `JWT_SECRET_KEY`
- `POSTGRES_PASSWORD`

### 3) Run locally (API + router ports exposed)

```bash
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d --build
```

Useful URLs:

- API docs: [http://localhost:8000/docs](http://localhost:8000/docs)
- API health: [http://localhost:8000/health](http://localhost:8000/health)
- Router health: [http://localhost:8001/health](http://localhost:8001/health)

### 4) Stop

```bash
docker compose -f docker-compose.yml -f docker-compose.local.yml down
```

## API quick flow

Create user:

```bash
curl -s -X POST http://localhost:8000/users \
  -H "Content-Type: application/json" \
  -d '{"email":"alice@example.com"}' | jq
```

Grant credits:

```bash
curl -s -X POST http://localhost:8000/credits/grant \
  -H "Content-Type: application/json" \
  -d '{"user_id":"<user_id>","amount":5}' | jq
```

Purchase subdomain:

```bash
curl -s -X POST http://localhost:8000/subdomains/purchase \
  -H "Content-Type: application/json" \
  -d '{"user_id":"<user_id>","slug":"myapp"}' | jq
```

Set origin:

```bash
curl -s -X POST http://localhost:8000/subdomains/myapp/origin \
  -H "Content-Type: application/json" \
  -d '{"origin_host":"203.0.113.10","origin_port":8080}' | jq
```

## Testing

Run unit/integration tests:

```bash
pytest
```

Run Docker E2E tests:

```bash
docker compose -f docker-compose.e2e.yml up --build --abort-on-container-exit
docker compose -f docker-compose.e2e.yml down -v
```

## Security defaults

- Private and loopback origin IP ranges are blocked
- DNS resolution checks prevent private-network origin bypass
- Edge rate limiting is enforced by Traefik

## Arcus vs Coolify

[Coolify](https://coolify.io) is a self-hosted Platform-as-a-Service (PaaS) that lets you deploy full
applications (Node, PHP, Python, Docker images, databases, etc.) to your own servers — the open-source
alternative to Heroku/Netlify/Vercel.

Arcus solves a different, complementary problem: **subdomain-as-a-service**.

| | Arcus | Coolify |
|---|---|---|
| **Primary purpose** | Sell & route customer subdomains on your own base domain | Deploy & manage full applications on your own servers |
| **What it manages** | DNS records, TLS edge, per-subdomain origin routing | Servers, Docker containers, databases, networking |
| **Target user** | SaaS builders who want to offer `<customer>.yourdomain.com` | Developers who want to self-host their apps |
| **DNS provider** | Cloudflare (built-in API integration) | Delegated to the user / cloud provider |
| **Billing model** | Credit-based subdomain purchases (built in) | Not applicable |
| **Reverse proxy** | Traefik (wildcard TLS, per-subdomain routing) | Traefik or Caddy (per-app routing) |
| **Auth surface** | JWT + API tokens for your control plane | Web UI sessions for the operator |
| **Webhooks** | Yes — lifecycle events for subdomain changes | Yes — deploy hooks |
| **Language/stack** | Python / FastAPI | PHP / Laravel |

**In short:** Use Coolify when you want to host your own apps. Use Arcus when you want to
*sell or assign subdomains* to your own customers and proxy their traffic — a use-case Coolify
does not address.

The two tools can work side-by-side: Coolify can host the applications that Arcus routes traffic
to via customer subdomains.

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md).
