# Arcus

Arcus is a minimal, production-sensible subdomain-as-a-service platform.  
Users purchase subdomains under **bigalan.dev** using credits, point them at their own origin server, and all traffic is transparently reverse-proxied through the platform.

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
| `router`   | Reverse proxy – routes `*.bigalan.dev` traffic |
| `traefik`  | Edge load balancer with automatic TLS            |

---

## Prerequisites

- Docker ≥ 24 and Docker Compose V2
- A Cloudflare account with `bigalan.dev` configured
- A Cloudflare API token with **Zone:DNS:Edit** permission

---

## Cloudflare DNS setup

1. Log into the [Cloudflare dashboard](https://dash.cloudflare.com).
2. Select your `bigalan.dev` zone.
3. Add a **wildcard A record** pointing to your server's public IP:

   | Type | Name               | Content        | Proxy status |
   |------|--------------------|----------------|--------------|
   | A    | `*.bigalan.dev`| `<your IP>`    | Proxied ✅   |

4. Obtain your **Zone ID** from the zone overview page (right-hand sidebar).
5. Create an API token with *Zone › DNS › Edit* permission.

> Alternatively, leave `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ZONE_ID` set – Arcus will create per-subdomain CNAME records automatically on each purchase.

---

## Running tests

Tests run entirely in-process with a SQLite database – no external dependencies required.

```bash
# Install dependencies
pip install -r api/requirements.txt
pip install pytest==8.3.2 pytest-asyncio==0.23.8 asgi-lifespan

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

After this, `https://myapp.bigalan.dev` will proxy traffic to `http://203.0.113.10:8080`.

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

---

## Production deployment

### 1 — Provision a server

Any Linux VPS (Ubuntu 22.04 LTS recommended) with:

- Docker ≥ 24 + Docker Compose V2 (`docker compose` subcommand)
- Ports 80 and 443 open in your firewall
- A public static IP pointed to by your Cloudflare wildcard DNS record

### 2 — Configure secrets

```bash
cp .env.example .env
```

Edit `.env` and fill in **all** required values:

| Variable | Notes |
|---|---|
| `CLOUDFLARE_API_TOKEN` | Zone:DNS:Edit permission |
| `CLOUDFLARE_ZONE_ID` | Found in Cloudflare zone overview |
| `JWT_SECRET_KEY` | Generate with `openssl rand -hex 32` |
| `API_SECRET_KEY` | Generate with `openssl rand -hex 32` |
| `POSTGRES_PASSWORD` | Use a strong random password |

> **Never commit `.env` to version control.**  
> The repository's `.gitignore` excludes it by default.

### 3 — Deploy

```bash
# Clone and enter the project
git clone https://github.com/Bigalan09/Arcus.git
cd Arcus

# Copy and configure secrets
cp .env.example .env
# ... fill in .env ...

# Build images and start all services in the background
docker compose up -d --build

# Watch logs until healthy
docker compose logs -f --tail=50
```

All four services (`postgres`, `api`, `router`, `traefik`) start automatically.  
Traefik obtains a Let's Encrypt TLS certificate via Cloudflare DNS-01 within ~30 seconds.

### 4 — First-run admin setup

Once the API is live, visit `https://api.<your-domain>/setup` in a browser to create the initial admin account. This endpoint is disabled after the first admin is created.

### 5 — Ongoing operations

```bash
# Pull and redeploy after a code change
git pull
docker compose up -d --build

# View running containers
docker compose ps

# Tail a single service's logs
docker compose logs -f api

# Run database migrations manually (if needed)
docker compose exec api alembic upgrade head

# Stop everything
docker compose down

# Stop and wipe all data volumes (destructive!)
docker compose down -v
```

### Environment variable reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `CLOUDFLARE_API_TOKEN` | ✅ | — | Cloudflare API token (Zone:DNS:Edit) |
| `CLOUDFLARE_ZONE_ID` | ✅ | — | Zone ID for your domain |
| `JWT_SECRET_KEY` | ✅ | `change_me_jwt_secret_in_production` | HS256 signing secret — **must change** |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | ❌ | `1440` | Session lifetime (minutes) |
| `BASE_DOMAIN` | ❌ | `bigalan.dev` | Root domain |
| `API_SECRET_KEY` | ❌ | `changeme` | Legacy signing key |
| `POSTGRES_PASSWORD` | ❌ | `arcus` | PostgreSQL password |
| `SMTP_HOST` | ❌ | — | SMTP server for email (leave empty to log only) |
| `SMTP_PORT` | ❌ | `587` | SMTP port |
| `SMTP_USER` | ❌ | — | SMTP username |
| `SMTP_PASSWORD` | ❌ | — | SMTP password |
| `SMTP_FROM_EMAIL` | ❌ | `noreply@arcus.local` | From address for system emails |
| `SMTP_USE_TLS` | ❌ | `true` | Enable STARTTLS |

---

## GitHub Actions & self-hosted runners

The CI pipeline (`.github/workflows/ci.yml`) runs three jobs on every pull request against `main` or `develop`:

| Job | What it does |
|---|---|
| `Lint (ruff)` | Checks Python style with Ruff |
| `Test (pytest)` | Runs the full test suite against an in-memory SQLite DB |
| `Build Docker images` | Validates both Dockerfiles compile (no push) |

By default all jobs use `ubuntu-latest` (GitHub-hosted runners). If you want to run CI on your **own infrastructure** (e.g. to avoid minutes limits or to test against a real Postgres), follow the steps below.

### Registering a self-hosted runner

1. Go to **Settings → Actions → Runners → New self-hosted runner** in the GitHub repository.
2. Follow the on-screen instructions for your OS (typically Linux x64). The essential steps are:

```bash
# Download the runner package (version shown in the GitHub UI)
mkdir actions-runner && cd actions-runner
curl -o actions-runner-linux-x64.tar.gz -L \
  https://github.com/actions/runner/releases/download/v<VERSION>/actions-runner-linux-x64-<VERSION>.tar.gz
tar xzf ./actions-runner-linux-x64.tar.gz

# Configure against your repository
./config.sh --url https://github.com/<YOUR_ORG>/<YOUR_REPO> \
            --token <REGISTRATION_TOKEN>

# Install and start as a systemd service (runs on reboot)
sudo ./svc.sh install
sudo ./svc.sh start
```

> The `REGISTRATION_TOKEN` is shown once in the GitHub UI; it expires after one hour.

### Enabling Docker-in-Docker on the runner host

The `Build Docker images` job uses `docker/build-push-action`, which requires Docker to be available on the runner:

```bash
# Install Docker Engine on Ubuntu
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER   # allow runner user to call docker
# Re-login or: newgrp docker
```

### Switching the workflow to use your runner

Add a label when you configured the runner (e.g. `self-hosted,linux,arcus`) then change the relevant job's `runs-on` in `.github/workflows/ci.yml`:

```yaml
jobs:
  lint:
    runs-on: [self-hosted, linux, arcus]   # was: ubuntu-latest

  test:
    runs-on: [self-hosted, linux, arcus]

  build:
    runs-on: [self-hosted, linux, arcus]
```

Commit and push — the next CI run will be dispatched to your runner.

### Runner security notes

- Self-hosted runners execute arbitrary code from pull requests; only enable them on **private** repositories or configure [required approvals for external contributors](https://docs.github.com/en/actions/managing-workflow-runs-and-deployments/managing-workflow-runs/approving-workflow-runs-from-public-forks).
- Store repository secrets (`CLOUDFLARE_API_TOKEN`, etc.) under **Settings → Secrets and variables → Actions** — they are injected as environment variables at run time and never written to disk.
