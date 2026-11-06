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
| `GET /stickers` | Stickers newest first. Takes the filters below, `limit` (1-5000, default 100), `offset` and `format=json\|geojson`. |
| `POST /stickers` | Adds a sticker and returns it with status 201. |
| `GET /stats/summary` | The number of stickers, people, cities and countries. |
| `GET /stats/counts?by=…` | Stickers per `person`, `country`, `city`, `month`, `weekday`, `hour` or `day`. Takes `limit`. |
| `GET /stats/farthest?latitude=…&longitude=…` | The stickers farthest from a place, with `distance_km`. Takes `limit` (1-100, default 10). |
| `GET /stats/people` | For each person: stickers, countries, cities, stickers at night and at the weekend, `travelled_km` from each of their stickers to their next, and their first and last. With `latitude` and `longitude`, also their `farthest` sticker from there. |
| `GET /stats/pairs` | The two people who share the most stickers, and the next ones. Takes `limit` (1-100, default 10). |
| `GET /stats/records` | The `record_day` with the most stickers, the `longest_streak` of days in a row, the stickers farthest `north`, `south`, `east` and `west`, and the `home_share` within 25 km of Norderstedt. |
| `GET /stats/latest` | The two newest stickers and the distance between them. Takes no filters. |
| `GET /health` | 200 when the database is reachable, otherwise 503. |
| `GET /docs` | Interactive documentation. |

Every `GET /stickers` and `/stats` request except `/stats/latest` takes the same filters:

| Filter | Matches |
| --- | --- |
| `name` | One whole person, case-insensitively: `Timo` finds `Lisa & Timo` but not `Timon`. |
| `country` | The ISO 3166-1 alpha-2 code, like `DE`. |
| `city` | The city, case-insensitively. |
| `since`, `until` | Placed at or after `since` and before `until`. Times without an offset are in UTC. |
| `since_day`, `until_day` | Placed on or after `since_day` and before `until_day`, dates like `2024-03-01` on the clocks where the sticker is. Use these for a month or a year, so that they match the local days and months of the statistics. |
| `time_of_day` | `night` (22:00 to 5:59) or `day`, in local time where the sticker is. |

For example, the people with the most stickers at night: `GET /stats/counts?by=person&time_of_day=night&limit=10`.

- `X-Total-Count` on `GET /stickers` holds the number of matching stickers across all pages.
- `POST /stickers` takes `latitude`, `longitude` and `name` (up to 75 characters, several people separated by `&`). The server adds `id`, `date`, the time zone of the place, and the address in German from [Nominatim](https://nominatim.org/), which gets the coordinates. If Nominatim fails or finds nothing, as at sea, the address stays empty. The request needs no login and is limited to 5 per minute and 50 per day for each client IP. There is no endpoint to delete stickers, see [Removing spam](#removing-spam).
- Distances are along the globe, by the haversine formula on a sphere of the Earth's mean radius, at most 0.5 % off the exact distance.
- A sticker of several people counts for each of them in `/stats/people` and `/stats/counts?by=person`, and once for someone on it twice, as in `Ana & ana`.
- A sticker has `date` in UTC, `timezone` (an IANA name like `Europe/Berlin`), `city`, `state`, `country`, `country_code` and `people`, the names split at `&`.
- `/stats/counts` lists people, countries and cities with the most stickers first, and times in their order: months as `2024-03`, weekdays from `1` for Monday to `7`, hours from `00` to `23` and days as `2024-03-31`, all local where the sticker is. A `label` is the most common spelling of its `key`, like `Deutschland` for `DE`.

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

Point a proxy host for your domain at `hbg-frontend:80` and enable TLS there. The proxy must add the client's address to `X-Forwarded-For`, or all visitors share one rate limit. Turn off its access log, as the frontend's privacy policy (`/datenschutz`) says no visit is logged; in Nginx Proxy Manager, put `access_log off;` in the proxy host's Advanced tab.

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
| `STICKER_CREATE_RATE_LIMIT` | New stickers per client IP, in [`limits` notation](https://limits.readthedocs.io/en/stable/quickstart.html#rate-limit-string-notation). Default: `5/minute;50/day`. |
| `STICKER_NOMINATIM_EMAIL` | Sent to Nominatim with each request, as its [usage policy](https://operations.osmfoundation.org/policies/nominatim/) asks. Default: none. |
| `STICKER_NOMINATIM_URL` | The reverse geocoding endpoint. Default: the public Nominatim. |

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

### Removing spam

Back up first. List the stickers by id, or everything saved since a UTC time, then run the same command again with `--yes` to delete them:

```sh
docker compose exec sticker-api python src/delete_stickers.py --since "2026-11-05 14:00"
docker compose exec sticker-api python src/delete_stickers.py 2801 2802 --yes
```

### Moving from the old MySQL site

1. Start the stack without pointing the public hostname at it yet.
2. Stop new stickers on the old site, for example by renaming `insert.php`, so that none get lost after the export.
3. Export the `locations` table with a header row, for example as CSV from phpMyAdmin. It needs the columns `id`, `latitude`, `longitude`, `name`, `date`, `city`, `state` and `country`.
4. Check which time zone the old server saved the dates in, with `SELECT @@global.time_zone, @@system_time_zone;` in phpMyAdmin. `SYSTEM` means the second value.
5. Import it. The import converts the dates from `Europe/Berlin` to UTC; pass another zone with `--source-timezone`. It also adds each sticker's time zone and turns the country names, which the old site saved in each visitor's language, into a code and the German name. It names any country it has no code for, which you can add to `LEGACY_COUNTRIES` in `src/places.py`. If you imported with a release before this conversion, import again with `--replace`, because those dates are still in the old server's time. `--replace` deletes everything already in the sticker table, such as test data. An invalid row aborts the import and changes nothing.
   ```sh
   docker compose run --rm -v "$PWD/locations.csv:/tmp/locations.csv:ro" \
     sticker-api python src/import_stickers.py /tmp/locations.csv --replace
   ```
6. Compare the imported count with the old map, check the pages, and switch the site over.
7. Remove the old `*.php` files and `credentials.txt` from the old server. Keep the MySQL database until you are sure you will not roll back.

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

## License

[MIT](LICENSE)
