# Influencers Platform

A full-stack platform with a Django REST API backend, Next.js web frontend, a Node.js realtime service, and a React Native mobile app.

## Architecture

```
influencers/
├── django/       # REST API — Django + PostgreSQL + Redis + Celery
├── web/          # Web frontend — Next.js
├── realtime/     # Realtime service — Node.js + Socket.io
└── mobile/       # Mobile app — Expo React Native
```

### Services & Ports

| Service   | URL                        | Description                          |
|-----------|----------------------------|--------------------------------------|
| Nginx     | http://localhost:9000      | Reverse proxy entry point (`ENTRYPOINT_PORT`) |
| Django    | http://localhost:8000      | REST API + Django admin (direct)     |
| Web       | http://localhost:3000      | Next.js dev server (direct)          |
| Realtime  | http://localhost:3001      | WebSocket / realtime events (direct) |
| Flower    | http://localhost:5555      | Celery UI (`FLOWER_HOST_PORT` if 5555 is busy) |
| Postgres  | localhost:5432             | PostgreSQL database                  |
| Redis     | localhost:6379             | Cache + message broker               |

Nginx routes all traffic through a single port: `/api/` and `/admin/` → Django, `/socket.io/` → Realtime, everything else → Next.js.

---

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose
- [Node.js](https://nodejs.org/) 20+ and npm (for the web and mobile frontends)

---

## Installation

### 1. Clone the repo

```bash
git clone <repo-url>
cd influencers
```

### 2. Set up environment variables

```bash
chmod +x taskfile.sh
./taskfile.sh setup-env
# Edit .env and fill in any required secrets (API keys, etc.)
```

This copies `.env.example` to `.env` and auto-generates `CONTAINER_SUFFIX` and `INTEGRATION_ENCRYPTION_KEY`.

### 3. Start the backend stack

This starts Django, PostgreSQL, Redis, Celery, Celery Beat, Flower, Realtime, and Nginx — all via Docker Compose.

```bash
./taskfile.sh start
```

### 4. Initialize Django (first time only)

```bash
./taskfile.sh setup-django
```

This runs migrations, resets DB sequences, creates a default Organization, and creates a superuser (`admin@localhost.com` / `p`).

### 5. Start the web frontend

In a separate terminal:

```bash
./taskfile.sh web
```

This starts Next.js natively (not in Docker) on the port set by `WEB_PORT` (default: 3000).

---

## Taskfile Commands

Run `./taskfile.sh help` to see all available commands.

```
./taskfile.sh <command>

  setup-env               Copy .env.example to .env; auto-generate CONTAINER_SUFFIX and INTEGRATION_ENCRYPTION_KEY
  setup-django            Run migrations and create default org + superuser
  start                   Start the full backend stack (Docker)
  start --rebuild / -r    Rebuild images before starting
  down                    Stop all containers
  down-clean              Stop containers and remove volumes + images
  migrate                 Run makemigrations + migrate
  migrate <app> <num>     Roll back to a specific migration
  web                     Start Next.js frontend natively
  psql                    Open a psql shell in the postgres container
  shell                   Open an interactive shell in the django container
  shell <cmd> [args...]   Run a one-off command in the django container
```

---

## Development Workflow

1. **Start backend**: `./taskfile.sh start`
2. **Start frontend**: `./taskfile.sh web` (separate terminal)
3. **Make Django migrations**: `./taskfile.sh migrate`
4. **Access Django admin**: http://localhost:8000/admin (admin@localhost.com / p)
5. **Monitor Celery tasks**: http://localhost:5555 (or the host port from `FLOWER_HOST_PORT` in `.env`)
6. **Stop everything**: `./taskfile.sh down`

### Rebuilding after dependency changes

```bash
./taskfile.sh start --rebuild
```

### Reset everything

```bash
./taskfile.sh down-clean
./taskfile.sh start
./taskfile.sh setup-django
```

---

## Environment Variables

All configuration lives in `.env` at the project root (copied from `.env.example`).

| Variable | Default | Description |
|----------|---------|-------------|
| `DEBUG` | `1` | Django debug mode |
| `SECRET_KEY` | (insecure default) | Django secret key — change in production |
| `POSTGRES_DB` | `startup-db` | Database name |
| `POSTGRES_USER` | `startup-user` | Database user |
| `POSTGRES_PASSWORD` | `startup_password` | Database password |
| `POSTGRES_HOST_PORT` | `5432` | Host port mapped to Postgres in Docker (change if local 5432 is busy) |
| `POSTGRES_PORT` | `5432` | Port Django uses to reach `postgres` inside Compose (leave at 5432) |
| `DJANGO_PORT` | `8000` | Django API port |
| `REALTIME_PORT` | `3001` | Realtime service port |
| `FLOWER_HOST_PORT` | `5555` | Host port mapped to Flower in Docker (change if local 5555 is busy) |
| `WEB_PORT` | `3000` | Next.js dev server port (nginx proxies `/` here) |
| `ENTRYPOINT_PORT` | `9000` | Host port for the nginx reverse proxy |
| `REDIS_HOST_PORT` | `6379` | Host port mapped to Redis in Docker (raise if local 6379 is busy) |
| `INTEGRATION_ENCRYPTION_KEY` | _(auto-generated)_ | Fernet key for encrypting integration secrets |
| `REDIS_HOST` | `redis` | Redis hostname (e.g. ElastiCache endpoint in AWS) |
| `REDIS_URL` / `CELERY_*` | see `.env.example` | Full URLs; use if host or DB index differs from defaults |
| `OPENAI_API_KEY` | _(empty)_ | Optional — for AI features |

The web frontend also has its own `web/.env.local` (see `web/.env.local.example`).

---

## Service READMEs

Each service has its own README with service-specific details:

- [django/README.md](django/README.md)
- [web/README.md](web/README.md)
- [realtime/README.md](realtime/README.md)
- [mobile/README.md](mobile/README.md)
