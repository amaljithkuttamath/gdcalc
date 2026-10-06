# CLI and local server

All commands use the same conversion engine. No Codex or Mathcad installation is needed for Calcpad execution. A compatible private Mathcad template is required for conversion; the public repository does not include one.

## Install

For command-line use:

```bash
uv tool install gdcalc==0.2.1
gdcalc --version
gdcalc setup-engine
```

The one-time engine build needs Git and the .NET 10 SDK. The resulting executable is self-contained. `setup-engine` deliberately refuses to replace an existing engine directory. Reuse a working engine; for an upgrade, build into a new directory and set `GDCALC_ENGINE_DIR` rather than deleting the old installation blindly. For editable development use [CONTRIBUTING.md](../CONTRIBUTING.md).

## Inspect before converting

```bash
gdcalc inspect /path/to/report.gp11t
gdcalc inspect /path/to/report.gp11t --cases 1,3,7
```

Inspection returns cases, selected cases, load basis and an envelope where selection is resolved. Default selection recognizes `STR` case names and excludes service cases. If classification is unresolved, obtain the intended case IDs; do not guess. Reports must be GROUP text in the supported kip/in convention, not Excel binaries.

Default loads come from the last summary: axial compression from local pile-top reactions, shears/moments from local pile effects. Use `--load-source reactions` only when local top reactions are the intended basis for all components.

## Convert one report

```bash
gdcalc convert /path/to/report.gp11t \
  --template /path/to/reference.mcdx \
  --output /path/to/new-results/design.mcdx

# Explicit case selection and an already-reviewed literal input change:
gdcalc convert /path/to/report.gp11t \
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
gdcalc validate /path/to/design.mcdx
```

This checks ZIP/XML relationships and package integrity. It does not execute Mathcad, validate all PTC schemas or approve the design. Use `gdcalc <command> --help` for authoritative flags. CLI commands print machine-readable results; inspect process exit status before consuming outputs.

## Batch conversion

```bash
gdcalc batch /path/to/reports --recursive \
  --template /path/to/reference.mcdx \
  --output-dir /path/to/batch-results --workers 4

gdcalc batch /path/to/reports --recursive \
  --template /path/to/reference.mcdx \
  --output-dir /path/to/batch-results --workers 4 --resume
```

Explicit files and multiple folders are also accepted. Options apply to every input in the invocation: group compatible reports/templates together. Keep source/template files outside the output directory. Worker count is 1–32; default is up to four. Progress is JSON Lines on stderr; stdout is the summary. `--quiet` suppresses progress.

Exit codes: 0 = all succeeded or verified/skipped; 1 = one or more jobs failed; 2 = invalid setup. Inspect `batch-manifest.jsonl` for individual failures. Resume validates saved identity, hashes and calculation evidence; corrupted outputs are not silently reused. Do not run two batches writing to the same output directory.

## Summary CSV across reports

```bash
gdcalc summary /path/to/a.gp11t /path/to/b.gp11t -o /path/to/new-results/summary.csv
gdcalc summary /path/to/batch-results -o /path/to/new-results/summary.csv
```

Writes one CSV row per report and final-summary load case. Report inputs use the same parser and default case selection as `inspect`; `--cases` and `--load-source` apply to every report input. A directory is treated as gdcalc output (batch or browser): each `.audit.json` is summarized from its `_source` report snapshot after checking the audited SHA-256, using the cases and load basis recorded in that audit. `--cases`/`--load-source` are rejected with a directory, even `--load-source effects`. The snapshot hash is checked before the snapshot is parsed; a symlinked audit, job folder or `_source` folder is rejected. A directory without audits, a missing or changed snapshot, an unresolved case selection or an unreadable report fails the whole command and writes nothing. The output must end in `.csv`, is written as UTF-8 with a byte-order mark (so Excel shows non-ASCII names) and is never overwritten. Overlapping inputs are skipped, not repeated, and listed in `duplicates_skipped` in the JSON result: the same resolved file twice (for example a directory and its subfolder), or a second input with identical source bytes, load basis and selected cases. The same report with a different selection is kept. The browser applies the same rule and requires at least two distinct reports.

| Column | Meaning |
| --- | --- |
| `report`, `origin` | Report filename; the input path or audit path (relative to the directory) it came from |
| `source_sha256` | SHA-256 of the report bytes |
| `load_source` | `effects` or `reactions` basis for Vy/Vz/My/Mz |
| `case_id`, `case_name`, `selected` | Every final-summary case; `selected` marks the cases used for the envelope |
| `P_kip`, `Vy_kip`, `Vz_kip`, `My_kip_in`, `Mz_kip_in` | That case's maximum compression and maximum component magnitudes over all piles |
| `governs` | Measures for which this selected case is the report's maximum (ties list every case) |

Component maxima may come from different piles and cases; they are not concurrent loads. Excluded (for example service) cases are listed but never govern. Report and case names that begin with `=`, `+`, `-`, `@` are prefixed with `'` so spreadsheets do not evaluate them. In the browser, **Download summary** on the Inputs step appears when two or more reports are loaded and includes every report with a resolved case selection, using each report's selected cases and the current load basis.

## Start and stop the browser

```bash
gdcalc serve --no-open --port 8765 \
  --template /path/to/reference.mcdx \
  --output-dir /path/to/browser-results
```

Open the printed URL. Omit `--template` to select it in the browser; omit `--no-open` to launch the browser automatically. `--port 0` chooses an available port. `GET /healthz` reports service health. Ctrl+C stops the server while retaining completed outputs.

Workflow: Files → Inputs → Changes → Outputs. Open Report/Template/Output file to inspect content; Results shows separate fresh Calcpad calculations. The original-file view is a reconstruction, not Prime rendering. Current UI cannot edit arbitrary equations. Saved outputs survive restart; the visible upload queue and temporary previews do not.

## Environment variables

Default template lookup: explicit `--template`, then `GDCALC_TEMPLATE`, checkout `assets/local/reference.mcdx`, `$XDG_CONFIG_HOME/gdcalc/reference.mcdx` (default `~/.config/gdcalc/reference.mcdx`), then `~/.agents/skills/gdcalc/assets/local/reference.mcdx`. The older `$CODEX_HOME/skills/gdcalc/assets/local/reference.mcdx` location remains a last compatibility fallback. No agent installation is required. An explicitly configured missing path is reported as missing rather than silently replaced by another template.

| Variable | Purpose |
| --- | --- |
| `GDCALC_TEMPLATE` | Private default template path; `--template` overrides it |
| `GDCALC_ENGINE_DIR` | Directory containing the built calculator |
| `GDCALC_CALCPAD` | Explicit calculator executable path |
| `PORT` | Server port; default 8765; `--port` overrides |
| `GDCALC_HOST` | Default bind host; use loopback for local work |
| `GDCALC_PUBLIC_URL` | Exact public origin for hosted mode |
| `GDCALC_OUTPUT_DIR` | Server output location; `--output-dir` overrides |
| `GDCALC_ACCESS_TOKEN` | Hosting secret, at least 32 characters |
| `GDCALC_ACCESS_TOKEN_FILE` | Read the hosting secret from this file; takes precedence |

For a host reachable over the network, follow [deployment instructions](../deploy/README.md). CLI startup does not automatically load `.env`; Compose reads it. `GDCALC_PORT`, `GDCALC_DOMAIN` and `GDCALC_IMAGE` in the example environment are Compose settings, distinct from direct CLI variables.

## Common recovery paths

| Failure | Recovery |
| --- | --- |
| Calculator missing | Run `setup-engine` once or configure the existing executable |
| Engine directory exists | Reuse it or choose a new `--install-dir`; do not overwrite it |
| Template missing | Pass/select a compatible private template |
| Unsupported expression | Report the exact construct and extend the adapter with tests; no cache fallback |
| Pile ID beyond template capacity | Review actual geometry before an explicit override |
| Unknown case names | Supply reviewed `--cases` |
| Output exists | Choose another basename, or verified batch resume |
| Summary file exists | Choose a new `-o` filename |
| Port occupied | Use `--port 0` or another port |
| Hosted login/origin error | Check exact HTTPS origin, secret and proxy Host forwarding; do not disable protections |
