# HBG Sticker API

Stores the stickers placed around the world with their coordinates and address, and serves them to the pages in [HBG-Frontend](https://github.com/mnowatzky/HBG-Frontend). It replaces the PHP pages and MySQL database behind https://intern.diehbg.de/karte.

```
browser ──> Apache (HBG-Frontend) ──/api/──> sticker-api ──> sticker-db (Postgres)
```

The browser reaches the API on the same origin below `/api`, so no CORS is needed and HTTPS comes from the site itself.

## API

| Request | Purpose |
| --- | --- |
| `GET /stickers` | Stickers newest first. `limit` (1-500, default 100), `offset`, `format=json\|geojson`, `name`. |
| `POST /stickers` | Adds a sticker and returns it with status 201. The server assigns `id` and `date`. |
| `GET /health` | 200 when the database is reachable, otherwise 503. |
| `GET /docs` | Interactive documentation. |

- `X-Total-Count` on `GET /stickers` holds the number of matching stickers across all pages.
- `name` matches one whole person, case-insensitively: `Timo` finds `Lisa & Timo` but not `Timon`.
- `POST /stickers` takes `latitude`, `longitude` and `name` (up to 75 characters), plus optional `city`, `state` and `country`. It is limited to 30 requests per minute for each client IP.

## Running it

The stack is a compose file and a `.env`, using the images from Docker Hub: `maltenow/sticker-api` and `maltenow/hbg-frontend`. You need a reverse proxy with TLS on the same server that reaches containers over a Docker network.

```sh
mkdir -p /opt/stickers && cd /opt/stickers
curl -fsSLO https://raw.githubusercontent.com/mnowatzky/HBG-Fast-API/main/docker-compose.yml
curl -fsSL -o .env https://raw.githubusercontent.com/mnowatzky/HBG-Fast-API/main/.env.example
chmod 600 .env
```

In `.env`, set `STICKER_DB_PASSWORD`, `PROXY_NETWORK` and the release versions in `API_TAG` and `FRONTEND_TAG`. Then start it:

```sh
docker compose pull
docker compose up -d --no-build --wait
curl http://127.0.0.1:8080/api/health
```

Point a proxy host for your domain at `hbg-frontend:80` and enable TLS there. The proxy must add the client's address to `X-Forwarded-For`, or all visitors share one rate limit.

Migrations run when the API starts. The database is not published at all, and the site is on `127.0.0.1:8080` only for checks, for example through an SSH tunnel.

### Updates and rollback

Set the new `API_TAG` or `FRONTEND_TAG` in `.env`, then run:

```sh
docker compose pull && docker compose up -d --no-build --wait
```

To roll back, set the previous tag and run the same commands. Migrations are not reverted, so only roll the API back across releases without schema changes. If a release changes `docker-compose.yml` or `.env.example`, download the compose file again and copy the changes into your `.env`.

## Moving from MySQL

The live site writes to MySQL until the new frontend is deployed, so export as late as possible.

1. Start the stack as described above, without pointing the public hostname at it yet.
2. Stop new stickers on the old site, for example by renaming `insert.php`, so that none get lost after the export. Then export the table with a header row. phpMyAdmin's CSV export works, or:
   ```sh
   mysql --batch --default-character-set=utf8mb4 -h HOST -u USER -p DATABASE \
     -e "SELECT id, latitude, longitude, name, date, city, state, country FROM locations ORDER BY id" \
     > locations.csv
   ```
3. Import it. `--replace` deletes everything already in the sticker table, such as old test data. An invalid row aborts the import and changes nothing.
   ```sh
   docker compose run --rm -v "$PWD/locations.csv:/tmp/locations.csv:ro" \
     sticker-api python src/import_stickers.py /tmp/locations.csv --replace
   ```
4. Compare the imported count with "N Sticker insgesamt" on the old map.
5. Check the map, a `?name=` link from the bar chart, the statistics, and saving a sticker.
6. Switch the site over.
7. Remove the old `*.php` files and `credentials.txt` from the old server. Keep the MySQL database until you are sure you will not roll back.

## Backups

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

## Development

```sh
uv sync
uv run pytest           # starts its own Postgres container, needs Docker
uv run ruff check .
uv run ruff format .
```

To run the whole stack from source, with HBG-Frontend checked out next to this repository, set up `.env` as above and run:

```sh
docker network create hbg-dev   # and set PROXY_NETWORK=hbg-dev in .env
docker compose -f docker-compose.yml -f compose.dev.yml up -d --build
```

To change the schema, edit `src/sticker.py`, then generate a migration against the running database and review it:

```sh
docker compose -f docker-compose.yml -f compose.dev.yml run --rm --user "$(id -u)" \
  -v "$PWD/migrations:/app/migrations" -v "$PWD/src:/app/src:ro" \
  sticker-api alembic revision --autogenerate -m "describe the change"
```

A test fails if the models and the migrations drift apart.

## Releasing

Versions follow [SemVer](https://semver.org). Each push runs CI. A version tag on `main` runs the checks again, pushes the image with the version and as `latest` for `linux/amd64` and `linux/arm64`, and creates a GitHub release. A tag that isn't on `main` fails before anything is pushed.

This repository's tag has to match the version in `pyproject.toml`:

```sh
uv version 0.2.0
git commit -am "Release 0.2.0"
git tag -a v0.2.0 -m "Release 0.2.0"
git push --follow-tags
```

HBG-Frontend has no version file, so there it's only the last two commands. Both repositories need the secrets `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN`.
