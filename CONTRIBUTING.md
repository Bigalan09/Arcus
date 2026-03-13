# Contributing to Arcus

Thank you for contributing! This document describes our branching strategy,
commit conventions, and release process.

---

## Branching strategy (GitFlow)

```
main ──────────────────────────────────────── v1.0.0 ──── v1.0.1
      \                                      /      \     /
       release/1.0.0 ──────────────────────         hotfix/...
      /
develop ─────────────────────────────────────────────────────────
    \         /     \          /
    feature/A       feature/B
```

### Branch types

| Branch | Purpose | Branches from | Merges into |
|--------|---------|---------------|-------------|
| `main` | Production-ready code. Every commit here is releasable. | – | – |
| `develop` | Integration branch. The next release is assembled here. | `main` | `main` via `release/*` |
| `feature/<ticket>-short-description` | New features and non-urgent fixes. | `develop` | `develop` |
| `release/<version>` | Release preparation (bump versions, final fixes). | `develop` | `main` **and** `develop` |
| `hotfix/<version>` | Urgent production fixes. | `main` | `main` **and** `develop` |

### Naming examples

```
feature/42-add-stripe-billing
feature/101-improve-router-ws-proxy
release/1.2.0
release/1.2.1-rc.1
hotfix/1.1.1
```

### Branch protection rules (configure in GitHub → Settings → Branches)

- **`main`** – require PR, require passing CI, no direct pushes, require linear history.
- **`develop`** – require PR, require passing CI.

---

## Commit messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short summary>

[optional body]

[optional footer]
```

| Type | When to use |
|------|-------------|
| `feat` | New feature |
| `fix` | Bug fix |
| `refactor` | Code change with no behaviour change |
| `test` | Adding or updating tests |
| `docs` | Documentation only |
| `ci` | CI/CD configuration |
| `chore` | Maintenance (deps, tooling) |
| `perf` | Performance improvement |

**Examples:**

```
feat(api): add stripe billing endpoint
fix(router): handle missing Host header gracefully
ci: add docker build step to release workflow
chore: upgrade python-multipart to 0.0.22
```

---

## Release process

Arcus uses **Semantic Versioning** (`MAJOR.MINOR.PATCH`).

| Version part | Increment when |
|---|---|
| `MAJOR` | Breaking API or schema changes |
| `MINOR` | New backwards-compatible features |
| `PATCH` | Backwards-compatible bug fixes |

### Creating a release

```bash
# 1. Branch from develop
git checkout develop && git pull
git checkout -b release/1.2.0

# 2. Update version references if needed, then commit
git commit -am "chore: bump version to 1.2.0"

# 3. Open a PR: release/1.2.0 → main
#    Once approved and CI is green, merge it.

# 4. Tag main with the release version
git checkout main && git pull
git tag -a v1.2.0 -m "Release v1.2.0"
git push origin v1.2.0
# → triggers the Release workflow:
#   • builds & pushes Docker images to GHCR (ghcr.io/bigalan09/arcus-api:1.2.0)
#   • creates a GitHub Release with auto-generated notes

# 5. Merge main back into develop to pick up any release-branch commits
git checkout develop
git merge --no-ff main
git push origin develop
```

### Release candidates

For larger releases, publish a release candidate first:

```bash
git tag -a v1.2.0-rc.1 -m "Release candidate v1.2.0-rc.1"
git push origin v1.2.0-rc.1
# → builds & pushes images tagged :1.2.0-rc.1
# → creates a pre-release on GitHub (does NOT overwrite :latest)
```

### Hotfixes

```bash
# Branch from main (not develop)
git checkout main && git pull
git checkout -b hotfix/1.1.1

# Fix, test, commit
git commit -am "fix(router): handle nil origin port"

# PR hotfix/1.1.1 → main, merge, then tag
git checkout main && git pull
git tag -a v1.1.1 -m "Hotfix v1.1.1"
git push origin v1.1.1

# Merge back into develop
git checkout develop
git merge --no-ff main
git push origin develop
```

---

## CI/CD overview

| Workflow | Trigger | Jobs |
|----------|---------|------|
| **CI** (`.github/workflows/ci.yml`) | Push/PR to `main` or `develop` | Lint (ruff), Test (pytest), Build Docker images |
| **Release** (`.github/workflows/release.yml`) | Push of `v*.*.*` or `v*.*.*-rc.*` tag | Build & push images to GHCR, Create GitHub Release |

### Docker image registry

Images are published to **GitHub Container Registry**:

```
ghcr.io/bigalan09/arcus-api:<version>
ghcr.io/bigalan09/arcus-router:<version>
```

Tags produced for each release:
- `1.2.0` – exact version
- `1.2` – major.minor alias
- `latest` – always points to the most recent stable release (not RCs)

### Running CI locally

```bash
# Lint
pip install ruff==0.4.4
ruff check api/ router/

# Tests
pip install -r api/requirements.txt pytest==8.3.2 pytest-asyncio==0.23.8 asgi-lifespan
pytest
```
