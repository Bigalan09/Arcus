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
- Cloudflare zone + token (`Zone:DNS:Edit`) for production edge/TLS

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

### 3) Run local development

```bash
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d --build
```

Useful URLs:

- API docs: [http://localhost:8000/docs](http://localhost:8000/docs)
- API health: [http://localhost:8000/health](http://localhost:8000/health)
- Router health: [http://localhost:8001/health](http://localhost:8001/health)
- Local edge API: [http://api.localhost/docs](http://api.localhost/docs)
- Local UI: [http://api.localhost/login](http://api.localhost/login)

Local development assumptions:

- local Traefik uses plain HTTP on `*.localhost`
- Cloudflare and ACME are disabled locally
- private, loopback, and LAN origin hosts are allowed locally
- use `host.docker.internal` for services running on your host machine
- browser sessions are canonicalised onto `api.localhost`; use `localhost:8000` for direct API access
- production defaults remain strict

### 4) Stop

```bash
docker compose -f docker-compose.yml -f docker-compose.local.yml down
```

## API quick flow

Create the first admin user:

```bash
curl -s -X POST http://localhost:8000/auth/setup \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"changeit123"}' | jq
```

Log in and export the bearer token:

```bash
export ARCUS_TOKEN=$(
  curl -s -X POST http://localhost:8000/auth/login \
    -H "Content-Type: application/json" \
    -d '{"email":"admin@example.com","password":"changeit123"}' | jq -r '.access_token'
)
```

Create user:

```bash
curl -s -X POST http://localhost:8000/admin/users \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $ARCUS_TOKEN" \
  -d '{"email":"alice@example.com","role":"normal"}' | jq
```

Grant credits:

```bash
curl -s -X POST http://localhost:8000/credits/grant \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $ARCUS_TOKEN" \
  -d '{"user_id":"<user_id>","amount":5}' | jq
```

Purchase subdomain:

```bash
curl -s -X POST http://localhost:8000/subdomains/purchase \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $ARCUS_TOKEN" \
  -d '{"user_id":"<user_id>","slug":"myapp"}' | jq
```

Set origin:

```bash
curl -s -X POST http://localhost:8000/subdomains/myapp/origin \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $ARCUS_TOKEN" \
  -d '{"origin_host":"203.0.113.10","origin_port":8080}' | jq
```

Check availability:

```bash
curl -s "http://localhost:8000/subdomains/check?slug=myapp" | jq
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
