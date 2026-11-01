# HBG Sticker API

[![CI](https://github.com/mnowatzky/HBG-Fast-API/actions/workflows/ci.yml/badge.svg)](https://github.com/mnowatzky/HBG-Fast-API/actions/workflows/ci.yml)
[![Docker Hub](https://img.shields.io/docker/v/maltenow/sticker-api?sort=semver&label=docker%20hub)](https://hub.docker.com/r/maltenow/sticker-api)

Stores the stickers the HBG places around the world, with their coordinates and address, and serves them to the map, the statistics and the page for adding a sticker in [HBG-Frontend](https://github.com/mnowatzky/HBG-Frontend). Built with FastAPI, SQLModel, Alembic and PostgreSQL. This repository also holds the compose file that deploys the whole stack.

```
browser ──> reverse proxy (TLS) ──> frontend (Apache) ──/api/──> sticker-api ──> sticker-db
```

The browser reaches the API on the site's own origin below `/api`, so no CORS is needed.

## API

| Request | Purpose |
| --- | --- |
| `GET /stickers` | Stickers newest first. Takes `limit` (1-500, default 100), `offset`, `format=json\|geojson` and `name`. |
| `POST /stickers` | Adds a sticker and returns it with status 201. The server assigns `id` and `date`. |
| `GET /health` | 200 when the database is reachable, otherwise 503. |
| `GET /docs` | Interactive documentation. |

- `X-Total-Count` on `GET /stickers` holds the number of matching stickers across all pages.
- `name` matches one whole person, case-insensitively: `Timo` finds `Lisa & Timo` but not `Timon`.
- `POST /stickers` takes `latitude`, `longitude` and `name` (up to 75 characters), plus optional `city`, `state` and `country`. It needs no login and is limited to 30 requests per minute for each client IP.

## Running it

You need Docker Compose and a reverse proxy with TLS on the same server that reaches containers over a Docker network. The server only needs two files:

```sh
mkdir -p /opt/stickers && cd /opt/stickers
curl -fsSLO https://raw.githubusercontent.com/mnowatzky/HBG-Fast-API/main/docker-compose.yml
curl -fsSL -o .env https://raw.githubusercontent.com/mnowatzky/HBG-Fast-API/main/.env.example
chmod 600 .env
```

In `.env`, set `STICKER_DB_PASSWORD` and `PROXY_NETWORK`, then start the stack:

```sh
docker compose pull
docker compose up -d --no-build --wait
curl http://127.0.0.1:8080/api/health
```

Point a proxy host for your domain at `hbg-frontend:80` and enable TLS there. The proxy must add the client's address to `X-Forwarded-For`, or all visitors share one rate limit.

Migrations run when the API starts. Only the frontend publishes a port, on `127.0.0.1:8080`, for checks through an SSH tunnel.

### Configuration

| `.env` setting | Purpose |
| --- | --- |
| `API_TAG`, `FRONTEND_TAG` | Release versions to run. The two repositories release independently. |
| `PROXY_NETWORK` | Docker network of your reverse proxy. Required. |
| `STICKER_DB_PASSWORD` | Database password, for example from `openssl rand -hex 32`. Required. |
| `STICKER_DB_USER`, `STICKER_DB_NAME` | Database user and name. Required, and fixed once the database exists. |
| `STICKER_DB_HOST`, `STICKER_DB_PORT`, `STICKER_DB_TYPE` | Where the API finds the database. Keep the values from the example. |
| `STICKER_ROOT_PATH` | Path the proxy serves the API below, used for the links in `/docs`. `/api` in this stack. |
| `STICKER_CORS_ORIGINS` | Other origins allowed to call the API, as a JSON list. Default: none. |
| `STICKER_CREATE_RATE_LIMIT` | New stickers per client IP. Default: `30/minute`. |

### Updates and rollback

Set the new `API_TAG` or `FRONTEND_TAG` in `.env`, then run:

```sh
docker compose pull && docker compose up -d --no-build --wait
```

To roll back, set the previous tag and run the same command. Migrations are not reverted, so only roll the API back across releases without schema changes. If a release changes `docker-compose.yml` or `.env.example`, download the compose file again and copy the changes into your `.env`.

### Backups

`./data` holds the database, and nothing backs it up by default. Schedule this and keep the files on another machine:

```sh
docker compose exec -T sticker-db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' \
  | gzip > "sticker-$(date +%F).sql.gz"
```

To restore into an empty database:

```sh
gunzip -c sticker-YYYY-MM-DD.sql.gz \
  | docker compose exec -T sticker-db sh -c 'psql -U "$POSTGRES_USER" "$POSTGRES_DB"'
```

`postgres` is pinned to major version 17 because the data directory is tied to it. Moving to a newer major version takes a dump and restore.

### Moving from the old MySQL site

1. Start the stack without pointing the public hostname at it yet.
2. Stop new stickers on the old site, for example by renaming `insert.php`, so that none get lost after the export.
3. Export the `locations` table with a header row, for example as CSV from phpMyAdmin. It needs the columns `id`, `latitude`, `longitude`, `name`, `date`, `city`, `state` and `country`.
4. Import it. `--replace` deletes everything already in the sticker table, such as test data. An invalid row aborts the import and changes nothing.
   ```sh
   docker compose run --rm -v "$PWD/locations.csv:/tmp/locations.csv:ro" \
     sticker-api python src/import_stickers.py /tmp/locations.csv --replace
   ```
5. Compare the imported count with the old map, check the pages, and switch the site over.
6. Remove the old `*.php` files and `credentials.txt` from the old server. Keep the MySQL database until you are sure you will not roll back.

## Development

The app is in `src/`, the schema changes in `migrations/` and the tests in `tests/`. You need [uv](https://docs.astral.sh/uv/) and Docker.

```sh
uv sync
uv run pytest           # starts its own Postgres container
uv run ruff check .
uv run ruff format .
```

To run the whole stack from source, check out HBG-Frontend next to this repository, set up `.env` as above with `PROXY_NETWORK=hbg-dev`, and run:

```sh
docker network create hbg-dev
docker compose -f docker-compose.yml -f compose.dev.yml up -d --build
```

The site is then on http://127.0.0.1:8080 and the API on http://127.0.0.1:8000.

To change the schema, edit `src/sticker.py`, then generate a migration against the running database and review it. A test fails if the models and the migrations drift apart.

```sh
docker compose -f docker-compose.yml -f compose.dev.yml run --rm --user "$(id -u)" \
  -v "$PWD/migrations:/app/migrations" -v "$PWD/src:/app/src:ro" \
  sticker-api alembic revision --autogenerate -m "describe the change"
```

## Releasing

Versions follow [SemVer](https://semver.org). Each push runs CI. A version tag on `main` runs the checks again, pushes the image with the version and as `latest` for `linux/amd64` and `linux/arm64`, and creates a GitHub release. A tag that isn't on `main`, or doesn't match `pyproject.toml`, fails before anything is pushed. The repository needs the secrets `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN`.

```sh
uv version 0.2.0
git commit -am "Release 0.2.0"
git tag -a v0.2.0 -m "Release 0.2.0"
git push --follow-tags
```
