# CLI and local server

All commands use the same conversion engine. No Codex or Mathcad installation is needed for Calcpad execution. A compatible private Mathcad template is required for conversion; the public repository does not include one.

## Install

For command-line use:

```bash
uv tool install mcdxkit==0.3.0
mcdxkit --version
mcdxkit setup-engine
```

The one-time engine build needs Git and the .NET 10 SDK. The resulting executable is self-contained. `setup-engine` deliberately refuses to replace an existing engine directory. Reuse a working engine; for an upgrade, build into a new directory and set `MCDXKIT_ENGINE_DIR` rather than deleting the old installation blindly. For editable development use [CONTRIBUTING.md](../CONTRIBUTING.md).

## Inspect before converting

```bash
mcdxkit inspect /path/to/report.gp11t
mcdxkit inspect /path/to/report.gp11t --cases 1,3,7
mcdxkit inspect /path/to/report.gp11t --history /path/to/earlier-results   # learn case naming
mcdxkit inspect /path/to/report.gp11t --checks none                        # no review checks
```

Inspection returns cases, selected cases, load basis and an envelope where selection is resolved. Default selection recognizes `STR` case names and excludes service cases. If classification is unresolved, obtain the intended case IDs; do not guess. `case_suggestions` classifies every case name (strength, service, extreme, fatigue, other or unknown) with confidence and evidence and lists `recommended_cases`; it is advisory, so pass reviewed IDs to `--cases` yourself. `--history OUTPUT_DIR` (inspect only) learns naming conventions from completed conversion audits in that directory. Reports must be GROUP text in the supported kip/in convention, not Excel binaries.

Inspection, conversion audits and batch audits include an advisory `review_checks` block (schema `review-checks/1`, replacing the earlier `review_flags`): flags, annotations such as the governing case, case-name suggestions, errors from checks that could not run, and `checks_run` with each check's version and thresholds. A flag asks you to check the GROUP input and never changes the selection or result. See [review checks](machine-learning.md#review-checks).

## Review checks

```bash
mcdxkit checks list                              # id, version, kind, source, on/off
mcdxkit checks list --checks default,my_check    # on/off for a --checks value; --json for rows
```

`--checks` on `inspect`, `convert` and `batch` takes `default` (the built-in checks, annotators and case-name classifier), `none`, or a comma list of ids such as `default,my_check` or `ratio_outlier`. An unknown id is an error (exit 2). Installed plug-ins (Python entry points in the `mcdxkit.review` group) are listed but stay off until named. A plug-in that fails to load, raises or exceeds its time budget is reported under `review_checks.errors` as `check_error`; the inspection or conversion still completes. With no review decisions, `.mcdx`, `.cpd` and `.html` outputs are byte-identical with `--checks none` and `--checks default`.

Default loads come from the last summary: axial compression from local pile-top reactions, shears/moments from local pile effects. Use `--load-source reactions` only when local top reactions are the intended basis for all components.

## Convert one report

```bash
mcdxkit convert /path/to/report.gp11t \
  --template /path/to/reference.mcdx \
  --output /path/to/new-results/design.mcdx

# Explicit case selection and an already-reviewed literal input change:
mcdxkit convert /path/to/report.gp11t \
  --template /path/to/reference.mcdx \
  --cases 1,3,7 --set n_z=11 --set n_y=1 \
  --output /path/to/new-results/design-revised.mcdx
```

The count values above illustrate syntax; they are not inferred geometry. Read the [template contract](../references/template-contract.md) before applying overrides. `--title` changes the generated source-page title, not inherited headers.

Four files are published together, with audit JSON written last as the completion marker:

| File | Meaning |
| --- | --- |
| `.mcdx` | Native input/formula package; Prime execution unverified |
| `.cpd` | Executable translated Calcpad worksheet |
| `.html` | Fresh Calcpad result snapshot |
| `.audit.json` | Source selection, hashes, assumptions and calculation evidence |

Existing artifacts are never overwritten. Choose a new basename for a new run. A successfully calculated worksheet may contain failing design checks.

## Validate a package

```bash
mcdxkit validate /path/to/design.mcdx
```

This checks ZIP/XML relationships and package integrity. It does not execute Mathcad, validate all PTC schemas or approve the design. Use `mcdxkit <command> --help` for authoritative flags. CLI commands print machine-readable results; inspect process exit status before consuming outputs.

## Batch conversion

```bash
mcdxkit batch /path/to/reports --recursive \
  --template /path/to/reference.mcdx \
  --output-dir /path/to/batch-results --workers 4

mcdxkit batch /path/to/reports --recursive \
  --template /path/to/reference.mcdx \
  --output-dir /path/to/batch-results --workers 4 --resume
```

Explicit files and multiple folders are also accepted. Options apply to every input in the invocation: group compatible reports/templates together. Keep source/template files outside the output directory. Worker count is 1–32; default is up to four. Progress is JSON Lines on stderr; stdout is the summary. `--quiet` suppresses progress.

Exit codes: 0 = all succeeded or verified/skipped; 1 = one or more jobs failed; 2 = invalid setup. Inspect `batch-manifest.jsonl` for individual failures. Resume validates saved identity, hashes and calculation evidence; corrupted outputs are not silently reused. Do not run two batches writing to the same output directory. Manifest rows of converted or verified jobs carry `open_checks`, the number of review flags without an engineer decision. Batch accepts `--checks`; the enabled check ids and versions are part of the job identity, so a new check version converts and reviews again on `--resume` (in a new job folder) instead of reusing the old audit.

## Start and stop the browser

```bash
mcdxkit serve --no-open --port 8765 \
  --template /path/to/reference.mcdx \
  --output-dir /path/to/browser-results
```

Open the printed URL. Omit `--template` to select it in the browser; omit `--no-open` to launch the browser automatically. `--port 0` chooses an available port. `GET /healthz` reports service health. Ctrl+C stops the server while retaining completed outputs.

Workflow: Files → Inputs → Changes → Outputs. Open Report/Template/Output file to inspect content; Results shows separate fresh Calcpad calculations. The original-file view is a reconstruction, not Prime rendering. Inputs and Changes list advisory review checks as "Review: …" items to check; they are never shown as a pass or fail. Inputs greys strength cases that can never govern; they stay selected. Current UI cannot edit arbitrary equations. Saved outputs survive restart; the visible upload queue and temporary previews do not.

## Environment variables

Default template lookup: explicit `--template`, then `MCDXKIT_TEMPLATE`, checkout `assets/local/reference.mcdx`, `$XDG_CONFIG_HOME/mcdxkit/reference.mcdx` (default `~/.config/mcdxkit/reference.mcdx`), then `~/.agents/skills/mcdxkit/assets/local/reference.mcdx`. The older `$CODEX_HOME/skills/mcdxkit/assets/local/reference.mcdx` location remains a last compatibility fallback. No agent installation is required. An explicitly configured missing path is reported as missing rather than silently replaced by another template.

| Variable | Purpose |
| --- | --- |
| `MCDXKIT_TEMPLATE` | Private default template path; `--template` overrides it |
| `MCDXKIT_ENGINE_DIR` | Directory containing the built calculator |
| `MCDXKIT_CALCPAD` | Explicit calculator executable path |
| `PORT` | Server port; default 8765; `--port` overrides |
| `MCDXKIT_HOST` | Default bind host; use loopback for local work |
| `MCDXKIT_PUBLIC_URL` | Exact public origin for hosted mode |
| `MCDXKIT_OUTPUT_DIR` | Server output location; `--output-dir` overrides |
| `MCDXKIT_ACCESS_TOKEN` | Hosting secret, at least 32 characters |
| `MCDXKIT_ACCESS_TOKEN_FILE` | Read the hosting secret from this file; takes precedence |
| `MCDXKIT_CHECKS` | Server review checks, same values as `--checks`; default `default` (built-ins only) |

For a host reachable over the network, follow [deployment instructions](../deploy/README.md). CLI startup does not automatically load `.env`; Compose reads it. `MCDXKIT_PORT`, `MCDXKIT_DOMAIN` and `MCDXKIT_IMAGE` in the example environment are Compose settings, distinct from direct CLI variables.

## Common recovery paths

| Failure | Recovery |
| --- | --- |
| Calculator missing | Run `setup-engine` once or configure the existing executable |
| Engine directory exists | Reuse it or choose a new `--install-dir`; do not overwrite it |
| Template missing | Pass/select a compatible private template |
| Unsupported expression | Report the exact construct and extend the adapter with tests; no cache fallback |
| Pile ID beyond template capacity | Review actual geometry before an explicit override |
| Unknown case names | Supply reviewed `--cases`; `case_suggestions` in `mcdxkit inspect` can suggest them |
| Output exists | Choose another basename, or verified batch resume |
| Port occupied | Use `--port 0` or another port |
| Hosted login/origin error | Check exact HTTPS origin, secret and proxy Host forwarding; do not disable protections |
