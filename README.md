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

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md).
