# Deployment

One service serves the browser and authenticated API through FastAPI/Uvicorn. The Python conversion engine remains independent of HTTP. `service.py` owns file handling and jobs; `inspection.py` provides a read-only worksheet view and expression diff. Only supported worksheet formulas are translated and calculated; arbitrary scripts, macros and includes are rejected.

The current deployment is **one process/replica for one trusted user or team**. Everyone with the access token shares the workspace and saved outputs. It is not a multi-tenant service. Generation is serialized; concurrent conversion requests receive a retryable error. Scaling to separate customers requires per-user authorization/storage and a durable worker queue first.

## Local CLI

```bash
mcdxkit serve --template /path/to/reference.mcdx --output-dir ./outputs
```

The default binds to `127.0.0.1:8765` and opens a browser. Use `--port 0` for a free port, or `--no-open` to print the URL. Local mode sends no files to a cloud service.

## Docker on your computer

From the repository:

```bash
python3 scripts/setup_deploy.py
docker compose up --build -d
```

Open http://127.0.0.1:8765 and sign in with the contents of `.secrets/access-token`. Select your private template in the browser. The image never includes reports, worksheets, templates, or credentials.

Compose publishes the application port on host loopback only. The app runs as a non-root user with a read-only root filesystem, temporary scratch storage, dropped capabilities, a memory limit, a health check, and a persistent named volume at `/data`. `docker compose stop` preserves that volume. Do not use `down -v` unless you intend to delete the stored files.

See [AWS/GCP infrastructure and operator runbook](cloud.md) for reviewed-plan examples, usage, backups and rollback. The [distributed architecture](../docs/distributed-architecture.md) states the separate requirements before adding replicas.

## Cloud VM with HTTPS

Use a Linux VM with Docker Compose, a domain pointing to it, and ports 80/443 available. Run `setup_deploy.py`, then update `.env`:

```dotenv
MCDXKIT_PUBLIC_URL=https://calc.example.com
MCDXKIT_DOMAIN=calc.example.com
MCDXKIT_PORT=8765
```

Start the optional Caddy TLS proxy:

```bash
docker compose --profile cloud up --build -d
```

Caddy terminates HTTPS and forwards to the application on the private Compose network. Keep the app's 8765 port private. The app checks the exact configured Host/Origin, requires a deployment token to log in, and uses an HttpOnly, SameSite cookie plus a separate request token. HTTPS origins get Secure cookies. Login expires after eight hours; restarting the service invalidates login sessions. A server deployment uploads selected files to that server, which the interface explicitly states.

## Managed container platforms

The GitHub Actions workflow tests Python 3.10 and 3.12, checks JavaScript syntax, builds a wheel/source distribution, checks packaged assets, then builds and tests the Docker image. Successful runs on `main` publish that exact tested image to `ghcr.io/amaljithkuttamath/mcdxkit` with `latest` and `sha-<full-commit-sha>` tags. Pull requests run checks without publishing. A manual run from the Actions tab can rebuild `main`.

The image currently targets Linux AMD64. Build locally with the Dockerfile for another supported architecture. Python artifacts are downloadable from each workflow run for 30 days; they do not bundle the calculator, so non-container installs still need `mcdxkit setup-engine`.

No manually created publishing secret is needed: Actions uses its temporary `GITHUB_TOKEN`, with package-write permission limited to the container job. Actions are pinned to commits and Dependabot checks their updates weekly. No cloud hosting environment or deployment credentials are configured by this workflow.

After an image has published, reuse the existing Compose security and storage settings:

```bash
python3 scripts/setup_deploy.py
# Set MCDXKIT_IMAGE in .env to the desired sha tag for a reproducible deployment.
docker compose -f compose.yaml -f compose.registry.yaml pull mcdxkit
docker compose -f compose.yaml -f compose.registry.yaml up --no-build -d
```

The container package's visibility is separate from the repository's. If it is private, authenticate to GHCR with an account authorized to read the package. Public anonymous pulls require the package to be made public in GitHub Packages settings. Do not place registry credentials in `.env` or source control. Deployment access tokens remain in the generated `.secrets/access-token` file or a hosting provider's secret manager.

Build this Dockerfile, deploy **one instance**, and configure:

| Setting | Value |
|---|---|
| `PORT` | Platform's assigned port; default `8765` |
| `MCDXKIT_HOST` | `0.0.0.0` |
| `MCDXKIT_PUBLIC_URL` | Exact HTTPS origin, without a path |
| `MCDXKIT_ACCESS_TOKEN` | Random secret with at least 32 characters, injected by secret manager |
| `MCDXKIT_OUTPUT_DIR` | Persistent mounted directory, e.g. `/data/outputs` |
| Health check | `GET /healthz` |

Alternatively mount a token file and set `MCDXKIT_ACCESS_TOKEN_FILE`. Use a writable persistent volume owned by UID/GID 10001 and allow temporary `/tmp` storage. The default template can be mounted read-only and set with `MCDXKIT_TEMPLATE`, or selected in the browser. Configure the TLS proxy to preserve the public Host header, allow 32 MiB requests, and use a sufficiently long request timeout for conversion (e.g. 120 seconds). Never disable authentication to make a deployment work.

## Storage and boundaries

- Upload queue, temporary previews, and selected template are session state and reset on restart. Refreshing the page resets the visible queue.
- Completed jobs persist as `.mcdx`, `.cpd`, calculated `.html`, audit JSON, and `_source/` snapshots of the original report and template. Saved worksheets restores download links and diffs after restart. Back up the entire output volume; source snapshots are private engineering data too.
- The source/template snapshots allow an exact expression comparison against the inputs used for that conversion. Preview files remain temporary until Generate is chosen.
- Reports are limited to 16 MiB, worksheets/templates to 32 MiB, and session uploads to 256 MiB/100 files. ZIP expansion and XML parsing are independently constrained by the engine.
- Worksheet inspection displays extracted text, images and native equations using a restricted MathML renderer. Unsupported constructs remain labeled text with original XML available. It is not Mathcad's native page renderer or calculator.
- Linux containers cannot execute Mathcad Prime. Native verification requires a separate licensed Windows/Mathcad installation. No native calculation success is implied by package checks.

See [Docker build guidance](https://docs.docker.com/build/building/best-practices/), [Compose services](https://docs.docker.com/reference/compose-file/services/) and [FastAPI container guidance](https://fastapi.tiangolo.com/deployment/docker/) for the underlying deployment features.

## Required calculation engine

The Docker build compiles the pinned MIT-licensed CalcpadCE source and bundles the self-contained bridge. No calculator setup or network access is needed during conversion. Each worker executes an isolated, time-limited calculator process; size the worker count to available memory. Docker builds need access to GitHub and NuGet. Non-container installs run `mcdxkit setup-engine` once with Git and the .NET 10 SDK.

A successful job includes `.cpd`, calculated `.html`, `.mcdx` and audit JSON. Resume checks the calculated artifacts too. The browser shows CalcpadCE results; native Mathcad execution remains a separate check.
