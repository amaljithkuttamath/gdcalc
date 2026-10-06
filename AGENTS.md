# Coding agent guide

## Start here

Read [README.md](README.md) for the shipped product, [CLI and server guide](docs/cli.md) for commands, [architecture](docs/architecture.md) for boundaries, and [CONTRIBUTING.md](CONTRIBUTING.md) for development and verification. [SKILL.md](SKILL.md) is the agent-facing conversion workflow. Read [the template contract](references/template-contract.md) before changing load mapping or worksheet generation.

The current app converts GROUP text reports into executable Calcpad worksheets, calculated HTML, native Mathcad formula packages and audit JSON. The browser inspects files and runs conversions. It is not yet a general equation editor or a universal Mathcad runtime. The broader [feature review](docs/mathcad-prime-review.md) is a roadmap, not an implemented API specification.

## Run locally

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.lock
python -m pip install --no-deps -e .
# Once per engine location; needs Git and .NET 10 SDK:
gdcalc setup-engine
gdcalc serve --no-open --port 8765 --output-dir ./gdcalc-output
```

The server prints its URL. Upload/select a private compatible template in the browser, or pass `--template /absolute/path/reference.mcdx`. Use `--port 0` if the preferred port is occupied; read the printed URL rather than assuming a port. Do not kill an unrelated server. Stop the process you started with Ctrl+C. Preserve output directories.

## Engineering and data invariants

- Read load values from the final local-load summary only. No fallback to earlier/global tables. Preserve the intended case selection and load basis.
- Never invent geometry, materials, fixity or pile counts to make a calculation pass. Overrides change engineering inputs.
- Preserve sources and existing outputs. Use new output paths. Keep engineering documents, snapshots, `.env` and secrets out of Git, logs and public fixtures.
- Keep native formulas executable and remove stale Mathcad result caches. Never insert a cached pass message as a fresh result.
- Unsupported expressions must be explicit failures. Do not silently substitute zero, cached values or another engine's semantics.
- Distinguish package validation, Calcpad calculation, Prime-native verification and engineering review. `native_execution_verified` stays false unless there is real native execution evidence.
- Independent component extrema are not concurrent load combinations. Keep governing case/pile provenance visible.
- Do not invent universal input limits or code factors. Record applicable project/code/catalog sources and editions. The proposed [engineering standards register](docs/engineering-standards.md) is not implemented compliance validation.

## Implementation boundaries

Use `engine.py` for conversion logic shared by CLI and server. Keep HTTP/session concerns in `server.py` and `service.py`; source parsing in `group_report.py`; package editing in `mcdx.py`; translation/execution in `calcpad.py`; inspection in `inspection.py`; scheduling/resume in `batch.py`. Do not create a separate calculation implementation in the UI or skill scripts.

CalcpadCE itself has more capabilities than the current translator. Broader input execution changes the trust boundary: preserve timeouts, file-access controls and HTML isolation. Keep network authentication, Host/Origin checks, CSRF protections and upload/package limits intact. Current hosting is a shared trusted workspace, not tenant-isolated storage.

The root README is also the PyPI package description. Use absolute GitHub URLs for repository-file links in README.md; relative links break on PyPI and fail `scripts/check_package.py`. Relative links remain appropriate inside the repository docs.

If adding browser assets, update both `pyproject.toml` package data and `.dockerignore`; add required distribution assets to `scripts/check_package.py` when appropriate. If adding CLI flags, update `--help`, docs and applicable tests. Keep the CLI version and project version consistent when changing a release version.

## Verification and publishing

Follow [repository standards](docs/standards.md) and the [testing contract](docs/testing.md). For each behavioral change, add or update meaningful regression tests and relevant negative cases from that matrix. Use independent expected values and real-engine integration where calculation changes. Record exactly what ran, what passed and what remains unverified; never claim a planned or mocked check as execution evidence. Required checks must pass on the current PR head.

Work through a GitHub issue and a feature/fix branch. Claim or comment on the issue before implementation to avoid duplicate work. Use a branch such as `feat/123-short-description`, `fix/123-short-description` or `chore/123-short-description`. Do not commit new work directly to `main`. Keep one coherent change per pull request, link the ticket with `Closes #123`, and provide acceptance evidence. Use a draft PR for incomplete work; only request merge when required checks pass. Maintainers merge through GitHub, then publication runs from `main`. See [contribution workflow](CONTRIBUTING.md#tickets-branches-and-review).

```bash
python -m unittest discover -s tests -v
node --check src/gdcalc/web/app.js
python -m pip install build
python -m build
python scripts/check_package.py
git diff --check
```

Tests execute the real calculator and start loopback HTTP servers. Use synthetic fixtures from `tests/test_pipeline.py`; do not commit private reports/templates. For UI changes, exercise the affected workflow in a browser and distinguish tested behavior from unverified behavior.

The Actions workflow tests Python 3.10/3.12, builds packages and tests the actual container before publishing it on `main`. Check the run for the exact pushed commit. A local test pass is not a successful remote image publish. Follow the user's requested publication scope; cloud hosting is separate from GitHub publication.
