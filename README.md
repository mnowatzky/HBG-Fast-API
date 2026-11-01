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

## Configuration

Copy `.env.example` to `.env` and set a password. The file explains the optional settings.

## Running it

```sh
docker compose up -d --build
curl http://127.0.0.1:8000/health
```

Migrations run when the container starts. The API listens only on `127.0.0.1:8000` and on the Docker network `hbg`, and the database is not published at all.

## Connecting the frontend

**In Docker.** After starting this project, run `docker compose up -d --build` in HBG-Frontend. Set `PROXY_NETWORK` in its `.env` first (see `.env.example`). The container joins the `hbg` network and that network of your reverse proxy. Point the proxy host for `intern.diehbg.de` at `hbg-frontend:80` and enable TLS there. The site is also on `127.0.0.1:8080` for checks, for example through an SSH tunnel.

**On an existing Apache.** Copy the HTML, `css`, `js` and `bilder` to the document root, enable `mod_proxy_http` and `mod_negotiation`, and add this to the vhost:

```apache
Options +MultiViews
ProxyPass "/api/" "http://127.0.0.1:8000/" disablereuse=On connectiontimeout=3 timeout=30 retry=0
ProxyPassReverse "/api/" "http://127.0.0.1:8000/"
```

**On its own domain,** if the API cannot run behind the site's web server: set `API_BASE_URL` in the frontend's `js/api.js` to the API's HTTPS URL, and set `STICKER_CORS_ORIGINS=["https://intern.diehbg.de"]` and an empty `STICKER_ROOT_PATH` in `.env`. Its proxy must add the client's address to `X-Forwarded-For`, or all visitors share one rate limit.

## Moving from MySQL

The live site writes to MySQL until the new frontend is deployed, so export as late as possible.

1. Start the API as described above, and connect the frontend somewhere that is not yet public.
2. Stop new stickers on the old site, for example by renaming `insert.php`, so that none get lost after the export. Then export the table with a header row. phpMyAdmin's CSV export works, or:
   ```sh
   mysql --batch --default-character-set=utf8mb4 -h HOST -u USER -p DATABASE \
     -e "SELECT id, latitude, longitude, name, date, city, state, country FROM locations ORDER BY id" \
     > locations.tsv
   ```
3. Import it. `--replace` deletes everything already in the sticker table, such as old test data. An invalid row aborts the import and changes nothing.
   ```sh
   docker compose run --rm -v "$PWD/locations.tsv:/tmp/locations.tsv:ro" \
     sticker-api python src/import_stickers.py /tmp/locations.tsv --replace
   ```
4. Compare the imported count with "N Sticker insgesamt" on the old map.
5. Check the map, a `?name=` link from the bar chart, the statistics, and saving a sticker.
6. Switch the site over.
7. Remove the old `*.php` files and `credentials.txt` from the server. Keep the MySQL database until you are sure you will not roll back.

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

To change the schema, edit `src/sticker.py`, then generate a migration against the running database and review it:

```sh
docker compose run --rm --user "$(id -u)" -v "$PWD/migrations:/app/migrations" -v "$PWD/src:/app/src:ro" \
  sticker-api alembic revision --autogenerate -m "describe the change"
```

A test fails if the models and the migrations drift apart.
